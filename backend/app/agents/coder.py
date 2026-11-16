import difflib
import re

from langchain_core.runnables import RunnableConfig

from app.agents.base import MAX_ATTEMPTS, ask, emit
from app.graph.state import AgentState
from app.llm.router import AllProvidersFailed
from app.llm.utils import extract_json
from app.rag.retrieval import format_context

MAX_CHANGES = 5

SYSTEM = """You are the Coder in a team of software engineering agents.
You propose code changes; you never apply them. Reply with JSON only, in exactly this shape:
{"summary": "one or two sentences",
 "changes": [
   {"path": "relative/file/path",
    "action": "modify" or "create",
    "explanation": "why this change",
    "old": "for modify: the exact existing code to replace, copied verbatim from the excerpts",
    "new": "the replacement code (for create: the full new file)"}
 ]}
Rules:
- Copy "old" exactly as it appears in the excerpts, WITHOUT the "N: " line-number prefixes.
- Keep changes small and focused, at most 5. Follow the conventions of the surrounding code.
- Only modify files that appear in the excerpts."""

_NUM_PREFIX = re.compile(r"^\d+:( |$)")


def strip_line_numbers(code: str) -> str:
    """Models sometimes copy the 'N: ' prefixes from the excerpts; remove them if present."""
    lines = code.splitlines()
    if lines and all(_NUM_PREFIX.match(line) for line in lines):
        return "\n".join(_NUM_PREFIX.sub("", line) for line in lines)
    return code


def _norm(code: str) -> str:
    return "\n".join(line.rstrip() for line in code.strip("\n").splitlines())


def locate(path: str, old: str, hits: list[dict]) -> int | None:
    """Return the real line number where `old` starts, or None if it isn't in the retrieved code."""
    needle = _norm(old)
    if not needle:
        return None
    for h in hits:
        if h["path"] != path:
            continue
        hay = _norm(h["text"])
        idx = hay.find(needle)
        if idx != -1:
            return h["start_line"] + hay[:idx].count("\n")
    return None


def make_diff(path: str, action: str, old: str, new: str) -> str:
    old_lines = old.splitlines() if action == "modify" else []
    return "\n".join(difflib.unified_diff(
        old_lines, new.splitlines(),
        f"a/{path}" if action == "modify" else "/dev/null", f"b/{path}",
        lineterm="", n=1,
    ))


def build_proposal(data: dict, hits: list[dict]) -> dict:
    changes = []
    for c in data.get("changes", [])[:MAX_CHANGES]:
        path, action = str(c.get("path", "")).strip(), str(c.get("action", "modify")).strip()
        if not path or action not in ("modify", "create"):
            continue
        old = strip_line_numbers(str(c.get("old", "")))
        new = strip_line_numbers(str(c.get("new", "")))
        line = locate(path, old, hits) if action == "modify" else None
        changes.append({
            "path": path, "action": action, "explanation": str(c.get("explanation", "")),
            "line": line,
            # Guardrail: a modify is only "verified" if its `old` text really exists in the repo.
            "verified": action == "create" or line is not None,
            "diff": make_diff(path, action, old, new),
        })
    if not changes:
        raise ValueError("no valid changes in reply")
    return {"summary": str(data.get("summary", "")), "changes": changes}


async def coder(state: AgentState, config: RunnableConfig) -> dict:
    attempt = state.get("coder_attempts", 0) + 1
    await emit(config, "coder", "running", {"attempt": attempt})
    plan = "\n".join(f"- {s}" for s in state.get("plan", []))
    user = (f"Task: {state['task']}\n\nPlan:\n{plan}\n\nAnalysis:\n{state.get('analysis', '')}\n\n"
            f"Repository excerpts:\n{format_context(state.get('hits', []))}")
    if state.get("error"):
        user += f"\n\nYour previous reply was rejected: {state['error']}"
    try:
        text, provider = await ask([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
        proposal = build_proposal(extract_json(text), state.get("hits", []))
        bad = [c["path"] for c in proposal["changes"] if not c["verified"]]
        if bad and attempt < MAX_ATTEMPTS:
            raise ValueError(
                f"the 'old' code for {', '.join(bad)} was not found in the excerpts; "
                "copy it exactly, without line-number prefixes")
    except AllProvidersFailed as e:
        await emit(config, "coder", "error", {"message": str(e)})
        return {"fatal": f"No model provider available: {e}"}
    except Exception as e:
        if attempt >= MAX_ATTEMPTS:
            await emit(config, "coder", "error", {"message": f"Could not produce a valid proposal: {e}"})
            return {"coder_attempts": attempt, "fatal": f"Coder failed: {e}"}
        await emit(config, "coder", "retrying", {"reason": str(e)})
        return {"coder_attempts": attempt, "error": str(e)}
    await emit(config, "coder", "done", proposal, provider)
    return {"proposal": proposal, "coder_attempts": attempt, "error": ""}