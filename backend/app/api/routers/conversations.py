"""Conversations router (LLD 09) — channel chat history, visible in the UI, plus the in-app
multi-turn chat turn endpoint (same memory/persistence as the Telegram path).
All reads/writes are scoped to the current tenant."""
from fastapi import APIRouter, Depends, Query

from app.api.schemas.common import Page
from app.api.schemas.conversation import ChatIn, ChatOut, ConversationOut
from app.api.schemas.run import MessageOut
from app.channels.dispatcher import converse
from app.core.deps import current_tenant_id, get_db, get_run_service
from app.core.errors import BadRequest, ResourceNotFound
from app.models import Conversation, Message

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("/chat", response_model=ChatOut)
async def chat(body: ChatIn, rs=Depends(get_run_service), tenant_id: int = Depends(current_tenant_id)):
    """Send one multi-turn chat turn to an agent. Async — the agent loop + LLM run off the
    event loop's critical path; history/memory are persisted so the next turn has context."""
    if body.conversation_id is None and body.agent_id is None and body.workflow_id is None:
        raise BadRequest("provide agent_id or workflow_id (new chat) or conversation_id (continue)")
    try:
        result = await converse(rs.session_factory, text=body.message, agent_id=body.agent_id,
                                conversation_id=body.conversation_id, chat_id=body.chat_id,
                                tenant_id=tenant_id, workflow_id=body.workflow_id)
    except ValueError as e:
        raise ResourceNotFound(str(e)) from e
    return ChatOut(**result)


def _get(db, conv_id: int, tenant_id: int) -> Conversation:
    conv = db.query(Conversation).filter_by(id=conv_id, tenant_id=tenant_id).first()
    if conv is None:
        raise ResourceNotFound("conversation not found")
    return conv


@router.get("", response_model=Page[ConversationOut])
def list_conversations(agent_id: int | None = Query(None), channel: str | None = Query(None),
                       db=Depends(get_db), tenant_id: int = Depends(current_tenant_id),
                       limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    q = db.query(Conversation).filter(Conversation.tenant_id == tenant_id)
    if agent_id is not None:
        q = q.filter(Conversation.agent_id == agent_id)
    if channel is not None:
        q = q.filter(Conversation.channel == channel)
    q = q.order_by(Conversation.last_at.desc())
    total = q.count()
    items = [ConversationOut.model_validate(c) for c in q.limit(limit).offset(offset).all()]
    return Page[ConversationOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/{conv_id}", response_model=ConversationOut)
def get_conversation(conv_id: int, db=Depends(get_db), tenant_id: int = Depends(current_tenant_id)):
    return ConversationOut.model_validate(_get(db, conv_id, tenant_id))


@router.get("/{conv_id}/messages", response_model=Page[MessageOut])
def conversation_messages(conv_id: int, db=Depends(get_db), tenant_id: int = Depends(current_tenant_id),
                          limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)):
    _get(db, conv_id, tenant_id)
    # run_id IS NULL → only this conversation's CHAT turns (workflow-run messages reuse the numeric
    # id space in Message.conversation_id, so they'd otherwise leak into a same-id conversation).
    q = (db.query(Message)
         .filter(Message.conversation_id == str(conv_id), Message.run_id.is_(None))
         .order_by(Message.id.asc()))
    total = q.count()
    items = [MessageOut.model_validate(m) for m in q.limit(limit).offset(offset).all()]
    return Page[MessageOut](items=items, total=total, limit=limit, offset=offset)
