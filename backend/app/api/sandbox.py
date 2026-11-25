"""Run generated tests for a proposal inside Docker. Nothing here touches the real project."""
import asyncio
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.tester import TEST_FILE, GenerationError, generate_tests
from app.database import sandbox_repo
from app.rag.store import get_root
from app.sandbox.docker import (SELFTEST_LABELS, SELFTEST_SCRIPT, docker_status, ensure_image, image_ready,
                                install_deps, run_in_container)
from app.sandbox.workspace import WorkspaceTooLarge, cleanup, make_workspace
from app.security.proposals import store
from app.tools.apply import apply_change

log = logging.getLogger("devpilot.sandbox")
sandbox = APIRouter(prefix="/api/sandbox")
_busy = asyncio.Lock()  # one container job at a time keeps memory and CPU predictable
TEST_TIMEOUT = 120


class TestRequest(BaseModel):
    __test__ = False  # not a pytest class
    change_indexes: list[int] | None = Field(default=None, max_length=10)
    install_deps: bool = False
    scope: Literal["generated", "all"] = "generated"


@sandbox.get("/status")
async def status() -> dict:
    ok, detail = await asyncio.to_thread(docker_status)
    return {"docker": ok, "detail": detail, "image_ready": await asyncio.to_thread(image_ready) if ok else False}


@sandbox.post("/selftest")
async def selftest() -> dict:
    """Prove the isolation is real on THIS machine: runs probes inside a real container."""
    ok, detail = await asyncio.to_thread(docker_status)
    if not ok:
        return {"available": False, "passed": False, "detail": detail, "checks": []}
    if _busy.locked():
        raise HTTPException(status_code=429, detail="The sandbox is busy. Try again in a moment.")
    async with _busy:
        probe = Path(tempfile.mkdtemp(prefix="devpilot-selftest-"))
        try:
            (probe / "hello.txt").write_text("hello")
            await asyncio.to_thread(ensure_image)
            res = await asyncio.to_thread(run_in_container, probe, ["python", "-c", SELFTEST_SCRIPT], timeout=60)
        except RuntimeError as e:
            return {"available": True, "passed": False, "detail": str(e), "checks": []}
        finally:
            shutil.rmtree(probe, ignore_errors=True)
    line = next((ln for ln in res.output.splitlines() if ln.startswith("RESULT ")), None)
    if line is None:
        return {"available": True, "passed": False, "checks": [],
                "detail": "The self-test did not complete: " + res.output[-300:]}
    found = json.loads(line[7:])
    checks = [{"name": SELFTEST_LABELS[k], "passed": bool(found.get(k))} for k in SELFTEST_LABELS]
    return {"available": True, "passed": all(c["passed"] for c in checks), "checks": checks, "detail": ""}


@sandbox.get("/results/{pid}")
def results(pid: str) -> dict | None:
    return sandbox_repo.latest(pid)


@sandbox.post("/test/{pid}")
async def run_tests(pid: str, body: TestRequest) -> dict:
    rec = await asyncio.to_thread(store.get, pid)
    if not rec:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    raw_root = await asyncio.to_thread(get_root, rec["repo_id"])
    if not raw_root or not Path(raw_root).is_dir():
        raise HTTPException(status_code=409, detail="This repository was not indexed from a local folder, "
                                                    "so there is nothing to copy into the sandbox.")
    ok, detail = await asyncio.to_thread(docker_status)
    if not ok:
        return {"status": "unavailable", "summary": detail, "steps": [], "tests": None, "output": ""}
    if _busy.locked():
        raise HTTPException(status_code=429, detail="The sandbox is busy with another run. Try again in a moment.")
    async with _busy:
        result = await _execute(rec, Path(raw_root), body)
    result["id"] = await asyncio.to_thread(sandbox_repo.save_result, pid, result["status"], result)
    return result


async def _execute(rec: dict, root: Path, body: TestRequest) -> dict:
    steps: list[dict] = []
    result: dict = {"status": "error", "summary": "", "steps": steps, "tests": None, "output": "",
                    "duration_ms": 0, "timed_out": False, "truncated": False}

    def step(name: str, ok: bool, detail: str = "") -> None:
        steps.append({"name": name, "ok": ok, "detail": detail})

    def fail(summary: str) -> dict:
        result["summary"] = summary
        return result

    ws = None
    try:
        ws = await asyncio.to_thread(make_workspace, root)
        step("Copied the project to a temporary folder (secrets, .git and node_modules left out)", True)

        changes = rec["proposal"]["changes"]
        wanted = body.change_indexes if body.change_indexes is not None else range(len(changes))
        applied = []
        for i in wanted:
            if not 0 <= i < len(changes):
                continue
            out = await asyncio.to_thread(apply_change, ws, changes[i])
            if out.status == "applied":
                applied.append(changes[i])
            else:
                step(f"Skipped {changes[i]['path']}", False, out.detail)
        if not applied:
            return fail("None of the changes could be applied to the sandbox copy.")
        step(f"Applied {len(applied)} change(s) to the copy. Your real files are untouched.", True)

        tests = await generate_tests(rec["proposal"]["summary"], applied, ws)
        (ws / TEST_FILE).write_text(tests["content"], encoding="utf-8")
        result["tests"] = {"filename": TEST_FILE, "content": tests["content"], "notes": tests["notes"],
                           "provider": tests["provider"]}
        step("Generated tests and passed the safety scan", True, tests["notes"])

        await asyncio.to_thread(ensure_image)
        step("Sandbox image ready", True)

        volume = None
        if body.install_deps:
            req = ws / "requirements.txt"
            if not req.is_file():
                step("Install requirements", False, "No requirements.txt in the project root.")
            else:
                ok, volume, log_text = await asyncio.to_thread(install_deps, ws, req.read_text(encoding="utf-8"))
                step("Installed requirements (wheels only, cached for next time)", ok, "" if ok else log_text)
                if not ok:
                    return fail("Installing the project's requirements failed. See the step details.")

        cmd = ["python", "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider", "--basetemp=/tmp/pytest",
               "-o", "asyncio_mode=auto", *([TEST_FILE] if body.scope == "generated" else [])]
        run = await asyncio.to_thread(run_in_container, ws, cmd, timeout=TEST_TIMEOUT, deps_volume_name=volume)
        result.update(output=run.output, duration_ms=run.duration_ms, timed_out=run.timed_out,
                      truncated=run.truncated)
        if run.timed_out:
            result["status"], result["summary"] = "timed_out", f"The tests did not finish within {TEST_TIMEOUT} seconds."
        elif run.exit_code == 0:
            result["status"], result["summary"] = "passed", "All generated tests passed."
        elif run.exit_code == 1:
            result["status"], result["summary"] = "failed", ("Some tests failed. Either the change or the "
                                                             "generated test is wrong, so read the output.")
        elif run.exit_code == 5:
            result["summary"] = "pytest found no tests to run."
        else:
            result["summary"] = f"pytest stopped with exit code {run.exit_code}. See the output."
        return result
    except WorkspaceTooLarge as e:
        return fail(str(e))
    except GenerationError as e:
        return fail(str(e))
    except RuntimeError as e:  # image build failed
        return fail(str(e))
    except Exception as e:
        log.exception("sandbox run crashed")
        return fail(f"Unexpected error ({type(e).__name__}). See the backend console.")
    finally:
        if ws is not None:
            await asyncio.to_thread(cleanup, ws)