"""Path safety for anything that writes to disk. Every write goes through resolve_inside()."""
import re
from pathlib import Path, PurePosixPath

from app.rag.chunking import CODE_EXTS, SKIP_DIRS

SENSITIVE_NAMES = {".npmrc", ".pypirc", ".netrc", ".htpasswd", "id_rsa", "id_ed25519", "credentials"}


class PathRejected(ValueError):
    """The path is not safe to write. The message is user-safe."""


def resolve_inside(root: Path, rel: str) -> Path:
    if not rel or "\x00" in rel or ":" in rel:  # ':' also blocks Windows drives and alternate streams
        raise PathRejected("invalid path")
    p = PurePosixPath(rel.replace("\\", "/"))
    if p.is_absolute() or re.match(r"^[A-Za-z]:", rel) or ".." in p.parts:
        raise PathRejected("path must be relative and stay inside the repository")
    if any(part in SKIP_DIRS for part in p.parts):
        raise PathRejected("protected folder (.git, node_modules, virtual environments, ...)")
    name = p.name.lower()
    if name.startswith(".env") or name in SENSITIVE_NAMES:
        raise PathRejected("refusing to touch a file that usually holds secrets")
    if p.suffix.lower() not in CODE_EXTS:
        raise PathRejected(f"file type '{p.suffix or 'none'}' is not allowed")
    root_resolved = root.resolve()
    target = (root_resolved / Path(*p.parts)).resolve()  # resolves symlinks too
    if root_resolved not in target.parents:
        raise PathRejected("path escapes the repository folder")
    return target