"""All three providers speak the OpenAI-compatible API, so one client class covers them."""
from dataclasses import dataclass

import httpx
from openai import AsyncOpenAI

from app.core.config import settings


# The OpenAI SDK defaults to a 10-minute timeout and 2 automatic retries. For a router with
# fallbacks that is the wrong trade: a hung provider would delay failover by minutes. So fail fast
# and let the router move to the next provider instead.
HOSTED_TIMEOUT = httpx.Timeout(connect=5, read=60, write=10, pool=5)
LOCAL_TIMEOUT = httpx.Timeout(connect=5, read=180, write=10, pool=5)  # local models load slowly on first use


def _client(api_key: str, base_url: str, local: bool = False) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0,
                       timeout=LOCAL_TIMEOUT if local else HOSTED_TIMEOUT)


@dataclass
class Provider:
    name: str
    model: str
    client: AsyncOpenAI

    async def chat(self, messages: list[dict], **kwargs) -> str:
        resp = await self.client.chat.completions.create(
            model=self.model, messages=messages, **kwargs
        )
        return resp.choices[0].message.content or ""


def build_providers() -> dict[str, Provider]:
    providers: dict[str, Provider] = {}
    if settings.groq_api_key:
        providers["groq"] = Provider(
            "groq", settings.groq_model,
            _client(settings.groq_api_key, "https://api.groq.com/openai/v1"),
        )
    if settings.openrouter_api_key:
        providers["openrouter"] = Provider(
            "openrouter", settings.openrouter_model,
            _client(settings.openrouter_api_key, "https://openrouter.ai/api/v1"),
        )
    providers["ollama"] = Provider(
        "ollama", settings.ollama_model,
        _client("ollama", settings.ollama_base_url, local=True),
    )
    return providers