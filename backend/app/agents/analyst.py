import asyncio

from langchain_core.runnables import RunnableConfig

from app.agents.base import ask, emit
from app.graph.state import AgentState
from app.llm.router import AllProvidersFailed
from app.rag.retrieval import format_context, search

MAX_HITS = 8

SYSTEM = """You are the Code Analyst in a team of software engineering agents.
You are given a task, a plan, and numbered excerpts from the repository.
In under 200 words, explain: which files are relevant, which existing patterns and
conventions the change must follow, and where exactly the change belongs.
Cite as path:line using only the line numbers shown. Do not invent files."""


async def analyst(state: AgentState, config: RunnableConfig) -> dict:
    await emit(config, "analyst", "running")
    queries = [state["task"], *state.get("queries", [])]
    best: dict[tuple, dict] = {}
    for q in queries:
        for h in await asyncio.to_thread(search, state["repo_id"], q, 4):
            key = (h["path"], h["start_line"])
            if key not in best or h["score"] > best[key]["score"]:
                best[key] = h
    hits = sorted(best.values(), key=lambda h: h["score"], reverse=True)[:MAX_HITS]
    files = [{k: h[k] for k in ("path", "start_line", "end_line", "score")} for h in hits]
    if not hits:
        msg = "No relevant code found. Is the repository indexed?"
        await emit(config, "analyst", "error", {"message": msg})
        return {"hits": [], "fatal": msg}

    plan = "\n".join(f"- {s}" for s in state.get("plan", []))
    user = f"Task: {state['task']}\n\nPlan:\n{plan}\n\nRepository excerpts:\n{format_context(hits)}"
    try:
        analysis, provider = await ask([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
    except AllProvidersFailed as e:
        await emit(config, "analyst", "error", {"message": str(e)})
        return {"fatal": f"No model provider available: {e}"}
    await emit(config, "analyst", "done", {"files": files, "analysis": analysis}, provider)
    return {"hits": hits, "analysis": analysis}