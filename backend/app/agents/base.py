from langchain_core.runnables import RunnableConfig

from app.llm.router import router as llm
from app.llm.utils import strip_think

MAX_ATTEMPTS = 2


async def emit(config: RunnableConfig, agent: str, status: str, data: dict | None = None,
               provider: str | None = None) -> None:
    """Push a progress event to whoever is streaming this run (the SSE endpoint)."""
    fn = (config.get("configurable") or {}).get("emit")
    if fn:
        await fn({"agent": agent, "status": status, "data": data or {}, "provider": provider})


async def ask(messages: list[dict]) -> tuple[str, str]:
    """Call the model router. Returns (clean_text, provider_name)."""
    text, provider = await llm.chat(messages, temperature=0.2)
    return strip_think(text), provider