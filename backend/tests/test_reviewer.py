import json

from app.agents import analyst as analyst_mod
from app.agents import base
from app.agents import planner as planner_mod
from app.agents.reviewer import normalize
from app.graph.workflow import build_graph
from app.llm.router import AllProvidersFailed
from app.security.static_checks import scan_changes

HIT = {"path": "app/main.py", "start_line": 10, "end_line": 14, "score": 0.9,
       "text": "@app.get('/health')\ndef health():\n    return {'status': 'ok'}\n"}
OK_CODE = "def health():\n    return 1"
PLAN = json.dumps({"steps": ["s"], "search_queries": ["q"]})


def coder_reply(new):
    return json.dumps({"summary": "s", "changes": [{
        "path": "app/main.py", "action": "modify", "explanation": "e",
        "old": "def health():", "new": new}]})


def review(verdict="approve", findings=()):
    return json.dumps({"verdict": verdict, "summary": "sum", "findings": list(findings), "suggested_tests": ["t1"]})


MEDIUM = {"severity": "medium", "path": "app/main.py", "issue": "no error handling", "suggestion": "add try/except"}


class FakeLLM:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    async def chat(self, messages, **kw):
        self.seen.append(messages)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r, "fake"


async def run(monkeypatch, replies):
    fake = FakeLLM(replies)
    monkeypatch.setattr(base, "llm", fake)
    monkeypatch.setattr(analyst_mod, "search", lambda *a, **k: [HIT])
    monkeypatch.setattr(planner_mod, "list_files", lambda *a, **k: ["app/main.py"])
    events = []

    async def emit(ev):
        events.append(ev)

    final = await build_graph().ainvoke({"task": "do it", "repo_id": "r"}, config={"configurable": {"emit": emit}})
    return final, fake, events


# ---- static checks ---------------------------------------------------------------------------

def test_static_checks_flag_new_risky_lines_only():
    changes = [{"path": "a.py", "line": 5, "old": "x = eval(y)",
                "new": "x = eval(y)\ntoken = 'abcdefghijklmnop'\nsubprocess.run(c, shell=True)\nrequests.get(u, verify=False)"}]
    rules = {f["rule"] for f in scan_changes(changes)}
    assert rules == {"Possible hardcoded secret", "Shell command execution", "TLS certificate verification disabled"}
    assert all(f["severity"] == "high" for f in scan_changes(changes))  # pre-existing eval is not re-flagged


def test_static_checks_leave_clean_code_alone():
    assert scan_changes([{"path": "a.py", "old": "", "new": "def add(a, b):\n    return a + b"}]) == []


def test_normalize_rules():
    clean = normalize({"verdict": "revise", "findings": [{"severity": "low", "issue": "nit"}]}, [])
    assert clean["verdict"] == "approve"  # "revise" needs a real high/medium finding
    forced = normalize({"verdict": "approve", "findings": []},
                       [{"severity": "high", "path": "a.py", "rule": "eval/exec on dynamic input", "text": "eval(x)"}])
    assert forced["verdict"] == "revise" and forced["findings"][0]["severity"] == "high"


# ---- the review loop -------------------------------------------------------------------------

async def test_approved_proposal_goes_straight_through(monkeypatch):
    final, fake, events = await run(monkeypatch, [PLAN, "analysis", coder_reply(OK_CODE), review()])
    assert final["review"]["verdict"] == "approve" and final["review"]["suggested_tests"] == ["t1"]
    assert len(fake.seen) == 4 and final["proposal"]


async def test_medium_finding_sends_work_back_once_and_feedback_reaches_coder(monkeypatch):
    final, fake, events = await run(monkeypatch, [
        PLAN, "analysis", coder_reply(OK_CODE), review("revise", [MEDIUM]),
        coder_reply("def health():\n    return 2  # fixed"), review("approve"),
    ])
    coder_prompts = [m[1]["content"] for m in fake.seen if m[0]["content"].startswith("You are the Coder")]
    assert len(coder_prompts) == 2 and "reviewer rejected" in coder_prompts[1] and "no error handling" in coder_prompts[1]
    assert "fixed" in final["proposal"]["changes"][0]["diff"] and final["review"]["verdict"] == "approve"
    reviews = [e for e in events if e["agent"] == "reviewer" and e["status"] == "done"]
    assert [r["data"]["sent_back"] for r in reviews] == [True, False]


async def test_static_high_flag_forces_revision_even_if_llm_approves(monkeypatch):
    final, fake, _ = await run(monkeypatch, [
        PLAN, "analysis", coder_reply("def health():\n    return eval(x)"), review("approve"),
        coder_reply(OK_CODE), review("approve"),
    ])
    assert "eval" not in final["proposal"]["changes"][0]["diff"] and final["review"]["static_flags"] == []


async def test_revision_is_limited_and_remaining_findings_are_shown(monkeypatch):
    final, fake, _ = await run(monkeypatch, [
        PLAN, "analysis", coder_reply(OK_CODE), review("revise", [MEDIUM]),
        coder_reply(OK_CODE), review("revise", [MEDIUM]),
    ])
    assert final["review"]["verdict"] == "revise" and final["proposal"]  # no endless loop; user decides
    assert len(fake.seen) == 6


async def test_reviewer_failure_degrades_to_unreviewed(monkeypatch):
    final, _, events = await run(monkeypatch, [PLAN, "analysis", coder_reply(OK_CODE), "not json", "still not"])
    assert final["review"]["verdict"] == "unreviewed" and final["proposal"]
    final, _, _ = await run(monkeypatch, [PLAN, "analysis", coder_reply(OK_CODE), AllProvidersFailed("down")])
    assert final["review"]["verdict"] == "unreviewed" and "no model provider" in final["review"]["summary"]


async def test_failed_revision_keeps_the_first_proposal(monkeypatch):
    final, _, _ = await run(monkeypatch, [
        PLAN, "analysis", coder_reply(OK_CODE), review("revise", [MEDIUM]), AllProvidersFailed("down")])
    assert final["fatal"] and final["prev_proposal"]["changes"]  # the API saves prev_proposal