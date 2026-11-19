"""MCP client: starts the GitHub MCP server as a subprocess and calls its tools."""
import os
import sys
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

from app.core.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[2]  # the folder containing `app/`


class MCPToolError(Exception):
    """A tool ran but reported an error (bad repo, rate limit, ...). The message is user-safe."""


# The server subprocess starts with a minimal environment, so forward network settings explicitly.
PASSTHROUGH = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE")


def _params() -> StdioServerParameters:
    env = {"GITHUB_TOKEN": getattr(settings, "github_token", "")}
    for key in PASSTHROUGH:
        for name in (key, key.lower()):
            if os.environ.get(name):
                env[name] = os.environ[name]
    if os.environ.get("GITHUB_API_URL"):
        env["GITHUB_API_URL"] = os.environ["GITHUB_API_URL"]
    return StdioServerParameters(
        command=sys.executable, args=["-m", "app.mcp.github_server"], env=env, cwd=str(BACKEND_DIR),
    )


async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    # One short-lived server process per call: simple and robust. A persistent session is a
    # later optimisation (the protocol is the same).
    async with Client(_params()) as client:
        result = await client.call_tool(name, arguments)
    if result.is_error:
        text = " ".join(getattr(c, "text", "") for c in result.content)
        raise MCPToolError(text.split(": ", 1)[-1] if ": " in text else text or "Tool failed")
    return result.structured_content or {}


async def list_tools() -> list[dict[str, Any]]:
    async with Client(_params()) as client:
        res = await client.list_tools()
    return [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in res.tools]


async def list_issues(repo: str, state: str = "open", limit: int = 10) -> dict[str, Any]:
    return await call_tool("list_issues", {"repo": repo, "state": state, "limit": limit})


async def get_issue(repo: str, number: int) -> dict[str, Any]:
    return await call_tool("get_issue", {"repo": repo, "number": number})