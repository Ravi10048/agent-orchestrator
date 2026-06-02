"""Token cost meter (LLD 02).

USD per 1M tokens (input, output) at public reference rates. Free tiers bill $0 in
reality, but we surface an *estimated* cost at standard rates so the monitor shows
realistic numbers (labeled "est."). Honest for free tiers while still meaningful.
"""
from app.llm.types import Usage

PRICING = {
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "gemini-2.0-flash": (0.10, 0.40),
    "llama3.2": (0.00, 0.00),  # local / Ollama
}
DEFAULT_RATE = (0.50, 1.50)


def estimate_cost(model: str, usage: Usage) -> float:
    inp, out = PRICING.get(model, DEFAULT_RATE)
    return round(usage.prompt_tokens / 1e6 * inp + usage.completion_tokens / 1e6 * out, 6)


def approx_tokens(text: str) -> int:
    """~4 chars/token heuristic. Only used when a provider omits `usage` so the
    monitor never shows blank token counts."""
    return max(1, len(text or "") // 4)
