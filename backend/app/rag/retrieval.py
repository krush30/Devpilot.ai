from app.rag.embeddings import embed
from app.rag.store import get_collection


def search(repo_id: str, query: str, k: int = 5) -> list[dict]:
    col = get_collection(repo_id)
    if col.count() == 0:
        return []
    res = col.query(query_embeddings=embed([query]), n_results=min(k, col.count()))
    hits = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        hits.append({**meta, "text": doc, "score": round(1 - dist, 3)})
    return hits


def format_context(hits: list[dict]) -> str:
    """Prefix every line with its real line number so the model can cite accurately."""
    blocks = []
    for h in hits:
        numbered = "\n".join(
            f"{h['start_line'] + i}: {line}" for i, line in enumerate(h["text"].splitlines())
        )
        blocks.append(f"File: {h['path']} (lines {h['start_line']}-{h['end_line']})\n{numbered}")
    return "\n\n".join(blocks)