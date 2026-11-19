"""ChromaDB persistence. One collection per indexed repository."""
import re

import chromadb

_client = chromadb.PersistentClient(path="./chroma_data")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-_")[:50] or "repo"
    return f"repo_{slug}"


def get_collection(repo_id: str, reset: bool = False, root: str | None = None):
    if reset:
        try:
            _client.delete_collection(repo_id)
        except Exception:
            pass
    meta = {"hnsw:space": "cosine", **({"root": root} if root else {})}
    return _client.get_or_create_collection(repo_id, metadata=meta)


def get_root(repo_id: str) -> str | None:
    """Local folder a repo was indexed from (None for GitHub-URL indexes or older indexes)."""
    try:
        return (_client.get_collection(repo_id).metadata or {}).get("root")
    except Exception:
        return None


def list_repos() -> list[dict]:
    out = []
    for c in _client.list_collections():
        name = c if isinstance(c, str) else c.name
        count = _client.get_collection(name).count()
        if count:  # hide empty indexes: they can't answer anything
            out.append({"repo_id": name, "chunks": count})
    return out