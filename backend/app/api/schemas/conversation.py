"""Conversation DTOs (LLD 09)."""
from datetime import datetime

from pydantic import Field

from app.api.schemas.common import OutModel, StrictModel


class ConversationOut(OutModel):
    id: int
    channel: str
    external_id: str
    agent_id: int
    workflow_id: int | None = None  # set → this chat is routed per-turn through the workflow's router
    curr_agent: str | None = None  # the specialist currently holding a routed chat (sticky)
    title: str
    summary: str
    total_tokens: int
    created_at: datetime
    last_at: datetime


class ChatIn(StrictModel):
    """One multi-turn chat turn. To START: `agent_id` (plain 1:1) OR `workflow_id` (each turn routed
    through that workflow's router). To CONTINUE: `conversation_id` (its binding is fixed at creation).
    `chat_id` is an optional Telegram chat the agent's send_telegram tool can deliver to."""
    message: str = Field(min_length=1)
    agent_id: int | None = None
    workflow_id: int | None = None
    conversation_id: int | None = None
    chat_id: str | None = None


class ToolUseOut(OutModel):
    tool: str
    ok: bool


class ChatOut(OutModel):
    conversation_id: int
    reply: str
    tools: list[ToolUseOut] = []
    total_tokens: int
    stopped_reason: str
    active_agent: str | None = None  # who produced this reply (the routed specialist, or the agent)
    routed_from: str | None = None  # the prior handler when routing changed this turn (for the UI chip)
