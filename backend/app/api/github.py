from fastapi import APIRouter, HTTPException, Query

from app.mcp import client as mcp_client
from app.mcp.client import MCPToolError

github = APIRouter(prefix="/api")

REPO_PATTERN = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"


@github.get("/github/issues")
async def issues(repo: str = Query(pattern=REPO_PATTERN), state: str = "open", limit: int = 15) -> dict:
    try:
        return await mcp_client.list_issues(repo, state, limit)
    except MCPToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=502, detail="GitHub MCP server unavailable")


@github.get("/mcp/tools")
async def tools() -> list[dict]:
    """Tool discovery: what the MCP server says it can do."""
    try:
        return await mcp_client.list_tools()
    except Exception:
        raise HTTPException(status_code=502, detail="GitHub MCP server unavailable")