# LLD 02 — LLM Gateway

> Provider abstraction + token/cost meter. Depends on [LLD 01](01-data-model.md) (config). Used by the Agent ([LLD 05](05-agent.md)). Status: **for review**.

## Responsibility
A single, provider-agnostic way to call an LLM and get back a **normalized** result `{text, tool_calls, usage(+cost)}`. Hides the provider (Groq / Gemini / Ollama) behind one interface, handles **timeout + retry + optional fallback**, and is the **source of truth for token & cost** (the live-monitoring requirement). It does **not** build prompts or execute tools (that's the Agent/Tool layers) — it just does the call and normalizes.

## Key insight (keeps it lean)
Groq, Ollama, and Gemini all expose an **OpenAI-compatible** chat-completions endpoint (incl. tool calling). So **one** `AsyncOpenAI` client implementation, parameterized by `base_url` + `api_key` + `default_model`, covers all three. The abstraction (`LLMProvider`) still allows a fully custom provider later (e.g. native Anthropic).

## Files
```
backend/app/llm/
  __init__.py        # public: complete(), get_provider(), types
  types.py           # LLMRequest, LLMResult, ToolCall, Usage
  base.py            # LLMProvider (ABC)
  openai_compat.py   # OpenAICompatProvider — Groq/Gemini/Ollama via OpenAI wire format
  registry.py        # provider config + get_provider(name) factory (cached)
  pricing.py         # PRICING table + estimate_cost()
```
Config keys (in `core/config.py`, LLD 09): `DEFAULT_LLM_PROVIDER="groq"`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_BASE_URL="http://localhost:11434"`, `LLM_TIMEOUT=60`, `LLM_MAX_RETRIES=2`, `LLM_FALLBACK_PROVIDER=None`.

## Types — `llm/types.py`
```python
from dataclasses import dataclass, field

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict                 # parsed from JSON (safe-loaded)

@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    est_cost_usd: float = 0.0       # estimated at public rates (free tiers bill $0 — see pricing.py)

@dataclass
class LLMRequest:
    messages: list[dict]            # OpenAI chat format (system/user/assistant/tool)
    model: str | None = None        # None → provider default
    tools: list[dict] | None = None # OpenAI function-tool specs (built by the Tool layer, LLD 03)
    temperature: float = 0.7
    max_tokens: int = 1024
    response_format: dict | None = None   # e.g. {"type":"json_object"} for structured routing output

@dataclass
class LLMResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "stop"
    model: str = ""
    provider: str = ""
    latency_ms: int = 0
```

## Interface — `llm/base.py`
```python
from abc import ABC, abstractmethod
class LLMProvider(ABC):
    name: str
    @abstractmethod
    async def complete(self, req: LLMRequest) -> LLMResult: ...
    # Optional (deferred): async def stream(self, req) -> AsyncIterator[str]
```

## Implementation — `llm/openai_compat.py`
```python
import time, json
from openai import AsyncOpenAI, NOT_GIVEN
from app.llm.base import LLMProvider
from app.llm.types import LLMRequest, LLMResult, ToolCall, Usage
from app.llm.pricing import estimate_cost

class OpenAICompatProvider(LLMProvider):
    def __init__(self, name, base_url, api_key, default_model, timeout, max_retries):
        self.name = name
        self.default_model = default_model
        # SDK gives us timeout + retry-with-backoff for free (covers the platform LLM-call standard).
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key or "not-needed",
                                   timeout=timeout, max_retries=max_retries)

    async def complete(self, req: LLMRequest) -> LLMResult:
        model = req.model or self.default_model
        t0 = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=model, messages=req.messages,
            tools=req.tools or NOT_GIVEN,
            temperature=req.temperature, max_tokens=req.max_tokens,
            response_format=req.response_format or NOT_GIVEN,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        msg = resp.choices[0].message
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name,
                     arguments=_safe_json(tc.function.arguments))
            for tc in (msg.tool_calls or [])
        ]
        u = resp.usage
        usage = Usage(
            prompt_tokens=getattr(u, "prompt_tokens", 0),
            completion_tokens=getattr(u, "completion_tokens", 0),
            total_tokens=getattr(u, "total_tokens", 0),
        )
        usage.est_cost_usd = estimate_cost(model, usage)
        return LLMResult(text=msg.content or "", tool_calls=tool_calls, usage=usage,
                         finish_reason=resp.choices[0].finish_reason or "stop",
                         model=model, provider=self.name, latency_ms=latency_ms)

def _safe_json(s: str | None) -> dict:
    try: return json.loads(s) if s else {}
    except Exception: return {"_raw": s}
```
> If a provider omits `usage` (rare on the OpenAI-compat path), we fall back to a cheap length-based token estimate (helper in `pricing.py`) so monitoring never shows blanks.

## Registry + public API — `llm/registry.py` + `__init__.py`
```python
# registry.py
from app.core.config import settings
from app.llm.openai_compat import OpenAICompatProvider

_CONFIG = {
    "groq":   dict(base_url="https://api.groq.com/openai/v1",
                   key=lambda: settings.GROQ_API_KEY,   default_model="llama-3.3-70b-versatile"),
    "gemini": dict(base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                   key=lambda: settings.GEMINI_API_KEY, default_model="gemini-2.0-flash"),
    "ollama": dict(base_url=f"{settings.OLLAMA_BASE_URL}/v1",
                   key=lambda: "ollama",                default_model="llama3.2"),
}
_cache: dict[str, OpenAICompatProvider] = {}

def get_provider(name: str | None = None):
    name = (name or settings.DEFAULT_LLM_PROVIDER).lower()
    if name not in _CONFIG:
        raise ValueError(f"Unknown LLM provider: {name}")
    if name not in _cache:
        c = _CONFIG[name]
        _cache[name] = OpenAICompatProvider(name, c["base_url"], c["key"](),
                                            c["default_model"], settings.LLM_TIMEOUT, settings.LLM_MAX_RETRIES)
    return _cache[name]
```
```python
# __init__.py  — convenience with optional fallback (the 3rd leg of timeout/retry/fallback)
async def complete(req, provider=None, fallback=None) -> "LLMResult":
    fallback = fallback or settings.LLM_FALLBACK_PROVIDER
    try:
        return await get_provider(provider).complete(req)
    except Exception:
        if fallback and fallback != provider:
            return await get_provider(fallback).complete(req)
        raise
```

## Pricing / cost meter — `llm/pricing.py`
```python
# USD per 1M tokens (input, output) at public reference rates. Free tiers bill $0 in reality,
# but we surface an *estimated* cost at standard rates so the monitor shows realistic numbers
# (labeled "est."). This satisfies the token/cost-tracking requirement honestly.
PRICING = {
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant":    (0.05, 0.08),
    "gemini-2.0-flash":        (0.10, 0.40),
    "llama3.2":                (0.00, 0.00),   # local / Ollama
}
DEFAULT_RATE = (0.50, 1.50)

def estimate_cost(model: str, usage) -> float:
    inp, out = PRICING.get(model, DEFAULT_RATE)
    return round(usage.prompt_tokens/1e6*inp + usage.completion_tokens/1e6*out, 6)
```

## How the Agent (LLD 05) uses it
```python
from app.llm import complete
from app.llm.types import LLMRequest
res = await complete(
    LLMRequest(messages=history, tools=tool_specs, model=agent.model,
               temperature=0.4, max_tokens=agent.guardrails.get("max_tokens", 1024)),
    provider=agent.provider,
)
# res.text, res.tool_calls → execute tools (LLD 03); res.usage → emit token_usage event + add to Run/Conversation totals
```
- **Provider & model are per-agent** (`Agent.provider`, `Agent.model`) — a configurable dimension.
- The Agent/Executor emits a `TOKEN_USAGE` `RunEvent` from `res.usage` and increments `Run.total_tokens/est_cost` (and `Conversation.total_tokens` for channel chats). The gateway stays pure (returns usage; doesn't touch the DB/event bus).

## Tests (`backend/tests/test_llm_gateway.py`)
- **Normalization** (mock `AsyncOpenAI`): a response with `tool_calls` + `usage` → `LLMResult` has parsed `ToolCall.arguments` (dict), correct `Usage`, computed `est_cost_usd`.
- `_safe_json` handles malformed arguments without raising.
- `estimate_cost` math for a known model + the `DEFAULT_RATE` fallback.
- `get_provider("bad")` raises; `get_provider()` returns the default; instances are cached.
- (Live smoke test against Groq — skipped if `GROQ_API_KEY` unset.)

## Decisions / tradeoffs
- **One OpenAI-compatible client for all 3 providers** — Groq/Gemini/Ollama all speak the OpenAI wire format (incl. tools), so a single impl is DRY and well-understood. Tradeoff: bound to that format; a native-only provider (e.g. Anthropic Messages API) would get its own `LLMProvider` subclass — the ABC makes that clean.
- **SDK-native timeout + retry** (no `tenacity` dep) — `AsyncOpenAI(timeout=, max_retries=)` already does exponential backoff on 429/5xx. **Fallback** is a thin wrapper (try primary → fallback provider). Together = the platform's "timeout + retry + fallback" LLM standard, which is a strong live-session talking point.
- **Cost as an estimate at public rates**, clearly labeled "est." — honest for free tiers ($0 real) while still demoing meaningful token/cost numbers.
- **`complete()` (non-streaming) first**; the "responsive" feel comes from Groq's speed + streaming *events* to the monitor (LLD 06), not raw token streaming. A `stream()` method is left as an optional extension on the same interface.
- **Gateway is side-effect-free** (no DB, no event emission) — keeps it unit-testable and lets the Agent/Executor own persistence + monitoring.

---
*Next: [LLD 03 — Tool system](03-tools.md). Reply "go" to continue, or flag changes.*
