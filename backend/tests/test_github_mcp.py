"""MCP tests. The end-to-end ones start the REAL MCP server subprocess over stdio and point it
at a tiny fake GitHub API running on localhost, so no network or token is needed."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from pydantic import ValidationError

from app.agents import github as github_mod
from app.agents import planner as planner_mod
from app.agents import base
from app.graph.workflow import build_graph
from app.mcp import client as mcp
from app.mcp.client import MCPToolError
from app.schemas.task import TaskRequest

ISSUE = {"number": 7, "title": "Add models endpoint", "state": "open", "labels": [{"name": "enhancement"}],
         "html_url": "https://github.com/o/r/issues/7", "body": "Please add GET /api/llm/models.", "comments": 1}
ROUTES = {
    "/repos/o/r/issues": [ISSUE, {**ISSUE, "number": 8, "title": "A PR", "pull_request": {}}],
    "/repos/o/r/issues/7": ISSUE,
    "/repos/o/r/issues/7/comments": [{"user": {"login": "sam"}, "body": "+1, needs tests too"}],
}


LAST_QUERY = {}
PR_HEAVY = [{**ISSUE, "number": 100 + n, "title": f"PR {n}", "pull_request": {}} for n in range(30)] + [ISSUE]
ROUTES["/repositories/1/issues"] = [ISSUE]
ROUTES["/repos/o/prs/issues"] = PR_HEAVY
ROUTES["/repos/o/weird/issues"] = [{"title": "no number field", "html_url": "x"}]


class Fake(BaseHTTPRequestHandler):
    def do_GET(self):
        path, _, query = self.path.partition("?")
        LAST_QUERY[path] = query
        if path == "/repos/old/name/issues":  # a renamed repo: GitHub answers 301 + JSON body
            self.send_response(301)
            self.send_header("Location", f"http://{self.headers['Host']}/repositories/1/issues")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"message": "Moved Permanently"}).encode())
            return
        data = ROUTES.get(path)
        self.send_response(200 if data is not None else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data if data is not None else {"message": "Not Found"}).encode())

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def fake_github():
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture
def api_url(fake_github, monkeypatch):
    monkeypatch.setenv("GITHUB_API_URL", fake_github)


async def test_tool_discovery(api_url):
    names = {t["name"] for t in await mcp.list_tools()}
    assert names == {"list_issues", "get_issue", "list_pull_requests", "get_pull_request"}


async def test_list_issues_skips_pull_requests(api_url):
    res = await mcp.list_issues("o/r")
    assert [i["number"] for i in res["issues"]] == [7]
    assert res["issues"][0]["labels"] == ["enhancement"]


async def test_get_issue_includes_comments(api_url):
    issue = await mcp.get_issue("o/r", 7)
    assert issue["title"] == "Add models endpoint" and issue["comments"][0]["author"] == "sam"


async def test_not_found_becomes_friendly_error(api_url):
    with pytest.raises(MCPToolError, match="Not found"):
        await mcp.get_issue("o/missing", 1)


async def test_bad_repo_name_rejected_by_server(api_url):
    with pytest.raises(MCPToolError, match="owner/name"):
        await mcp.call_tool("get_issue", {"repo": "../../etc/passwd", "number": 1})


# ---- graph integration (GitHub call mocked) ----------------------------------------------

class FakeLLM:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    async def chat(self, messages, **kw):
        self.seen.append(messages)
        return self.replies.pop(0), "fake"


PLAN = json.dumps({"steps": ["s1"], "search_queries": ["q"]})


async def run_graph(monkeypatch, replies, **state):
    fake = FakeLLM(replies)
    monkeypatch.setattr(base, "llm", fake)
    monkeypatch.setattr(planner_mod, "list_files", lambda *a, **k: ["app/main.py"])
    events = []

    async def emit(ev):
        events.append(ev)

    final = await build_graph().ainvoke(
        {"repo_id": "r", **state}, config={"configurable": {"emit": emit}})
    return final, fake, events


async def test_issue_becomes_wrapped_task_and_untrusted_note(monkeypatch):
    async def fake_get_issue(repo, number):
        return {**ISSUE, "labels": ["enhancement"], "url": ISSUE["html_url"],
                "comments": [{"author": "sam", "body": "needs tests"}]}

    monkeypatch.setattr(github_mod, "get_issue", fake_get_issue)
    vague = json.dumps({"clear": False, "question": "?"})  # stop right after the planner
    final, fake, events = await run_graph(
        monkeypatch, [vague], task="", github_repo="o/r", issue_number=7)
    assert final["task"].startswith("Resolve GitHub issue #7: Add models endpoint")
    assert "<github_issue>" in final["task"] and "sam: needs tests" in final["task"]
    system_prompt = fake.seen[0][0]["content"]
    assert "untrusted data" in system_prompt
    assert [e["agent"] for e in events][:2] == ["github", "github"]


async def test_github_failure_stops_run(monkeypatch):
    async def boom(repo, number):
        raise MCPToolError("Not found.")

    monkeypatch.setattr(github_mod, "get_issue", boom)
    final, fake, events = await run_graph(monkeypatch, [], task="", github_repo="o/r", issue_number=7)
    assert final["fatal"] == "GitHub: Not found." and not fake.seen


# ---- request schema ----------------------------------------------------------------------

def test_task_or_issue_required():
    TaskRequest(repo_id="r", task="add a feature")
    TaskRequest(repo_id="r", github_repo="o/r", issue_number=3)
    with pytest.raises(ValidationError):
        TaskRequest(repo_id="r", task="hi")
    with pytest.raises(ValidationError):
        TaskRequest(repo_id="r", github_repo="not a repo", issue_number=3)


async def test_renamed_repo_redirect_is_followed(api_url):
    # Regression: facebook/react moved to react/react; the 301 used to crash the tool.
    res = await mcp.list_issues("old/name")
    assert [i["number"] for i in res["issues"]] == [7]


async def test_issue_list_is_not_starved_by_pull_requests(api_url):
    res = await mcp.list_issues("o/prs", limit=5)
    assert [i["number"] for i in res["issues"]] == [7]
    assert "per_page=100" in LAST_QUERY["/repos/o/prs/issues"]


async def test_tool_schema_survives_error_wrapper(api_url):
    tools = {t["name"]: t for t in await mcp.list_tools()}
    assert set(tools["list_issues"]["input_schema"]["properties"]) == {"repo", "state", "limit"}


async def test_unexpected_crash_gives_readable_error_not_generic(api_url):
    with pytest.raises(MCPToolError, match=r"Unexpected error in list_issues \(KeyError\)"):
        await mcp.list_issues("o/weird")