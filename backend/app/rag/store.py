"""ChromaDB persistence. One collection per indexed repository."""
import re

import chromadb

_client = chromadb.PersistentClient(path="./chroma_data")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-_")[:50] or "repo"
    return f"repo_{slug}"


def get_collection(repo_id: str, reset: bool = False):
    if reset:
        try:
            _client.delete_collection(repo_id)
        except Exception:
            pass
    return _client.get_or_create_collection(repo_id, metadata={"hnsw:space": "cosine"})


def list_repos() -> list[dict]:
    out = []
    for c in _client.list_collections():
        name = c if isinstance(c, str) else c.name
        out.append({"repo_id": name, "chunks": _client.get_collection(name).count()})
    return out
