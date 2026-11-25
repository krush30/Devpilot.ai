"""Throwaway copy of a repository for sandboxed testing. The real project is never touched."""
import os
import shutil
import tempfile
from pathlib import Path

from app.rag.chunking import SKIP_DIRS
from app.security.paths import SENSITIVE_NAMES

MAX_FILES = 5000
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024


class WorkspaceTooLarge(Exception):
    pass


def _skip_file(name: str) -> bool:
    low = name.lower()
    # Secrets never enter the sandbox, even though it has no network.
    return low.startswith(".env") or low in SENSITIVE_NAMES or low.endswith((".pem", ".key", ".pfx", ".db", ".sqlite"))


def make_workspace(root: Path) -> Path:
    root = root.resolve()
    files: list[tuple[Path, Path]] = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not Path(dirpath, d).is_symlink()]
        for name in filenames:
            src = Path(dirpath, name)
            if _skip_file(name) or src.is_symlink():
                continue
            size = src.stat().st_size
            if size > MAX_FILE_BYTES:
                continue
            total += size
            files.append((src, src.relative_to(root)))
            if len(files) > MAX_FILES or total > MAX_TOTAL_BYTES:
                raise WorkspaceTooLarge(
                    f"The project is too large to copy into the sandbox (limit {MAX_FILES} files / "
                    f"{MAX_TOTAL_BYTES // (1024 * 1024)} MB after skipping node_modules, virtual environments and secrets).")

    ws = Path(tempfile.mkdtemp(prefix="devpilot-ws-"))
    for src, rel in files:
        dest = ws / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    if os.name != "nt":  # the container runs as an unprivileged user and must be able to read everything
        for p in [ws, *ws.rglob("*")]:
            p.chmod(0o755 if p.is_dir() else 0o644)
    return ws


def cleanup(ws: Path) -> None:
    shutil.rmtree(ws, ignore_errors=True)


def list_python_files(ws: Path, limit: int = 60) -> list[str]:
    return sorted(p.relative_to(ws).as_posix() for p in ws.rglob("*.py"))[:limit]