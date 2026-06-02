"""Public LLM API: `complete()` (with optional fallback), `get_provider()`, and the types."""
from app.core.config import settings
from app.llm.registry import get_provider
from app.llm.types import LLMRequest, LLMResult, ToolCall, Usage

__all__ = ["complete", "get_provider", "LLMRequest", "LLMResult", "ToolCall", "Usage"]


async def complete(req: LLMRequest, provider: str | None = None,
                   fallback: str | None = None) -> LLMResult:
    """Call the primary provider; on any error fall back to `fallback` (or the
    configured `LLM_FALLBACK_PROVIDER`) if set. The 3rd leg of timeout/retry/fallback."""
    fallback = fallback or settings.LLM_FALLBACK_PROVIDER
    try:
        return await get_provider(provider).complete(req)
    except Exception:
        if fallback and fallback != provider:
            return await get_provider(fallback).complete(req)
        raise
