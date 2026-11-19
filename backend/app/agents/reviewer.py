from langchain_core.runnables import RunnableConfig

from app.agents.base import ask, emit
from app.graph.state import AgentState
from app.llm.router import AllProvidersFailed
from app.llm.utils import extract_json
from app.rag.retrieval import format_context
from app.security.static_checks import scan_changes

MAX_REVIEW_ROUNDS = 1  # how many times the reviewer may send work back to the coder

SYSTEM = """You are the Reviewer in a team of software engineering agents.
You review a proposed code change. You do not write code.
Check, in order of importance: (1) does it actually solve the task, (2) bugs and unhandled edge
cases, (3) security problems (injection, secrets, unsafe input, disabled checks), (4) consistency
with the existing code in the excerpts, (5) missing tests.
Only report real problems you can point to in the diff. No style nitpicks and no speculation.
Reply with JSON only, in exactly this shape:
{"verdict": "approve" or "revise",
 "summary": "one or two sentences",
 "findings": [{"severity": "high" or "medium" or "low", "path": "file", "issue": "what is wrong", "suggestion": "how to fix it"}],
 "suggested_tests": ["short descriptions of tests that should accompany this change"]}
Use "revise" only if there is at least one high or medium finding."""

SEVERITIES = ("high", "medium", "low")


def normalize(data: dict, flags: list[dict]) -> dict:
    verdict = str(data.get("verdict", "")).lower()
    if verdict not in ("approve", "revise"):
        raise ValueError("'verdict' must be 'approve' or 'revise'")
    findings = []
    for f in data.get("findings", [])[:8]:
        if not isinstance(f, dict):
            continue
        sev = str(f.get("severity", "low")).lower()
        findings.append({"severity": sev if sev in SEVERITIES else "low", "path": str(f.get("path", "")),
                         "issue": str(f.get("issue", "")), "suggestion": str(f.get("suggestion", ""))})
    # Deterministic findings are always included, and a high one forces a revision.
    for fl in flags:
        if fl["severity"] == "high":
            findings.append({"severity": "high", "path": fl["path"], "issue": f"{fl['rule']}: {fl['text']}",
                             "suggestion": "Remove or replace this with a safe alternative."})
    serious = any(f["severity"] in ("high", "medium") for f in findings)
    if any(fl["severity"] == "high" for fl in flags):
        verdict = "revise"
    elif verdict == "revise" and not serious:
        verdict = "approve"  # "revise" requires a real high/medium finding
    return {
        "verdict": verdict, "summary": str(data.get("summary", "")), "findings": findings,
        "suggested_tests": [str(t) for t in data.get("suggested_tests", [])[:5]], "static_flags": flags,
    }


def feedback_text(review: dict) -> str:
    lines = [f"- [{f['severity']}] {f['path']}: {f['issue']} Fix: {f['suggestion']}"
             for f in review["findings"] if f["severity"] in ("high", "medium")]
    return "\n".join(lines)


async def reviewer(state: AgentState, config: RunnableConfig) -> dict:
    rounds = state.get("review_rounds", 0)
    await emit(config, "reviewer", "running", {"round": rounds + 1})
    proposal = state["proposal"]
    flags = scan_changes(proposal["changes"])

    diffs = "\n\n".join(
        f"### {c['path']} ({c['action']}, line {c.get('line') or '?'})\nWhy: {c['explanation']}\n{c['diff']}"
        for c in proposal["changes"])
    user = (f"Task: {state['task']}\n\nCoder's summary: {proposal['summary']}\n\n"
            f"Proposed changes:\n{diffs}\n\nRepository excerpts:\n{format_context(state.get('hits', []))}")
    if flags:
        user += "\n\nAutomated checks flagged:\n" + "\n".join(
            f"- [{f['severity']}] {f['path']}: {f['rule']}: {f['text']}" for f in flags)

    review, provider, last_error = None, None, ""
    for _ in range(2):  # one retry for malformed output
        try:
            text, provider = await ask([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
            review = normalize(extract_json(text), flags)
            break
        except AllProvidersFailed as e:
            last_error = f"no model provider available ({e})"
            break
        except Exception as e:
            last_error = str(e)
            user += f"\n\nYour previous reply was rejected: {e}. Reply with valid JSON only."

    if review is None:
        # The reviewer failing must not block the user: show the proposal clearly marked unreviewed.
        review = {"verdict": "unreviewed", "summary": f"The reviewer could not run: {last_error}",
                  "findings": [], "suggested_tests": [], "static_flags": flags}
        await emit(config, "reviewer", "error", {"message": review["summary"], "static_flags": flags})
        return {"review": review, "revise": False}

    revise = review["verdict"] == "revise" and rounds < MAX_REVIEW_ROUNDS
    await emit(config, "reviewer", "done", {**review, "round": rounds + 1, "sent_back": revise}, provider)
    if not revise:
        return {"review": review, "revise": False}
    return {"review": review, "revise": True, "review_rounds": rounds + 1,
            "review_feedback": feedback_text(review), "prev_proposal": proposal,
            "proposal": {}, "coder_attempts": 0, "error": ""}