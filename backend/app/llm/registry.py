"""Provider config + cached factory (LLD 02). Keys are read lazily (lambdas) so an
unset key doesn't error at import — only when that provider is actually used."""
from app.core.config import settings
from app.llm.openai_compat import OpenAICompatProvider

_CONFIG = {
    "groq": dict(
        base_url="https://api.groq.com/openai/v1",
        key=lambda: settings.GROQ_API_KEY,
        default_model="llama-3.3-70b-versatile",
    ),
    "gemini": dict(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        key=lambda: settings.GEMINI_API_KEY,
        default_model="gemini-2.0-flash",
    ),
    "ollama": dict(
        base_url=f"{settings.OLLAMA_BASE_URL}/v1",
        key=lambda: "ollama",
        default_model="llama3.2",
    ),
}
_cache: dict[str, OpenAICompatProvider] = {}


def get_provider(name: str | None = None) -> OpenAICompatProvider:
    name = (name or settings.DEFAULT_LLM_PROVIDER).lower()
    if name not in _CONFIG:
        raise ValueError(f"Unknown LLM provider: {name}")
    if name not in _cache:
        c = _CONFIG[name]
        _cache[name] = OpenAICompatProvider(
            name, c["base_url"], c["key"](), c["default_model"],
            settings.LLM_TIMEOUT, settings.LLM_MAX_RETRIES,
        )
    return _cache[name]
