"""One OpenAI-compatible client covers Groq / Gemini / Ollama (all speak the OpenAI
wire format, incl. tool-calling). SDK-native timeout + retry (exponential backoff on
429/5xx) gives us the platform's timeout+retry LLM standard for free (LLD 02)."""
import json
import time

from openai import NOT_GIVEN, AsyncOpenAI

from app.llm.base import LLMProvider
from app.llm.pricing import approx_tokens, estimate_cost
from app.llm.types import LLMRequest, LLMResult, ToolCall, Usage


class OpenAICompatProvider(LLMProvider):
    def __init__(self, name, base_url, api_key, default_model, timeout, max_retries):
        self.name = name
        self.default_model = default_model
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key or "not-needed",
            timeout=timeout,
            max_retries=max_retries,
        )

    async def complete(self, req: LLMRequest) -> LLMResult:
        model = req.model or self.default_model
        t0 = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=model,
            messages=req.messages,
            tools=req.tools or NOT_GIVEN,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            response_format=req.response_format or NOT_GIVEN,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        msg = resp.choices[0].message
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=_safe_json(tc.function.arguments))
            for tc in (msg.tool_calls or [])
        ]
        usage = _usage_from(resp, req, msg, model)
        return LLMResult(
            text=msg.content or "",
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=resp.choices[0].finish_reason or "stop",
            model=model,
            provider=self.name,
            latency_ms=latency_ms,
        )


def _safe_json(s: str | None) -> dict:
    try:
        return json.loads(s) if s else {}
    except Exception:
        return {"_raw": s}


def _usage_from(resp, req: LLMRequest, msg, model: str) -> Usage:
    u = getattr(resp, "usage", None)
    if u is not None:
        usage = Usage(
            prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(u, "completion_tokens", 0) or 0,
            total_tokens=getattr(u, "total_tokens", 0) or 0,
        )
    else:  # provider omitted usage → cheap length-based estimate so monitoring isn't blank
        pt = sum(approx_tokens(str(m.get("content", ""))) for m in req.messages)
        ct = approx_tokens(msg.content or "")
        usage = Usage(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct)
    if not usage.total_tokens:
        usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
    usage.est_cost_usd = estimate_cost(model, usage)
    return usage
