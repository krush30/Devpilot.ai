from langchain_core.runnables import RunnableConfig

from app.agents.base import MAX_ATTEMPTS, ask, emit
from app.graph.state import AgentState
from app.llm.router import AllProvidersFailed
from app.llm.utils import extract_json

SYSTEM = """You are the Planner in a team of software engineering agents.
Given a task about an existing codebase, break it into a short plan.
Reply with JSON only, in exactly this shape:
{"steps": ["3 to 6 short imperative steps"],
 "search_queries": ["2 to 4 natural-language queries for finding the relevant code"]}"""


async def planner(state: AgentState, config: RunnableConfig) -> dict:
    attempt = state.get("planner_attempts", 0) + 1
    await emit(config, "planner", "running", {"attempt": attempt})
    user = f"Task: {state['task']}"
    if state.get("error"):
        user += f"\n\nYour previous reply was rejected: {state['error']}. Reply with valid JSON only."
    try:
        text, provider = await ask([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
        data = extract_json(text)
        steps = [str(s) for s in data.get("steps", []) if str(s).strip()][:8]
        queries = [str(q) for q in data.get("search_queries", []) if str(q).strip()][:4]
        if not steps:
            raise ValueError("'steps' was empty")
    except AllProvidersFailed as e:
        await emit(config, "planner", "error", {"message": str(e)})
        return {"fatal": f"No model provider available: {e}"}
    except Exception as e:  # bad JSON, missing keys
        if attempt >= MAX_ATTEMPTS:
            await emit(config, "planner", "error", {"message": f"Could not produce a valid plan: {e}"})
            return {"planner_attempts": attempt, "fatal": f"Planner failed: {e}"}
        await emit(config, "planner", "retrying", {"reason": str(e)})
        return {"planner_attempts": attempt, "error": str(e)}
    await emit(config, "planner", "done", {"steps": steps, "queries": queries}, provider)
    return {"plan": steps, "queries": queries, "planner_attempts": attempt, "error": ""}