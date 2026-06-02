from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Table, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.tool import Tool

# many-to-many: agent ↔ tool  (mirrors the tool-registry mapping pattern)
agent_tools = Table(
    "agent_tools",
    Base.metadata,
    Column("agent_id", ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("tool_id", ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True),
)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    role: Mapped[str] = mapped_column(String(120), default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(40), default="groq")  # groq|gemini|ollama
    model: Mapped[str] = mapped_column(String(80), default="llama-3.3-70b-versatile")

    # config dimensions (JSON) — each is a "configurable dimension per agent"
    channels: Mapped[list] = mapped_column(JSON, default=list)  # ENABLED channels only, e.g. ["telegram"]
    guardrails: Mapped[dict] = mapped_column(JSON, default=dict)  # {"max_steps":6,"max_tokens":1024,...}
    memory_config: Mapped[dict] = mapped_column(JSON, default=dict)  # {"type":"short_term","window":12,...}
    schedule: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"enabled":true,"cron":"*/5 * * * *"}

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # "skills" = mapped tools (the allow-list advertised to the LLM at runtime)
    tools: Mapped[list[Tool]] = relationship(secondary=agent_tools, lazy="selectin")
