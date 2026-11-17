from app.rag.store import get_collection


def list_files(repo_id: str, limit: int = 80) -> list[str]:
    """Unique file paths in an indexed repo, so the planner can see what actually exists."""
    metas = get_collection(repo_id).get(include=["metadatas"])["metadatas"] or []
    return sorted({m["path"] for m in metas})[:limit]