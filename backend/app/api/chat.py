import asyncio

from fastapi import APIRouter, HTTPException

from app.llm.router import AllProvidersFailed, router as llm
from app.rag.retrieval import format_context, search
from app.schemas.chat import ChatRequest, ChatResponse, Source

api = APIRouter(prefix="/api")

RAG_INSTRUCTIONS = (
    "\n\nAnswer using the repository excerpts below. Each excerpt line is prefixed with its "
    "real line number. Cite as path:line (for example app/main.py:12), using only those numbers. "
    "Do not use any other citation format. If the excerpts don't contain the answer, say so "
    "instead of guessing.\n\n"
)


@api.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    system, sources = req.system, []
    if req.repo_id:
        # Embedding + vector search are blocking, so run them off the event loop.
        hits = await asyncio.to_thread(search, req.repo_id, req.message, 5)
        if hits:
            system += RAG_INSTRUCTIONS + format_context(hits)
            sources = [Source(**{k: h[k] for k in ("path", "start_line", "end_line")}) for h in hits]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": req.message}]
    try:
        text, provider = await llm.chat(messages)
    except AllProvidersFailed as e:
        raise HTTPException(status_code=503, detail=str(e))
    return ChatResponse(reply=text, provider=provider, sources=sources)


@api.get("/llm/health")
async def llm_health() -> dict:
    return llm.health()