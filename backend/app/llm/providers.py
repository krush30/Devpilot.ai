"""All three providers speak the OpenAI-compatible API, so one client class covers them."""
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.core.config import settings


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
            AsyncOpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1"),
        )
    if settings.openrouter_api_key:
        providers["openrouter"] = Provider(
            "openrouter", settings.openrouter_model,
            AsyncOpenAI(api_key=settings.openrouter_api_key, base_url="https://openrouter.ai/api/v1"),
        )
    providers["ollama"] = Provider(
        "ollama", settings.ollama_model,
        AsyncOpenAI(api_key="ollama", base_url=settings.ollama_base_url),
    )
    return providers
