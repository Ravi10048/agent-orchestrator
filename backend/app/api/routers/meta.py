"""Meta router (LLD 09) — health (drives the frontend onboarding banner) + model list."""
from fastapi import APIRouter, Query

from app.core.config import settings

router = APIRouter(tags=["meta"])

# selectable models per provider (surfaced in the agent editor)
_MODELS = {
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
    "gemini": ["gemini-2.0-flash"],
    "ollama": ["llama3.2"],
}
_PROVIDER_KEY = {
    "groq": lambda: bool(settings.GROQ_API_KEY),
    "gemini": lambda: bool(settings.GEMINI_API_KEY),
    "ollama": lambda: True,  # local, no key
}


@router.get("/health")
def health():
    provider = settings.DEFAULT_LLM_PROVIDER.lower()
    return {
        "ok": True,
        "llm_provider": provider,
        "llm_key_present": _PROVIDER_KEY.get(provider, lambda: False)(),
        "telegram_present": bool(settings.TELEGRAM_BOT_TOKEN),
        "db": "ok",
    }


@router.get("/models")
def models(provider: str | None = Query(None)):
    p = (provider or settings.DEFAULT_LLM_PROVIDER).lower()
    return {"provider": p, "models": _MODELS.get(p, [])}
