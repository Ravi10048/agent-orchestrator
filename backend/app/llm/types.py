"""Normalized LLM I/O types — provider-agnostic (LLD 02)."""
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict  # parsed from JSON (safe-loaded)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    est_cost_usd: float = 0.0  # estimated at public rates (free tiers bill $0 — see pricing.py)

    def __add__(self, other: "Usage") -> "Usage":
        # Agent/Executor accumulate per-turn usage with `usage += res.usage` (LLD 05/06).
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            est_cost_usd=round(self.est_cost_usd + other.est_cost_usd, 6),
        )


@dataclass
class LLMRequest:
    messages: list[dict]  # OpenAI chat format (system/user/assistant/tool)
    model: str | None = None  # None → provider default
    tools: list[dict] | None = None  # OpenAI function-tool specs (built by the Tool layer, LLD 03)
    temperature: float = 0.7
    max_tokens: int = 1024
    response_format: dict | None = None  # e.g. {"type":"json_object"} for structured routing output


@dataclass
class LLMResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "stop"
    model: str = ""
    provider: str = ""
    latency_ms: int = 0
