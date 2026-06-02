from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Tool(Base):
    __tablename__ = "tools"
    # tool names are unique PER TENANT (each tenant has its own tools, incl. its own copy of the
    # default builtins like web_fetch) — not globally unique.
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_tool_tenant_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(String(20), default="builtin")  # ToolType
    params_schema: Mapped[dict] = mapped_column(JSON, default=dict)  # JSON-Schema advertised to the LLM

    # builtin:
    builtin_key: Mapped[str | None] = mapped_column(String(80), nullable=True)  # registry key → python fn

    # http (user-defined REST tool):
    http_method: Mapped[str | None] = mapped_column(String(10), nullable=True)  # GET/POST/...
    endpoint: Mapped[str | None] = mapped_column(Text, nullable=True)  # URL template w/ {placeholders}
    headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    auth: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"type":"bearer","token_env":"X"}
    body_template: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
