import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.agents import base
from app.agents.tester import TEST_FILE, GenerationError, check_test_code, generate_tests
from app.api import sandbox as api
from app.database import sandbox_repo
from app.llm.router import AllProvidersFailed
from app.main import app
from app.sandbox.docker import SandboxResult
from app.security.proposals import store

GOOD_TEST = "from app.main import f\n\n\ndef test_f():\n    assert f() == 2\n"


# ---- the safety scan on generated tests ------------------------------------------------------

@pytest.mark.parametrize("code,fragment", [
    ("import subprocess\ndef test_a():\n    pass\n", "subprocess"),
    ("from socket import socket\ndef test_a():\n    pass\n", "socket"),
    ("import os\ndef test_a():\n    os.system('ls')\n", "os.system"),
    ("def test_a():\n    eval('1')\n", "eval"),
    ("def test_a():\n    __import__('os')\n", "__import__"),
    ("def test_a(:\n", "syntax error"),
    ("def helper():\n    pass\n", "no test_ functions"),
])
def test_unsafe_or_broken_tests_are_rejected(code, fragment):
    assert fragment in check_test_code(code)


def test_ordinary_tests_pass_the_scan():
    assert check_test_code(GOOD_TEST) is None
    assert check_test_code("import os\nimport pytest\n\n\nasync def test_a(tmp_path):\n    assert os.path.exists(tmp_path)\n") is None


# ---- generating tests ------------------------------------------------------------------------

class FakeLLM:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    async def chat(self, messages, **kw):
        self.seen.append(messages)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r, "fake"


CHANGE = {"path": "app/main.py", "action": "modify", "explanation": "e", "diff": "d"}


async def test_generation_retries_after_an_unsafe_reply(monkeypatch, tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("def f():\n    return 2\n")
    bad = json.dumps({"notes": "n", "content": "import subprocess\ndef test_a():\n    pass\n"})
    good = json.dumps({"notes": "covers f", "content": GOOD_TEST})
    fake = FakeLLM([bad, good])
    monkeypatch.setattr(base, "llm", fake)
    out = await generate_tests("summary", [CHANGE], tmp_path)
    assert out["content"] == GOOD_TEST and out["notes"] == "covers f"
    assert "not allowed" in fake.seen[1][1]["content"]  # the rejection reason was fed back
    assert "return 2" in fake.seen[0][1]["content"]  # the model saw the post-change file


async def test_generation_failure_modes(monkeypatch, tmp_path):
    monkeypatch.setattr(base, "llm", FakeLLM([AllProvidersFailed("down")]))
    with pytest.raises(GenerationError, match="No model provider"):
        await generate_tests("s", [CHANGE], tmp_path)
    monkeypatch.setattr(base, "llm", FakeLLM(["nope", "still nope"]))
    with pytest.raises(GenerationError, match="Could not produce"):
        await generate_tests("s", [CHANGE], tmp_path)


# ---- the endpoint ----------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_bytes(b"def f():\n    return 1\n")
    (root / "requirements.txt").write_text("fastapi==1\n")
    (root / ".env").write_text("SECRET=1\n")
    return root


def make_proposal():
    return store.save("repo_x", {"summary": "make f return 2", "changes": [{
        "path": "app/main.py", "action": "modify", "old": "def f():\n    return 1", "new": "def f():\n    return 2",
        "syntax": "ok", "verified": True, "line": 1, "explanation": "e", "diff": "d", "syntax_error": ""}]}, None)


class Sandbox:
    """Records what the endpoint did, and lets each test choose the container's outcome."""
    def __init__(self, monkeypatch, project, outcome=None, docker_ok=True):
        self.runs, self.snapshot = [], {}
        self.outcome = outcome or SandboxResult(0, "1 passed in 0.01s", duration_ms=10)
        monkeypatch.setattr(api, "get_root", lambda repo_id: str(project))
        monkeypatch.setattr(api, "docker_status", lambda: (docker_ok, "Docker 27" if docker_ok else "Docker is not running"))
        monkeypatch.setattr(api, "ensure_image", lambda: None)
        monkeypatch.setattr(api, "image_ready", lambda: True)

        async def fake_generate(summary, changes, ws):
            return {"content": GOOD_TEST, "notes": "covers f", "provider": "fake"}

        monkeypatch.setattr(api, "generate_tests", fake_generate)

        def fake_run(workdir, command, **opts):
            self.runs.append((workdir, command, opts))
            self.snapshot = {"main": (workdir / "app/main.py").read_text(), "test": (workdir / TEST_FILE).read_text(),
                             "has_env": (workdir / ".env").exists()}
            return self.outcome

        monkeypatch.setattr(api, "run_in_container", fake_run)


def new_client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def post(pid, **body):  # every call uses a fresh client (a closed httpx client can't be reused)
    async with new_client() as c:
        return await c.post(f"/api/sandbox/test/{pid}", json=body)


async def test_passing_run_uses_a_copy_and_cleans_up(monkeypatch, project):
    sb = Sandbox(monkeypatch, project)
    pid = make_proposal()
    resp = await post(pid)
    data = resp.json()
    assert resp.status_code == 200 and data["status"] == "passed" and data["tests"]["notes"] == "covers f"
    workdir, command, opts = sb.runs[0]
    assert "return 2" in sb.snapshot["main"] and "def test_f" in sb.snapshot["test"]  # change + tests were in the copy
    assert sb.snapshot["has_env"] is False  # secrets never reach the sandbox
    assert (project / "app" / "main.py").read_bytes() == b"def f():\n    return 1\n"  # real project untouched
    assert not Path(workdir).exists()  # the copy was deleted
    assert command[-1] == TEST_FILE and opts.get("deps_volume_name") is None
    assert sandbox_repo.latest(pid)["status"] == "passed"


@pytest.mark.parametrize("outcome,status", [
    (SandboxResult(1, "1 failed"), "failed"),
    (SandboxResult(None, "", timed_out=True), "timed_out"),
    (SandboxResult(5, "no tests ran"), "error"),
    (SandboxResult(2, "interrupted"), "error"),
])
async def test_outcomes_map_to_statuses(monkeypatch, project, outcome, status):
    Sandbox(monkeypatch, project, outcome)
    assert (await post(make_proposal())).json()["status"] == status


async def test_scope_all_runs_the_whole_suite(monkeypatch, project):
    sb = Sandbox(monkeypatch, project)
    await post(make_proposal(), scope="all")
    assert TEST_FILE not in sb.runs[0][1]


async def test_install_deps_mounts_the_cached_volume(monkeypatch, project):
    sb = Sandbox(monkeypatch, project)
    monkeypatch.setattr(api, "install_deps", lambda ws, text: (True, "devpilot-deps-abc", "ok"))
    data = (await post(make_proposal(), install_deps=True)).json()
    assert data["status"] == "passed" and sb.runs[0][2]["deps_volume_name"] == "devpilot-deps-abc"
    monkeypatch.setattr(api, "install_deps", lambda ws, text: (False, "v", "pip exploded"))
    data = (await post(make_proposal(), install_deps=True)).json()
    assert data["status"] == "error" and "requirements" in data["summary"]


async def test_no_docker_is_reported_not_crashed(monkeypatch, project):
    sb = Sandbox(monkeypatch, project, docker_ok=False)
    pid = make_proposal()
    data = (await post(pid)).json()
    assert data["status"] == "unavailable" and "not running" in data["summary"] and not sb.runs
    assert sandbox_repo.latest(pid) is None  # nothing saved for a run that never happened


async def test_guard_rails(monkeypatch, project):
    Sandbox(monkeypatch, project)
    assert (await post("nope")).status_code == 404
    monkeypatch.setattr(api, "get_root", lambda repo_id: None)
    assert (await post(make_proposal())).status_code == 409
    monkeypatch.setattr(api, "get_root", lambda repo_id: str(project))
    await api._busy.acquire()
    try:
        assert (await post(make_proposal())).status_code == 429
    finally:
        api._busy.release()


async def test_unapplicable_changes_end_cleanly(monkeypatch, project):
    sb = Sandbox(monkeypatch, project)
    (project / "app" / "main.py").write_text("def f():\n    return 'changed since the proposal'\n")
    data = (await post(make_proposal())).json()
    assert data["status"] == "error" and "None of the changes" in data["summary"] and not sb.runs


async def test_generator_failure_is_reported(monkeypatch, project):
    Sandbox(monkeypatch, project)

    async def boom(*a, **k):
        raise GenerationError("Could not produce valid tests: nope")

    monkeypatch.setattr(api, "generate_tests", boom)
    data = (await post(make_proposal())).json()
    assert data["status"] == "error" and "valid tests" in data["summary"]


# ---- self-test endpoint ----------------------------------------------------------------------

async def test_selftest_reports_each_check(monkeypatch, project):
    Sandbox(monkeypatch, project)
    all_true = {k: True for k in ("network_blocked", "project_read_only", "root_fs_read_only", "not_root", "no_host_secrets")}
    monkeypatch.setattr(api, "run_in_container", lambda *a, **k: SandboxResult(0, "noise\nRESULT " + json.dumps(all_true)))
    async with new_client() as c:
        ok = (await c.post("/api/sandbox/selftest")).json()
    assert ok["passed"] and len(ok["checks"]) == 5

    leaky = {**all_true, "network_blocked": False}
    monkeypatch.setattr(api, "run_in_container", lambda *a, **k: SandboxResult(0, "RESULT " + json.dumps(leaky)))
    async with new_client() as c:
        bad = (await c.post("/api/sandbox/selftest")).json()
    assert not bad["passed"] and [c["passed"] for c in bad["checks"]].count(False) == 1

    monkeypatch.setattr(api, "run_in_container", lambda *a, **k: SandboxResult(1, "Traceback..."))
    async with new_client() as c:
        broken = (await c.post("/api/sandbox/selftest")).json()
    assert not broken["passed"] and "did not complete" in broken["detail"]


async def test_status_endpoint(monkeypatch, project):
    Sandbox(monkeypatch, project)
    async with new_client() as c:
        assert (await c.get("/api/sandbox/status")).json() == {"docker": True, "detail": "Docker 27", "image_ready": True}