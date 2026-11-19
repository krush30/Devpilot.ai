import pytest

from app.llm.router import AllProvidersFailed, LLMRouter


class Fake:
    def __init__(self, name, fail=False):
        self.name, self.fail = name, fail

    async def chat(self, messages, **kw):
        if self.fail:
            raise RuntimeError("rate limited")
        return f"hi from {self.name}"


def make(providers, order):
    r = LLMRouter.__new__(LLMRouter)
    r.providers = {p.name: p for p in providers}
    r.order, r.cooldown_until = order, {}
    return r


@pytest.mark.asyncio
async def test_falls_back_when_primary_fails():
    r = make([Fake("groq", fail=True), Fake("ollama")], ["groq", "ollama"])
    text, name = await r.chat([{"role": "user", "content": "x"}])
    assert name == "ollama" and "cooling_down" in r.health()["groq"]


@pytest.mark.asyncio
async def test_all_fail_raises():
    r = make([Fake("groq", fail=True)], ["groq"])
    with pytest.raises(AllProvidersFailed):
        await r.chat([])


# ---- latency / cache behaviour -------------------------------------------------------------

class Counting(Fake):
    def __init__(self, name, fail=False):
        super().__init__(name, fail)
        self.calls = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        return await super().chat(messages, **kw)


MSG = [{"role": "user", "content": "plan this"}]


@pytest.mark.asyncio
async def test_cache_is_off_by_default():
    p = Counting("groq")
    r = make([p], ["groq"])
    await r.chat(MSG)
    await r.chat(MSG)
    assert p.calls == 2


@pytest.mark.asyncio
async def test_cache_reuses_identical_primary_answers():
    p = Counting("groq")
    r = make([p], ["groq"])
    first = await r.chat(MSG, cache_ttl=60, temperature=0.2)
    second = await r.chat(MSG, cache_ttl=60, temperature=0.2)
    assert p.calls == 1 and first[1] == "groq" and second[1] == "groq (cached)"
    await r.chat([{"role": "user", "content": "different"}], cache_ttl=60, temperature=0.2)
    assert p.calls == 2  # different prompt is a miss


@pytest.mark.asyncio
async def test_fallback_answers_are_not_cached(monkeypatch):
    primary, backup = Counting("groq", fail=True), Counting("ollama")
    r = make([primary, backup], ["groq", "ollama"])
    await r.chat(MSG, cache_ttl=60)
    r.cooldown_until.clear()  # primary recovers
    primary.fail = False
    text, name = await r.chat(MSG, cache_ttl=60)
    assert name == "groq" and primary.calls == 2  # got a fresh primary answer, not the degraded one


@pytest.mark.asyncio
async def test_cache_entries_expire(monkeypatch):
    import time as time_mod

    p = Counting("groq")
    r = make([p], ["groq"])
    await r.chat(MSG, cache_ttl=60)
    real = time_mod.time()
    monkeypatch.setattr("app.llm.router.time.time", lambda: real + 61)
    await r.chat(MSG, cache_ttl=60)
    assert p.calls == 2


def test_clients_fail_fast_instead_of_sdk_defaults():
    from app.llm.providers import build_providers

    ollama = build_providers()["ollama"].client
    assert ollama.max_retries == 0 and ollama.timeout.read == 180 and ollama.timeout.connect == 5