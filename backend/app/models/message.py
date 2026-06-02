from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Message(Base):
    """Covers all three message kinds — inter-agent, channel, and run history —
    via channel/from_agent/to_agent. Grouped by the string `conversation_id`
    (run id for workflow messages, conversation id for channel chats)."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    conversation_id: Mapped[str] = mapped_column(String(120), index=True, default="")
    from_agent: Mapped[str] = mapped_column(String(120), default="")  # agent name | "user" | "system"
    to_agent: Mapped[str] = mapped_column(String(120), default="")  # agent name | "user"
    channel: Mapped[str] = mapped_column(String(20), default="internal")  # ChannelType
    role: Mapped[str] = mapped_column(String(20), default="assistant")  # MessageRole
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tokens: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
