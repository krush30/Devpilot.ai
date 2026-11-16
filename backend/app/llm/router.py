"""Model routing: try providers in order, with a cooldown for ones that fail (rate limits, outages)."""
import logging
import time

from app.core.config import settings
from app.llm.providers import Provider, build_providers

log = logging.getLogger("devpilot.llm")
COOLDOWN_SECONDS = 60


class AllProvidersFailed(Exception):
    pass


class LLMRouter:
    def __init__(self) -> None:
        self.providers = build_providers()
        self.order = [p.strip() for p in settings.provider_order.split(",") if p.strip()]
        self.cooldown_until: dict[str, float] = {}

    def _available(self) -> list[Provider]:
        now = time.time()
        return [
            self.providers[n] for n in self.order
            if n in self.providers and self.cooldown_until.get(n, 0) <= now
        ]

    async def chat(self, messages: list[dict], **kwargs) -> tuple[str, str]:
        """Returns (text, provider_name)."""
        errors = []
        for provider in self._available():
            try:
                return await provider.chat(messages, **kwargs), provider.name
            except Exception as e:  # rate limit, timeout, auth, etc.
                log.warning("provider %s failed: %s", provider.name, e)
                self.cooldown_until[provider.name] = time.time() + COOLDOWN_SECONDS
                errors.append(f"{provider.name}: {e}")
        raise AllProvidersFailed("; ".join(errors) or "no providers configured")

    def health(self) -> dict:
        now = time.time()
        return {
            n: {"configured": True, "cooling_down": self.cooldown_until.get(n, 0) > now}
            for n in self.providers
        }


router = LLMRouter()
