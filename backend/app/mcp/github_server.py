"""A read-only GitHub MCP server (stdio).

Run by the backend as a subprocess:  python -m app.mcp.github_server
Exposes four tools. There are deliberately no write tools: anything that changes GitHub
will go behind an approval gate in a later week.
"""
import functools
import os
import re
import sys
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

API_URL = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_BODY = 4000
MAX_PATCH = 3000
MAX_FILES = 30

server = MCPServer("devpilot-github", log_level="WARNING")


def tool(fn):
    """Register an MCP tool, turning unexpected crashes into a readable error.

    Without this, any bug inside a tool surfaces to the caller only as the useless message
    'Error executing tool <name>'. The details go to stderr (visible in the backend console).
    """
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception as e:
            print(f"[github-mcp] {fn.__name__} crashed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            raise ToolError(f"Unexpected error in {fn.__name__} ({type(e).__name__}). See the backend console.")

    return server.tool()(wrapper)


def _check_repo(repo: str) -> str:
    if not REPO_RE.match(repo or ""):
        raise ToolError("repo must look like 'owner/name'")
    return repo


def _clip(text: str | None, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "\n…[truncated]"


async def _get(path: str, params: dict | None = None) -> Any:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "devpilot-ai"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, max_redirects=3) as client:
            r = await client.get(f"{API_URL}{path}", params=params, headers=headers)
    except httpx.HTTPError as e:
        raise ToolError(f"Could not reach GitHub: {type(e).__name__}")
    if r.status_code == 404:
        raise ToolError("Not found. Check the repo name and number (private repos need GITHUB_TOKEN).")
    if r.status_code in (401, 403):
        hint = "" if TOKEN else " Set GITHUB_TOKEN to raise the rate limit."
        raise ToolError(f"GitHub refused the request ({r.status_code}): rate limit or missing access.{hint}")
    if r.status_code >= 400:
        raise ToolError(f"GitHub error {r.status_code}")
    try:
        return r.json()
    except ValueError:
        raise ToolError("GitHub returned a response that is not JSON")


def _need_list(data: Any) -> list:
    if not isinstance(data, list):
        raise ToolError("Unexpected response from GitHub (expected a list)")
    return data


def _labels(item: dict) -> list[str]:
    return [lb["name"] for lb in item.get("labels", []) if isinstance(lb, dict)]


@tool
async def list_issues(repo: str, state: str = "open", limit: int = 10) -> dict[str, Any]:
    """List issues in a GitHub repository ('owner/name'). state: open, closed or all."""
    _check_repo(repo)
    state = state if state in ("open", "closed", "all") else "open"
    # This endpoint also returns pull requests, which can dominate a busy repo's first page.
    # Fetch a full page, drop the PRs, then trim to the requested limit.
    data = _need_list(await _get(f"/repos/{repo}/issues", {"state": state, "per_page": 100}))
    issues = [
        {"number": i["number"], "title": i["title"], "labels": _labels(i), "url": i["html_url"],
         "comments": i.get("comments", 0)}
        for i in data if isinstance(i, dict) and "pull_request" not in i
    ][:min(max(limit, 1), 30)]
    return {"repo": repo, "issues": issues}


@tool
async def get_issue(repo: str, number: int) -> dict[str, Any]:
    """Get one issue: title, body, labels and its first comments."""
    _check_repo(repo)
    issue = await _get(f"/repos/{repo}/issues/{int(number)}")
    comments = _need_list(await _get(f"/repos/{repo}/issues/{int(number)}/comments", {"per_page": 5})) if issue.get("comments") else []
    return {
        "repo": repo, "number": issue["number"], "title": issue["title"], "state": issue["state"],
        "labels": _labels(issue), "url": issue["html_url"], "body": _clip(issue.get("body"), MAX_BODY),
        "comments": [{"author": c["user"]["login"], "body": _clip(c.get("body"), 1000)} for c in comments],
    }


@tool
async def list_pull_requests(repo: str, state: str = "open", limit: int = 10) -> dict[str, Any]:
    """List pull requests in a GitHub repository ('owner/name')."""
    _check_repo(repo)
    state = state if state in ("open", "closed", "all") else "open"
    data = _need_list(await _get(f"/repos/{repo}/pulls", {"state": state, "per_page": min(max(limit, 1), 30)}))
    return {"repo": repo, "pull_requests": [
        {"number": p["number"], "title": p["title"], "author": p["user"]["login"], "url": p["html_url"],
         "draft": p.get("draft", False)} for p in data]}


@tool
async def get_pull_request(repo: str, number: int) -> dict[str, Any]:
    """Get one pull request with its changed files and (truncated) patches."""
    _check_repo(repo)
    pr = await _get(f"/repos/{repo}/pulls/{int(number)}")
    files = _need_list(await _get(f"/repos/{repo}/pulls/{int(number)}/files", {"per_page": MAX_FILES}))
    return {
        "repo": repo, "number": pr["number"], "title": pr["title"], "state": pr["state"],
        "author": pr["user"]["login"], "url": pr["html_url"], "body": _clip(pr.get("body"), MAX_BODY),
        "additions": pr.get("additions"), "deletions": pr.get("deletions"),
        "files": [{"path": f["filename"], "status": f["status"], "additions": f["additions"],
                   "deletions": f["deletions"], "patch": _clip(f.get("patch"), MAX_PATCH)} for f in files],
    }


if __name__ == "__main__":
    server.run("stdio")