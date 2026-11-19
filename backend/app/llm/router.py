"""Model routing: try providers in order, with a cooldown for ones that fail (rate limits, outages)."""
import hashlib
import json
import logging
import time
from collections import OrderedDict

from app.core.config import settings
from app.llm.providers import Provider, build_providers

log = logging.getLogger("devpilot.llm")
COOLDOWN_SECONDS = 60
CACHE_MAX_ENTRIES = 128


class AllProvidersFailed(Exception):
    pass


class LLMRouter:
    cache: OrderedDict | None = None  # created on first use; opt-in per call via cache_ttl

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

    def _primary(self) -> str | None:
        return next((n for n in self.order if n in self.providers), None)

    def _cache_get(self, key: str) -> tuple[str, str] | None:
        item = (self.cache or {}).get(key)
        if item and item[2] > time.time():
            self.cache.move_to_end(key)
            return item[0], f"{item[1]} (cached)"
        if item:
            del self.cache[key]
        return None

    def _cache_put(self, key: str, text: str, provider: str, ttl: int) -> None:
        if self.cache is None:
            self.cache = OrderedDict()
        self.cache[key] = (text, provider, time.time() + ttl)
        while len(self.cache) > CACHE_MAX_ENTRIES:
            self.cache.popitem(last=False)

    async def chat(self, messages: list[dict], cache_ttl: int = 0, **kwargs) -> tuple[str, str]:
        """Returns (text, provider_name).

        cache_ttl > 0 reuses an identical earlier request for that many seconds. Only answers from
        the primary provider are cached, so a degraded fallback answer never sticks after recovery.
        """
        key = None
        if cache_ttl > 0:
            key = hashlib.sha256(json.dumps([messages, kwargs], sort_keys=True, default=str).encode()).hexdigest()
            if (hit := self._cache_get(key)):
                return hit
        errors = []
        for provider in self._available():
            started = time.perf_counter()
            try:
                text = await provider.chat(messages, **kwargs)
                log.info("provider=%s ok in %.0f ms", provider.name, (time.perf_counter() - started) * 1000)
                if key and provider.name == self._primary():
                    self._cache_put(key, text, provider.name, cache_ttl)
                return text, provider.name
            except Exception as e:  # rate limit, timeout, auth, etc.
                log.warning("provider %s failed after %.0f ms: %s", provider.name,
                            (time.perf_counter() - started) * 1000, e)
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