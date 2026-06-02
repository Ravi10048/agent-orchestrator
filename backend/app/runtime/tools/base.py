"""Tool core types (LLD 03)."""
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    ok: bool
    output: Any = None  # JSON-serialisable
    error: str | None = None
    latency_ms: int = 0


@dataclass
class ToolContext:
    """What channel-/run-aware tools need."""
    run_id: int | None = None
    conversation_id: str | None = None
    chat_id: str | None = None  # e.g. Telegram chat → used by send_telegram
    agent_name: str = ""
