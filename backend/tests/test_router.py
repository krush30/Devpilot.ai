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
