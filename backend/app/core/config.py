"""Application settings — the single place for every env key (LLD 01–08 reference it;
fully enumerated in LLD 09 §config). Implemented in full here so later modules can import
their keys without re-editing this file."""
from __future__ import annotations

from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ── App ──────────────────────────────────────────────────────────
    APP_NAME: str = "Agent Orchestrator"
    ENV: str = "dev"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    # NoDecode: don't JSON-parse the raw env value (so CORS_ORIGINS=* or a CSV is accepted);
    # the validator below splits it. Without this, pydantic-settings tries json.loads("*") → crash.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # ── Persistence ──────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite:///./data/app.db"

    # ── LLM (LLD 02) ─────────────────────────────────────────────────
    DEFAULT_LLM_PROVIDER: str = "groq"
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    LLM_TIMEOUT: int = 60
    LLM_MAX_RETRIES: int = 2
    LLM_FALLBACK_PROVIDER: str | None = None

    # ── Channel / Telegram (LLD 07) ──────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_POLL_TIMEOUT: int = 30

    # ── Demo mock API (IKEA tenant tools) ────────────────────────────
    # Locally the mock runs as a SEPARATE service on :8001 (`make mock`), so the IKEA HTTP tools hit a
    # genuinely external API. For a single-service cloud deploy (e.g. Render), set MOUNT_MOCK_API=true to
    # serve the mock in-process at /api/mock, and point MOCK_API_BASE at it (…/api/mock).
    MOUNT_MOCK_API: bool = False
    MOCK_API_BASE: str = "http://localhost:8001/mock"

    # ── Scheduler (LLD 08) ───────────────────────────────────────────
    SCHEDULER_TIMEZONE: str = "UTC"
    SCHEDULER_MISFIRE_GRACE: int = 3600

    # ── Executor / runtime (LLD 06) ──────────────────────────────────
    MAX_RUN_STEPS: int = 50
    DEFAULT_MAX_VISITS: int = 8
    RUN_TIMEOUT_S: int = 300
    WS_BACKFILL_LIMIT: int = 500

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_csv(cls, v):
        # allow a plain comma-separated string in .env (not just JSON)
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


settings = Settings()
