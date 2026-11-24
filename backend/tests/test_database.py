import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app.api import tasks as tasks_mod
from app.database import repo
from app.database import session as db
from app.main import app
from app.models.tables import Run
from app.security.proposals import store


def restart():
    """Simulate a backend restart: new engine on the same database file."""
    url = db._engine.url.render_as_string(hide_password=False)
    db.configure(url)


# ---- run history -----------------------------------------------------------------------------

def test_run_lifecycle():
    rid = repo.create_run("repo_x", "add a thing", None, None)
    assert repo.get_run(rid)["status"] == "running"
    repo.finish_run(rid, "done", "", "pid1", [{"agent": "planner", "status": "done", "data": {}}])
    run = repo.get_run(rid)
    assert run["status"] == "done" and run["proposal_id"] == "pid1" and run["duration_ms"] is not None
    assert run["events"][0]["agent"] == "planner" and run["created_at"].endswith("+00:00")
    assert repo.delete_run(rid) is True and repo.get_run(rid) is None and repo.delete_run(rid) is False


def test_issue_runs_get_a_readable_title_and_list_is_newest_first_and_filterable():
    a = repo.create_run("repo_a", "", "o/r", 7)
    b = repo.create_run("repo_b", "second", None, None)
    listing = repo.list_runs()
    assert [r["id"] for r in listing] == [b, a]
    assert next(r for r in listing if r["id"] == a)["title"] == "GitHub issue #7 in o/r"
    assert [r["id"] for r in repo.list_runs(repo_id="repo_a")] == [a]


def test_runs_left_running_become_interrupted_after_restart():
    rid = repo.create_run("repo_x", "task", None, None)
    done = repo.create_run("repo_x", "task2", None, None)
    repo.finish_run(done, "done", "", None, [])
    restart()
    assert repo.get_run(rid)["status"] == "interrupted" and repo.get_run(done)["status"] == "done"


def test_old_history_is_pruned_but_recent_is_kept():
    old, new = repo.create_run("r", "old", None, None), repo.create_run("r", "new", None, None)
    with db.session() as s:
        s.get(Run, old).created_at = datetime.now(timezone.utc) - timedelta(days=db.RETENTION_DAYS + 5)
    restart()
    assert repo.get_run(old) is None and repo.get_run(new) is not None


# ---- proposals survive restarts --------------------------------------------------------------

def test_proposal_and_undo_bytes_survive_a_restart():
    pid = store.save("repo_x", {"summary": "s", "changes": [{"path": "a.py", "old": "x", "new": "y"}]}, {"verdict": "approve"})
    nasty = b"\xff\xfe binary \x00 and CRLF\r\n"  # not valid UTF-8: must round-trip exactly
    store.add_applied(pid, 0, {"path": "/tmp/a.py", "sha": "abc", "original": nasty})
    store.add_applied(pid, 1, {"path": "/tmp/new.py", "sha": "def", "original": None})
    restart()
    rec = store.get(pid)
    assert rec["proposal"]["changes"][0]["old"] == "x" and rec["review"] == {"verdict": "approve"}
    assert [i for i, _ in rec["applied"]] == [0, 1]
    assert rec["applied"][0][1]["original"] == nasty and rec["applied"][1][1]["original"] is None
    store.remove_applied(pid, 0)
    assert [i for i, _ in store.get(pid)["applied"]] == [1]
    assert store.get("missing") is None


# ---- the streaming endpoint records runs ----------------------------------------------------

class FakeGraph:
    def __init__(self, final=None, exc=None):
        self.final, self.exc = final or {}, exc

    async def ainvoke(self, state, config):
        emit = config["configurable"]["emit"]
        await emit({"agent": "planner", "status": "done", "data": {"steps": ["a"]}, "provider": "fake"})
        if self.exc:
            raise self.exc
        return self.final


PROPOSAL = {"summary": "s", "changes": [{"path": "a.py", "action": "modify", "old": "x", "new": "y", "line": 1,
                                         "verified": True, "syntax": "ok", "diff": "d", "explanation": "e"}]}


async def stream_run(monkeypatch, graph):
    class Col:
        def count(self):
            return 3

    monkeypatch.setattr(tasks_mod, "get_collection", lambda _id: Col())
    monkeypatch.setattr(tasks_mod, "graph", graph)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post("/api/tasks/run", json={"task": "add a models endpoint", "repo_id": "repo_x"})
    import json
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


async def test_successful_run_is_recorded_with_events_and_proposal(monkeypatch):
    events = await stream_run(monkeypatch, FakeGraph({"proposal": PROPOSAL, "review": {"verdict": "approve"}}))
    finished = events[-1]["data"]
    run = repo.get_run(finished["run_id"])
    assert run["status"] == "done" and run["proposal_id"] == finished["proposal_id"]
    assert [e["agent"] for e in run["events"]] == ["planner"]  # agent events only, no system event
    assert store.get(run["proposal_id"])["proposal"]["changes"][0]["old"] == "x"


async def test_question_run_is_recorded_as_needs_input(monkeypatch):
    events = await stream_run(monkeypatch, FakeGraph({"question": "Which part?"}))
    run = repo.get_run(events[-1]["data"]["run_id"])
    assert run["status"] == "needs_input" and run["proposal_id"] is None


async def test_crash_is_recorded_and_reported(monkeypatch):
    events = await stream_run(monkeypatch, FakeGraph(exc=RuntimeError("boom")))
    assert events[-1]["data"]["ok"] is False
    run = repo.get_run(events[-1]["data"]["run_id"])
    assert run["status"] == "error" and "boom" in run["error"] and len(run["events"]) == 1


async def test_cancelled_run_is_recorded(monkeypatch):
    await stream_run(monkeypatch, FakeGraph(exc=asyncio.CancelledError()))
    runs = repo.list_runs()
    assert len(runs) == 1 and runs[0]["status"] == "cancelled"


# ---- the runs API ----------------------------------------------------------------------------

async def test_runs_api():
    rid = repo.create_run("repo_x", "hello", None, None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert [r["id"] for r in (await c.get("/api/runs")).json()] == [rid]
        assert (await c.get(f"/api/runs/{rid}")).json()["title"] == "hello"
        assert (await c.get("/api/runs?limit=0")).status_code == 422
        assert (await c.delete(f"/api/runs/{rid}")).status_code == 200
        assert (await c.get(f"/api/runs/{rid}")).status_code == 404
        assert (await c.delete(f"/api/runs/{rid}")).status_code == 404