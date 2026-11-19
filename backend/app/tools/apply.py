"""Apply approved changes to disk, and undo them.

Only called by the approval endpoint, never by an agent. Every write is atomic, preserves the
file's line endings, and records what it needs to be undone.
"""
import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.security.paths import PathRejected, resolve_inside

MAX_BYTES = 500_000


@dataclass
class Outcome:
    status: str  # applied | would_apply | undone | skipped
    detail: str = ""
    undo: dict | None = None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _skip(detail: str) -> Outcome:
    return Outcome("skipped", detail)


def _atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".devpilot-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if target.exists():
            shutil.copymode(target, tmp)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def apply_change(root: Path, change: dict, dry_run: bool = False) -> Outcome:
    if change.get("syntax") == "error":
        return _skip("the proposed Python code has a syntax error")
    try:
        target = resolve_inside(root, change["path"])
    except PathRejected as e:
        return _skip(str(e))
    if change["action"] == "create":
        return _create(target, change, dry_run)
    return _modify(target, change, dry_run)


def _modify(target: Path, change: dict, dry_run: bool) -> Outcome:
    if not target.is_file():
        return _skip("file does not exist")
    raw = target.read_bytes()
    if len(raw) > MAX_BYTES:
        return _skip("file is too large to edit safely")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _skip("not a UTF-8 text file")

    nl = "\r\n" if "\r\n" in text else "\n"  # keep the file's own line endings (matters on Windows)
    lines = text.splitlines()
    old = [line.rstrip() for line in change["old"].strip("\n").splitlines()]
    if not old:
        return _skip("the change has no original code to replace")
    n = len(old)
    matches = [i for i in range(len(lines) - n + 1)
               if all(lines[i + j].rstrip() == old[j] for j in range(n))]
    if not matches:
        return _skip("original code not found in the file (has it changed since the proposal?)")
    if len(matches) > 1:
        return _skip(f"original code appears {len(matches)} times, so the position is ambiguous")

    i = matches[0]
    new = change["new"].strip("\n").splitlines()
    out = nl.join(lines[:i] + new + lines[i + n:]) + (nl if text.endswith("\n") else "")
    data = out.encode("utf-8")
    where = f"lines {i + 1}-{i + n}"
    if dry_run:
        return Outcome("would_apply", where)
    _atomic_write(target, data)
    return Outcome("applied", where, {"path": str(target), "original": raw, "sha": _sha(data)})


def _create(target: Path, change: dict, dry_run: bool) -> Outcome:
    if target.exists():
        return _skip("file already exists; refusing to overwrite")
    content = change["new"]
    if not content.strip():
        return _skip("the new file would be empty")
    data = (content.rstrip("\n") + "\n").encode("utf-8")
    if len(data) > MAX_BYTES:
        return _skip("new file is too large")
    if dry_run:
        return Outcome("would_apply", "new file")
    _atomic_write(target, data)
    return Outcome("applied", "new file created", {"path": str(target), "original": None, "sha": _sha(data)})


def undo_change(undo: dict) -> Outcome:
    target = Path(undo["path"])
    if not target.exists():
        return _skip("file no longer exists")
    if _sha(target.read_bytes()) != undo["sha"]:
        return _skip("file was edited after it was applied; not touching it")
    if undo["original"] is None:
        target.unlink()
        return Outcome("undone", "removed the file that was created")
    _atomic_write(target, undo["original"])
    return Outcome("undone", "restored the original content")