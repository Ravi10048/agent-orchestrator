"""LLD 02 — LLM Gateway tests (mock AsyncOpenAI; no network/keys)."""
from types import SimpleNamespace

import pytest

import app.llm as llmpkg
from app.llm import registry
from app.llm.openai_compat import OpenAICompatProvider, _safe_json
from app.llm.pricing import estimate_cost
from app.llm.types import LLMRequest, LLMResult, Usage


def _provider() -> OpenAICompatProvider:
    return OpenAICompatProvider("groq", "http://x", "k", "llama-3.3-70b-versatile", 60, 2)


def _patch_create(p: OpenAICompatProvider, resp):
    async def fake_create(**kwargs):
        fake_create.kwargs = kwargs
        return resp

    p._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    return fake_create


def _resp(content, tool_calls=None, with_usage=True):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    choice = SimpleNamespace(message=msg, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15) if with_usage else None
    return SimpleNamespace(choices=[choice], usage=usage)


async def test_normalization_with_tools_and_usage():
    p = _provider()
    tc = SimpleNamespace(id="call_1", function=SimpleNamespace(name="web_fetch", arguments='{"url":"http://a"}'))
    _patch_create(p, _resp("hello", tool_calls=[tc]))
    res = await p.complete(LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert res.text == "hello"
    assert res.tool_calls[0].name == "web_fetch"
    assert res.tool_calls[0].arguments == {"url": "http://a"}  # parsed to dict
    assert res.usage.total_tokens == 15
    assert res.usage.est_cost_usd == estimate_cost("llama-3.3-70b-versatile", res.usage)
    assert res.provider == "groq"
    assert res.finish_reason == "stop"


async def test_usage_fallback_when_provider_omits_it():
    p = _provider()
    _patch_create(p, _resp("a" * 40, with_usage=False))
    res = await p.complete(LLMRequest(messages=[{"role": "user", "content": "hello world"}]))
    assert res.usage.prompt_tokens > 0
    assert res.usage.completion_tokens > 0
    assert res.usage.total_tokens == res.usage.prompt_tokens + res.usage.completion_tokens


def test_safe_json_handles_malformed():
    assert _safe_json('{"a":1}') == {"a": 1}
    assert _safe_json("") == {}
    assert _safe_json(None) == {}
    assert _safe_json("not json") == {"_raw": "not json"}


def test_estimate_cost_math_and_default_rate():
    u = Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert estimate_cost("llama-3.3-70b-versatile", u) == round(0.59 + 0.79, 6)
    assert estimate_cost("unknown-model", u) == round(0.50 + 1.50, 6)  # DEFAULT_RATE
    assert estimate_cost("llama3.2", Usage(prompt_tokens=1000, completion_tokens=1000)) == 0.0


def test_registry_unknown_default_and_cache():
    registry._cache.clear()
    with pytest.raises(ValueError):
        registry.get_provider("does-not-exist")
    p1 = registry.get_provider("groq")
    p2 = registry.get_provider("groq")
    assert p1 is p2  # cached
    assert registry.get_provider().name == settings_default()


def settings_default() -> str:
    from app.core.config import settings
    return settings.DEFAULT_LLM_PROVIDER.lower()


def test_usage_add():
    c = Usage(1, 2, 3, 0.001) + Usage(4, 5, 9, 0.002)
    assert (c.prompt_tokens, c.completion_tokens, c.total_tokens) == (5, 7, 12)
    assert c.est_cost_usd == round(0.003, 6)


async def test_complete_uses_fallback(monkeypatch):
    class _P:
        def __init__(self, name, ok):
            self.name, self.ok = name, ok

        async def complete(self, req):
            if not self.ok:
                raise RuntimeError("primary down")
            return LLMResult(text=f"from-{self.name}", provider=self.name)

    providers = {"primary": _P("primary", ok=False), "backup": _P("backup", ok=True)}
    monkeypatch.setattr(llmpkg, "get_provider", lambda name=None: providers[name])
    res = await llmpkg.complete(LLMRequest(messages=[]), provider="primary", fallback="backup")
    assert res.text == "from-backup"
