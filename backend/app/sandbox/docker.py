"""Run commands in a locked-down Docker container.

Every container gets: no network (except the explicit dependency-install step), a read-only
root filesystem, the project mounted read-only, no Linux capabilities, an unprivileged user,
memory / CPU / process limits, a hard timeout, and none of the host's environment variables.
"""
import hashlib
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

IMAGE = "devpilot-sandbox:1"
DOCKERFILE = """FROM python:3.12-slim
RUN pip install --no-cache-dir "pytest>=8.3,<10" "pytest-asyncio>=0.24"
"""
MAX_OUTPUT = 100_000
LIMITS = ["--memory", "512m", "--memory-swap", "512m", "--cpus", "1", "--pids-limit", "256"]
HARDENING = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges"]


@dataclass
class SandboxResult:
    exit_code: int | None
    output: str
    timed_out: bool = False
    truncated: bool = False
    duration_ms: int = 0


def _docker(args: list[str], timeout: int = 15, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, input=stdin)


def docker_status() -> tuple[bool, str]:
    """(available, detail). Never raises."""
    try:
        r = _docker(["version", "--format", "{{.Server.Version}}"], timeout=10)
    except FileNotFoundError:
        return False, "Docker was not found. Install Docker Desktop and make sure `docker` works in a terminal."
    except subprocess.TimeoutExpired:
        return False, "Docker did not respond. Is Docker Desktop running?"
    if r.returncode != 0:
        return False, "Docker is installed but not running. Start Docker Desktop and try again."
    return True, f"Docker {r.stdout.strip()}"


def image_ready() -> bool:
    try:
        return _docker(["image", "inspect", IMAGE]).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def ensure_image() -> None:
    """Build the sandbox image once (needs network for the pip install inside the Dockerfile)."""
    if image_ready():
        return
    r = _docker(["build", "-t", IMAGE, "-"], timeout=900, stdin=DOCKERFILE)
    if r.returncode != 0:
        raise RuntimeError("Could not build the sandbox image: " + (r.stderr or r.stdout)[-500:])


def deps_volume(requirements_text: str) -> str:
    return "devpilot-deps-" + hashlib.sha256(requirements_text.encode()).hexdigest()[:12]


def build_run_args(name: str, workdir: Path, command: list[str], *, network: bool = False, readonly_root: bool = True,
                   deps_volume_name: str | None = None, deps_writable: bool = False, run_as_nobody: bool = True) -> list[str]:
    args = ["run", "--rm", "--name", name, *LIMITS, *HARDENING]
    args += ["--network", "bridge" if network else "none"]
    if readonly_root:
        args += ["--read-only", "--tmpfs", "/tmp:rw,size=64m"]
    if run_as_nobody:
        args += ["--user", "65534:65534"]
    args += ["-v", f"{workdir}:/work:ro", "-w", "/work"]
    if deps_volume_name:
        args += ["-v", f"{deps_volume_name}:/deps" + ("" if deps_writable else ":ro")]
    args += ["-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTHONPATH=/work:/deps"]
    return [*args, IMAGE, *command]


def run_in_container(workdir: Path, command: list[str], *, timeout: int = 120, **opts) -> SandboxResult:
    name = f"devpilot-sbx-{uuid.uuid4().hex[:8]}"
    args = ["docker", *build_run_args(name, workdir, command, **opts)]
    started = time.monotonic()
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    chunks: list[bytes] = []
    state = {"total": 0, "truncated": False}

    def drain() -> None:  # keep reading even past the cap so the container never blocks on a full pipe
        for chunk in iter(lambda: proc.stdout.read(4096), b""):
            if state["total"] < MAX_OUTPUT:
                chunks.append(chunk[: MAX_OUTPUT - state["total"]])
            else:
                state["truncated"] = True
            state["total"] += len(chunk)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        subprocess.run(["docker", "kill", name], capture_output=True, timeout=15)  # stop the container itself
        proc.kill()
        proc.wait()
    reader.join(timeout=5)
    return SandboxResult(
        exit_code=None if timed_out else proc.returncode,
        output=b"".join(chunks).decode("utf-8", "replace"),
        timed_out=timed_out, truncated=state["truncated"],
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def install_deps(workdir: Path, requirements_text: str, timeout: int = 900) -> tuple[bool, str, str]:
    """Download wheels into a named volume (the ONLY step with network). Returns (ok, volume, log)."""
    volume = deps_volume(requirements_text)
    check = run_in_container(workdir, ["test", "-f", "/deps/.devpilot-ok"], timeout=30,
                             deps_volume_name=volume)
    if check.exit_code == 0:
        return True, volume, "Dependencies already installed (cached)."
    # Wheels only: no setup.py of any package runs. Root inside the container so it can write the volume.
    cmd = ["sh", "-c", "pip install --no-cache-dir --only-binary=:all: --target /deps -r /work/requirements.txt "
                       "&& touch /deps/.devpilot-ok"]
    res = run_in_container(workdir, cmd, timeout=timeout, network=True, deps_volume_name=volume,
                           deps_writable=True, run_as_nobody=False)
    return res.exit_code == 0, volume, res.output[-2000:]


SELFTEST_SCRIPT = r'''
import json, os, socket
r = {}
try:
    socket.create_connection(("1.1.1.1", 53), timeout=3).close(); r["network_blocked"] = False
except OSError:
    r["network_blocked"] = True
for key, path in (("project_read_only", "/work/probe.txt"), ("root_fs_read_only", "/probe.txt")):
    try:
        open(path, "w").write("x"); r[key] = False
    except OSError:
        r[key] = True
r["not_root"] = os.getuid() != 0
r["no_host_secrets"] = not any(w in k.upper() for k in os.environ for w in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
print("RESULT " + json.dumps(r))
'''

SELFTEST_LABELS = {
    "network_blocked": "Network is blocked inside the container",
    "project_read_only": "Your project copy is mounted read-only",
    "root_fs_read_only": "The container's own filesystem is read-only",
    "not_root": "Code runs as an unprivileged user, not root",
    "no_host_secrets": "No API keys or tokens from your machine are visible",
}