"""Docker runner tests using a fake `docker`: they verify the exact flags and the control flow.
(The real isolation is proven on your machine by POST /api/sandbox/selftest.)"""
import io
import subprocess
from pathlib import Path

import pytest

from app.sandbox import docker as d

WORK = Path("/tmp/ws")


def flag_values(args, flag):
    return [args[i + 1] for i, a in enumerate(args) if a == flag]


# ---- the arguments ---------------------------------------------------------------------------

def test_default_container_is_locked_down():
    args = d.build_run_args("n", WORK, ["python", "-m", "pytest"])
    assert flag_values(args, "--network") == ["none"]
    assert "--read-only" in args and "--cap-drop" in args and "ALL" in flag_values(args, "--cap-drop")
    assert "no-new-privileges" in flag_values(args, "--security-opt")
    assert flag_values(args, "--user") == ["65534:65534"]
    assert f"{WORK}:/work:ro" in flag_values(args, "-v")
    assert flag_values(args, "--memory") == ["512m"] and flag_values(args, "--pids-limit") == ["256"]
    assert flag_values(args, "--cpus") == ["1"]
    assert "--privileged" not in args and "--rm" in args
    assert args[-4:] == [d.IMAGE, "python", "-m", "pytest"][-4:] or args[args.index(d.IMAGE):] == [d.IMAGE, "python", "-m", "pytest"]


def test_no_host_environment_is_forwarded():
    args = d.build_run_args("n", WORK, ["true"])
    env = flag_values(args, "-e")
    assert sorted(env) == sorted(["HOME=/tmp", "PYTHONDONTWRITEBYTECODE=1", "PYTHONPATH=/work:/deps"])


def test_deps_are_mounted_read_only_for_tests_and_writable_only_for_install():
    test_args = d.build_run_args("n", WORK, ["true"], deps_volume_name="vol")
    assert "vol:/deps:ro" in flag_values(test_args, "-v") and flag_values(test_args, "--network") == ["none"]
    install = d.build_run_args("n", WORK, ["true"], network=True, deps_volume_name="vol", deps_writable=True,
                               run_as_nobody=False)
    assert "vol:/deps" in flag_values(install, "-v") and flag_values(install, "--network") == ["bridge"]
    assert "--user" not in install and f"{WORK}:/work:ro" in flag_values(install, "-v")  # project still read-only


def test_deps_volume_name_depends_on_requirements():
    assert d.deps_volume("a==1") != d.deps_volume("a==2") and d.deps_volume("a==1") == d.deps_volume("a==1")


# ---- running, timeouts, truncation -----------------------------------------------------------

class FakeProc:
    def __init__(self, data=b"", returncode=0, hang=False):
        self.stdout, self.returncode, self.hang, self.killed = io.BytesIO(data), returncode, hang, False

    def wait(self, timeout=None):
        if self.hang and not self.killed:
            raise subprocess.TimeoutExpired("docker", timeout)
        return self.returncode

    def kill(self):
        self.killed = True


@pytest.fixture
def fake(monkeypatch):
    calls = {"popen": [], "run": []}

    def popen(args, **kw):
        calls["popen"].append(args)
        return calls["proc"]

    def run(args, **kw):
        calls["run"].append(args)
        return subprocess.CompletedProcess(args, calls.get("run_rc", 0), "", "")

    monkeypatch.setattr(d.subprocess, "Popen", popen)
    monkeypatch.setattr(d.subprocess, "run", run)
    return calls


def test_successful_run_returns_output_and_exit_code(fake):
    fake["proc"] = FakeProc(b"3 passed\n", 0)
    res = d.run_in_container(WORK, ["pytest"])
    assert res.exit_code == 0 and "3 passed" in res.output and not res.timed_out
    assert fake["popen"][0][:2] == ["docker", "run"]


def test_timeout_kills_the_container_by_name(fake):
    fake["proc"] = FakeProc(b"partial", hang=True)
    res = d.run_in_container(WORK, ["sleep", "999"], timeout=1)
    assert res.timed_out and res.exit_code is None and fake["proc"].killed
    name = flag_values(fake["popen"][0], "--name")[0]
    assert ["docker", "kill", name] in fake["run"]


def test_huge_output_is_truncated(fake):
    fake["proc"] = FakeProc(b"x" * (d.MAX_OUTPUT + 5000), 0)
    res = d.run_in_container(WORK, ["yes"])
    assert len(res.output) == d.MAX_OUTPUT and res.truncated


# ---- availability, image, dependency install -------------------------------------------------

def test_docker_status_messages(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(d, "_docker", missing)
    ok, msg = d.docker_status()
    assert not ok and "not found" in msg

    monkeypatch.setattr(d, "_docker", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "daemon down"))
    assert "not running" in d.docker_status()[1]

    monkeypatch.setattr(d, "_docker", lambda *a, **k: subprocess.CompletedProcess(a, 0, "27.3.1\n", ""))
    assert d.docker_status() == (True, "Docker 27.3.1")

    def hang(*a, **k):
        raise subprocess.TimeoutExpired("docker", 10)

    monkeypatch.setattr(d, "_docker", hang)
    assert "Docker Desktop running" in d.docker_status()[1]


def test_image_is_built_only_when_missing(monkeypatch):
    seen = []

    def fake_docker(args, timeout=15, stdin=None):
        seen.append((args, stdin))
        return subprocess.CompletedProcess(args, 1 if args[0] == "image" else 0, "", "")

    monkeypatch.setattr(d, "_docker", fake_docker)
    d.ensure_image()
    assert seen[1][0][:3] == ["build", "-t", d.IMAGE] and "pytest" in seen[1][1]

    seen.clear()
    monkeypatch.setattr(d, "_docker", lambda args, timeout=15, stdin=None: subprocess.CompletedProcess(args, 0, "", ""))
    d.ensure_image()  # already there: no build, no error

    monkeypatch.setattr(d, "_docker", lambda args, timeout=15, stdin=None: subprocess.CompletedProcess(args, 1, "", "boom"))
    with pytest.raises(RuntimeError, match="Could not build"):
        d.ensure_image()


def test_install_deps_uses_cache_then_network_with_wheels_only(monkeypatch):
    calls = []

    def fake_run(workdir, command, **opts):
        calls.append((command, opts))
        return d.SandboxResult(exit_code=0 if command[0] == "test" else 0, output="ok")

    monkeypatch.setattr(d, "run_in_container", fake_run)
    ok, vol, log = d.install_deps(WORK, "fastapi==1")
    assert ok and "cached" in log and len(calls) == 1  # marker file found: nothing installed

    calls.clear()
    monkeypatch.setattr(d, "run_in_container",
                        lambda w, c, **o: (calls.append((c, o)), d.SandboxResult(1 if c[0] == "test" else 0, "done"))[1])
    ok, vol, log = d.install_deps(WORK, "fastapi==1")
    install_cmd, install_opts = calls[1]
    assert ok and install_opts["network"] is True and install_opts["deps_writable"] is True
    assert "--only-binary=:all:" in install_cmd[2] and "--target /deps" in install_cmd[2]