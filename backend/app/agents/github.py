"""Graph node: turn a GitHub issue (fetched through MCP) into the task text."""
from langchain_core.runnables import RunnableConfig

from app.agents.base import emit
from app.graph.state import AgentState
from app.mcp.client import MCPToolError, get_issue


async def github(state: AgentState, config: RunnableConfig) -> dict:
    repo, number = state["github_repo"], state["issue_number"]
    await emit(config, "github", "running", {"repo": repo, "number": number})
    try:
        issue = await get_issue(repo, number)
    except MCPToolError as e:
        await emit(config, "github", "error", {"message": str(e)})
        return {"fatal": f"GitHub: {e}"}
    except Exception as e:  # server failed to start, protocol error, ...
        await emit(config, "github", "error", {"message": f"Could not use the GitHub MCP server: {type(e).__name__}"})
        return {"fatal": "GitHub MCP server unavailable"}

    comments = "\n".join(f"- {c['author']}: {c['body']}" for c in issue.get("comments", []))
    extra = f"\n\nExtra instructions from the user: {state['task']}" if state.get("task") else ""
    task = (f"Resolve GitHub issue #{issue['number']}: {issue['title']}\n\n"
            f"<github_issue>\n{issue['body']}\n"
            + (f"\nComments:\n{comments}\n" if comments else "")
            + f"</github_issue>{extra}")
    await emit(config, "github", "done", {
        "title": issue["title"], "number": issue["number"], "url": issue["url"],
        "labels": issue["labels"], "state": issue["state"],
    })
    return {"task": task}