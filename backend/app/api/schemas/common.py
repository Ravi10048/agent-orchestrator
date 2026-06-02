"""Shared DTO building blocks (LLD 09). Inputs forbid unknown fields (production-grade
request validation); Out models read from ORM attributes."""
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class StrictModel(BaseModel):
    """Base for request bodies — reject unknown fields with 422."""
    model_config = ConfigDict(extra="forbid")


class OutModel(BaseModel):
    """Base for responses — populate from ORM objects."""
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class GuardrailsDTO(StrictModel):
    max_steps: int = Field(default=6, ge=1, le=50)
    max_tokens: int = Field(default=1024, ge=1, le=32000)
    max_tokens_total: int = Field(default=8000, ge=1, le=200000)
    timeout_s: int = Field(default=60, ge=1, le=600)


class MemoryDTO(StrictModel):
    type: str = "short_term"
    window: int = Field(default=12, ge=0, le=200)
    summary: bool = False


class ScheduleDTO(StrictModel):
    enabled: bool = False
    kind: str | None = None  # "cron" | "interval"
    cron: str | None = None
    interval: dict | None = None
    timezone: str | None = None
    target: str = "agent"  # "agent" | "workflow"
    workflow_id: int | None = None
    prompt: str | None = None
    coalesce: bool | None = None
    max_instances: int | None = None
    misfire_grace_time: int | None = None


class AuthDTO(StrictModel):
    """Tool auth — env-var NAMES only, never raw secret values (extra='forbid' blocks `token`)."""
    type: str = "none"  # none | bearer | header
    token_env: str | None = None  # bearer: env var holding the token
    value_env: str | None = None  # header: env var holding the value
    name: str | None = None  # header: header name
