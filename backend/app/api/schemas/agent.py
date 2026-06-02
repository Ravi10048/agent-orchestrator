"""Agent DTOs (LLD 09)."""
from datetime import datetime

from pydantic import Field

from app.api.schemas.common import GuardrailsDTO, MemoryDTO, OutModel, ScheduleDTO, StrictModel
from app.api.schemas.tool import ToolOut


class AgentCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = ""
    system_prompt: str = ""
    provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"
    tool_ids: list[int] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    guardrails: GuardrailsDTO = Field(default_factory=GuardrailsDTO)
    memory_config: MemoryDTO = Field(default_factory=MemoryDTO)
    schedule: ScheduleDTO | None = None


class AgentUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = None
    system_prompt: str | None = None
    provider: str | None = None
    model: str | None = None
    channels: list[str] | None = None
    guardrails: GuardrailsDTO | None = None
    memory_config: MemoryDTO | None = None


class AgentOut(OutModel):
    id: int
    name: str
    role: str
    system_prompt: str
    provider: str
    model: str
    channels: list
    guardrails: dict
    memory_config: dict
    schedule: dict | None
    tools: list[ToolOut]
    created_at: datetime
    updated_at: datetime


class AgentToolsUpdate(StrictModel):
    tool_ids: list[int] = Field(default_factory=list)


class AgentTest(StrictModel):
    message: str = Field(min_length=1)


class AgentTestDraft(StrictModel):
    """Test the agent currently being edited WITHOUT saving it — so the editor's Test box reflects the
    live form (system prompt, model, tools, guardrails, memory) and works for not-yet-created agents."""
    message: str = Field(min_length=1)
    name: str = "Draft agent"
    role: str = ""
    system_prompt: str = ""
    provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"
    tool_ids: list[int] = Field(default_factory=list)
    guardrails: GuardrailsDTO = Field(default_factory=GuardrailsDTO)
    memory_config: MemoryDTO = Field(default_factory=MemoryDTO)


class AgentTestResult(OutModel):
    reply: str
    stopped_reason: str
    total_tokens: int
    est_cost_usd: float
