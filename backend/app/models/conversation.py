from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Conversation(Base):
    """A channel chat session — created when a new chat_id first messages the bot.
    Routes that chat to `agent_id` and holds the per-chat summary memory.
    Workflow runs do not need a Conversation (they use Run).

    Optional per-turn routing (the conversational stretch): when `workflow_id` is set, every
    turn is routed through that workflow's router (the supervisor) — the router picks the best
    specialist and that specialist answers. `curr_agent` is the name of the specialist currently
    holding the chat (supervisor-style sticky state), so the next turn stays with them unless the topic
    changes. When `workflow_id` is NULL the conversation is a plain 1:1 chat with `agent_id`."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(20), default="telegram")  # ChannelType
    external_id: Mapped[str] = mapped_column(String(120), index=True)  # e.g. Telegram chat_id
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)  # entry/router agent
    # per-turn routing: the workflow whose router routes this chat (NULL = plain 1:1 with agent_id).
    # ondelete=SET NULL documents intent for Postgres; SQLite FK enforcement is OFF (see core/db.py),
    # so the runtime guard in conversation_router (workflow missing OR no router -> 1:1) is what
    # actually makes a deleted workflow degrade gracefully.
    workflow_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True)
    curr_agent: Mapped[str | None] = mapped_column(String(120), nullable=True)  # sticky: who holds the chat
    title: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text, default="")  # rolling summary memory (when enabled)
    summarized_upto: Mapped[int] = mapped_column(default=0)  # watermark: messages already summarised
    total_tokens: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "channel", "external_id", name="uq_conv_tenant_channel_external"),
    )
