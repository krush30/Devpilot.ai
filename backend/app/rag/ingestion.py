import shutil
import subprocess
import tempfile
from pathlib import Path

from app.rag.chunking import chunk_repo
from app.rag.embeddings import embed
from app.rag.store import get_collection, slugify

BATCH = 64


def clone_repo(git_url: str) -> Path:
    dest = Path(tempfile.mkdtemp(prefix="devpilot_"))
    subprocess.run(
        ["git", "clone", "--depth", "1", git_url, str(dest)],
        check=True, capture_output=True, timeout=300,
    )
    return dest


def index_repo(name: str, path: str | None = None, git_url: str | None = None) -> dict:
    cleanup = None
    if git_url:
        root = cleanup = clone_repo(git_url)
    elif path:
        root = Path(path).expanduser()
        if not root.is_dir():
            raise ValueError(f"Not a directory: {path}")
    else:
        raise ValueError("Provide either path or git_url")

    try:
        chunks = chunk_repo(root)
        if not chunks:  # don't create an empty, unusable index
            raise ValueError(
                "No indexable files found. DevPilot reads text and code files (.py, .ts, .md, .json, ...); "
                "files without an extension, such as a bare 'README', are skipped.")
        repo_id = slugify(name)
        local_root = str(root.resolve()) if path and not git_url else None  # temp clones can't be edited
        col = get_collection(repo_id, reset=True, root=local_root)  # re-index replaces old data
        for i in range(0, len(chunks), BATCH):
            batch = chunks[i:i + BATCH]
            col.add(
                ids=[f"{c.path}:{c.start_line}" for c in batch],
                documents=[c.text for c in batch],
                embeddings=embed([c.text for c in batch]),
                metadatas=[
                    {"path": c.path, "start_line": c.start_line, "end_line": c.end_line}
                    for c in batch
                ],
            )
        return {"repo_id": repo_id, "files": len({c.path for c in chunks}), "chunks": len(chunks)}
    finally:
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)