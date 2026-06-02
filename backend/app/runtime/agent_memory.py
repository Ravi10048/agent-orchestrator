"""Memory helpers (LLD 05): short-term window + optional rolling summary.

Short-term memory = recent Message history, windowed by the caller. Summary memory =
one cheap LLM call to compress older turns; stored on Conversation.summary (channel chats).
"""
from app.llm import complete
from app.llm.types import LLMRequest


def window_history(history: list[dict], window: int | None) -> list[dict]:
    """Keep only the last `window` messages (0/None → keep all)."""
    if window and window > 0:
        return history[-window:]
    return history


async def summarize_history(messages: list[dict], prior: str = "", *, model: str | None = None) -> str:
    prompt = [
        {
            "role": "system",
            "content": "Summarise the conversation in <=120 words, keeping facts, "
            "decisions, and open tasks.",
        },
        {"role": "user", "content": prior + "\n" + _flatten(messages)},
    ]
    res = await complete(LLMRequest(messages=prompt, model=model, max_tokens=200, temperature=0.2))
    return res.text.strip()


def _flatten(messages: list[dict]) -> str:
    return "\n".join(f"{m.get('role', '')}: {m.get('content', '')}" for m in messages)
