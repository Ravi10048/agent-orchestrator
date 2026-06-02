"""Run / Message / Event DTOs (LLD 09)."""
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.api.schemas.common import OutModel, StrictModel


class RunCreate(StrictModel):
    workflow_id: int
    input: dict = Field(default_factory=dict)
    trigger: Literal["manual", "schedule", "channel"] = "manual"  # constrained → no 422 surprises


class RunOut(OutModel):
    id: int
    workflow_id: int
    status: str
    trigger: str
    input: dict
    output: dict | None
    total_tokens: int
    est_cost: float
    error: str | None
    started_at: datetime
    ended_at: datetime | None


class RunDetailOut(RunOut):
    pass  # same fields; messages/events fetched via dedicated endpoints


class MessageOut(OutModel):
    id: int
    run_id: int | None
    conversation_id: str
    from_agent: str
    to_agent: str
    channel: str
    role: str
    content: str
    tool_calls: list | None
    tokens: int
    created_at: datetime


class EventEnvelopeOut(OutModel):
    run_id: int
    seq: int
    type: str
    ts: str | None
    event_id: int | None
    payload: dict[str, Any] = Field(default_factory=dict)
