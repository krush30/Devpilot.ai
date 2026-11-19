import json

import pytest

from app.agents import analyst as analyst_mod
from app.agents import planner as planner_mod
from app.agents import base
from app.agents.coder import check_syntax, locate, make_diff, real_hunks, strip_line_numbers
from app.graph.workflow import build_graph
from app.llm.router import AllProvidersFailed
from app.llm.utils import extract_json

HIT = {
    "path": "app/main.py", "start_line": 10, "end_line": 14, "score": 0.9,
    "text": "@app.get('/health')\ndef health():\n    return {'status': 'ok'}\n",
}
REVIEW_OK = json.dumps({"verdict": "approve", "summary": "ok", "findings": [], "suggested_tests": []})
PLAN = json.dumps({"steps": ["find health route", "add models route"], "search_queries": ["health route"]})


def change(old):
    return json.dumps({"summary": "add route", "changes": [{
        "path": "app/main.py", "action": "modify", "explanation": "why",
        "old": old, "new": "def health():\n    return {'status': 'ok', 'v': 1}",
    }]})


class FakeLLM:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    async def chat(self, messages, **kw):
        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply, "fake"


@pytest.fixture
def events():
    return []


async def run(monkeypatch, replies, hits, events):
    fake = FakeLLM(replies)
    monkeypatch.setattr(base, "llm", fake)

    async def fake_search(*a, **k):  # to_thread target replaced below
        return hits

    monkeypatch.setattr(analyst_mod, "search", lambda *a, **k: hits)
    monkeypatch.setattr(planner_mod, "list_files", lambda *a, **k: ["app/main.py"])

    async def emit(ev):
        events.append(ev)

    final = await build_graph().ainvoke(
        {"task": "add a models endpoint", "repo_id": "repo_x"},
        config={"configurable": {"emit": emit}},
    )
    return final, fake


async def test_happy_path_retries_bad_planner_json(monkeypatch, events):
    final, fake = await run(
        monkeypatch,
        ["not json at all", PLAN, "The health route lives in app/main.py:10.", change("def health():\n    return {'status': 'ok'}"), REVIEW_OK],
        [HIT], events,
    )
    assert final["planner_attempts"] == 2
    change0 = final["proposal"]["changes"][0]
    assert change0["verified"] and change0["line"] == 11
    assert "+    return {'status': 'ok', 'v': 1}" in change0["diff"]
    agents = [(e["agent"], e["status"]) for e in events]
    assert ("planner", "retrying") in agents and ("coder", "done") in agents


async def test_stops_when_nothing_found(monkeypatch, events):
    final, fake = await run(monkeypatch, [PLAN], [], events)
    assert "No sufficiently relevant code" in final["fatal"]
    assert fake.calls == 1  # coder and analyst LLM calls never happened


async def test_coder_retries_when_old_code_not_in_repo(monkeypatch, events):
    final, _ = await run(
        monkeypatch,
        [PLAN, "analysis", change("this code does not exist"), change("def health():"), REVIEW_OK],
        [HIT], events,
    )
    assert final["coder_attempts"] == 2 and final["proposal"]["changes"][0]["verified"]


async def test_all_providers_failed_is_fatal(monkeypatch, events):
    final, _ = await run(monkeypatch, [AllProvidersFailed("down")], [HIT], events)
    assert "No model provider" in final["fatal"]


def test_extract_json_handles_think_and_fences():
    text = '<think>hmm</think>Sure!\n```json\n{"a": 1}\n```'
    assert extract_json(text) == {"a": 1}
    with pytest.raises(ValueError):
        extract_json("nothing here")


def test_strip_line_numbers_only_when_all_lines_prefixed():
    assert strip_line_numbers("5: a\n6: \n7: b") == "a\n\nb"
    assert strip_line_numbers("5: a\nplain") == "5: a\nplain"


def test_locate_and_diff():
    assert locate("app/main.py", "def health():", [HIT]) == 11
    assert locate("other.py", "def health():", [HIT]) is None
    d = make_diff("a.py", "create", "", "x = 1")
    assert d.startswith("--- /dev/null") and "+x = 1" in d


async def test_sse_endpoint_streams_events(monkeypatch):
    import httpx

    from app.api import tasks as tasks_mod
    from app.main import app

    class Col:
        def count(self):
            return 3

    monkeypatch.setattr(tasks_mod, "get_collection", lambda _id: Col())
    monkeypatch.setattr(base, "llm", FakeLLM([PLAN, "analysis", change("def health():"), REVIEW_OK]))
    monkeypatch.setattr(analyst_mod, "search", lambda *a, **k: [HIT])
    monkeypatch.setattr(planner_mod, "list_files", lambda *a, **k: ["app/main.py"])

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post("/api/tasks/run", json={"task": "add a models endpoint", "repo_id": "repo_x"})
        events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
        missing = await client.post("/api/tasks/run", json={"task": "x" * 10, "repo_id": "r"})
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert [e["agent"] for e in events if e["status"] == "done"] == ["planner", "analyst", "coder", "reviewer"]
    assert events[-1]["agent"] == "system" and events[-1]["data"]["ok"] is True
    assert events[-1]["data"]["proposal_id"]
    assert "old" not in json.dumps([e for e in events if e["agent"] == "coder"])  # raw code stays server-side


VAGUE = json.dumps({"clear": False, "question": "Which part should be improved: speed, tests, or structure?"})


async def test_vague_task_asks_a_question_and_stops(monkeypatch, events):
    final, fake = await run(monkeypatch, [VAGUE], [HIT], events)
    assert final["question"].startswith("Which part")
    assert fake.calls == 1 and not final.get("proposal") and not final.get("fatal")
    assert ("planner", "needs_input") in [(e["agent"], e["status"]) for e in events]
    assert not any(e["agent"] == "analyst" for e in events)


async def test_low_relevance_stops_before_coder(monkeypatch, events):
    weak = {**HIT, "score": 0.05}
    final, fake = await run(monkeypatch, [PLAN], [weak], events)
    assert "No sufficiently relevant code" in final["fatal"] and fake.calls == 1


def broken_change():
    return json.dumps({"summary": "s", "changes": [{
        "path": "app/main.py", "action": "modify", "explanation": "x",
        "old": "def health():", "new": "def health(:\n    pass"}]})


async def test_syntax_error_triggers_retry(monkeypatch, events):
    final, _ = await run(
        monkeypatch, [PLAN, "analysis", broken_change(), change("def health():"), REVIEW_OK], [HIT], events)
    assert final["coder_attempts"] == 2 and final["proposal"]["changes"][0]["syntax"] == "ok"


async def test_skipped_steps_are_reported(monkeypatch, events):
    reply = json.loads(change("def health():"))
    reply["skipped_steps"] = [{"step": "write tests", "reason": "out of scope"}]
    final, _ = await run(monkeypatch, [PLAN, "analysis", json.dumps(reply), REVIEW_OK], [HIT], events)
    assert final["proposal"]["skipped"] == ["write tests: out of scope"]


def test_check_syntax_dedents_and_skips_non_python():
    assert check_syntax("a.py", "    x = 1\n    y = 2")[0] == "ok"
    assert check_syntax("a.py", "def f(:")[0] == "error"
    assert check_syntax("a.ts", "const = ;")[0] == "skipped"


def test_hunk_headers_use_real_line_numbers():
    diff = make_diff("a.py", "modify", "x = 1", "x = 2")
    assert "@@ -1 +1 @@" in diff
    assert "@@ -40 +40 @@" in real_hunks(diff, 40)
    assert real_hunks(diff, None) == diff