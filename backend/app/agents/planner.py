import asyncio

from langchain_core.runnables import RunnableConfig

from app.agents.base import MAX_ATTEMPTS, ask, emit
from app.graph.state import AgentState
from app.llm.router import AllProvidersFailed
from app.llm.utils import extract_json
from app.rag.overview import list_files

SYSTEM = """You are the Planner in a team of software engineering agents.
Given a task and the list of files in the repository, decide whether the task is actionable,
and if so break it into a short plan. Reply with JSON only, in exactly this shape:
{"clear": true or false,
 "question": "only when clear is false: ONE specific question for the user",
 "steps": ["3 to 6 short imperative steps"],
 "search_queries": ["2 to 4 natural-language queries for finding the relevant code"]}
Set "clear" to false if the task is vague (for example "make it better"), unrelated to the
files listed, or needs a decision only the user can make.
Only plan steps that fit the language and frameworks visible in the file list.
Do not suggest tools or frameworks the repository does not use."""

DEFAULT_QUESTION = "Could you describe specifically what should change, and in which part of the code?"


async def planner(state: AgentState, config: RunnableConfig) -> dict:
    attempt = state.get("planner_attempts", 0) + 1
    await emit(config, "planner", "running", {"attempt": attempt})
    files = await asyncio.to_thread(list_files, state["repo_id"])
    user = f"Task: {state['task']}\n\nRepository files:\n" + "\n".join(files)
    if state.get("error"):
        user += f"\n\nYour previous reply was rejected: {state['error']}. Reply with valid JSON only."
    try:
        # Same task + same file list => same plan, so repeat runs skip this call. (Not cached for the coder:
        # re-running a task should give a fresh attempt.)
        text, provider = await ask([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], cache=True)
        data = extract_json(text)
        if data.get("clear", True) is False:
            question = str(data.get("question", "")).strip() or DEFAULT_QUESTION
            await emit(config, "planner", "needs_input", {"question": question}, provider)
            return {"question": question, "planner_attempts": attempt}
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