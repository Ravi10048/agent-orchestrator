"""Inbound dispatch — the 1:1 human↔agent path (LLD 07).

Resolve the bound agent FIRST, then find/create the Conversation (agent_id is NOT NULL),
persist inbound, run the SAME AgentRunner in 1:1 mode (no bus, no handoff tools), persist
outbound, roll counters + optional summary memory, then reply. Always sends result.text.
"""
import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.channels.base import InboundMessage, get_channel
from app.models import Agent, Conversation, Message, Workflow
from app.models.enums import EventType
from app.runtime.agent import AgentInput, AgentRunner
from app.runtime.agent_memory import summarize_history
from app.runtime.agent_spec import build_agent_spec
from app.runtime.conversation_router import (
    resolve_routing,
    run_routed_turn,
    workflow_for_router_agent,
)
from app.runtime.tools.base import ToolContext

log = logging.getLogger("channels.dispatcher")

NO_AGENT_REPLY = "No agent is connected to this channel yet. Configure one in the app, then message again."
AGENT_DELETED_REPLY = "Sorry — the agent for this chat is no longer available."


def effective_routing(session_factory, conv_id: int):
    """Resolve the per-turn router for a CHANNEL conversation (Telegram). Uses conv.workflow_id when
    already bound; otherwise LAZILY binds when conv.agent_id is itself the router of a non-template
    workflow in conv.tenant_id — so a fresh channel chat (or one created before this feature) auto-
    upgrades to routed instead of stranding on a router agent that's told never to answer 1:1.
    Returns a Routing or None (plain 1:1). (Web chats bind explicitly at creation; no lazy bind.)"""
    with session_factory() as db:
        conv = db.get(Conversation, conv_id)
        if conv is None:
            return None
        wf_id, agent_id, tenant_id = conv.workflow_id, conv.agent_id, conv.tenant_id
    if wf_id is None:
        wf_id = workflow_for_router_agent(session_factory, agent_id, tenant_id)
        if wf_id is not None:
            with session_factory() as db:  # persist the binding once (write-once; ignored if a race set it)
                c = db.get(Conversation, conv_id)
                if c is not None and c.workflow_id is None:
                    c.workflow_id = wf_id
                    db.commit()
    return resolve_routing(session_factory, wf_id)


def make_dispatcher(session_factory):
    """Build the dispatch callable the Channel poll loop calls (LLD 09 lifespan wiring).
    (Channel turns aren't monitored runs in v1, so no hub fan-out — visible via Conversations UI.)"""
    async def _dispatch(inb: InboundMessage) -> None:
        await dispatch_inbound(inb, session_factory=session_factory)

    return _dispatch


def resolve_agent_for_channel(db, channel: str) -> Agent | None:
    """First agent with this channel enabled (JSON list membership; iterated for SQLite)."""
    for a in db.query(Agent).order_by(Agent.id.asc()).all():
        if channel in (a.channels or []):
            return a
    return None


async def dispatch_inbound(inb: InboundMessage, *, session_factory, emit=None) -> dict | None:
    emit = emit or (lambda *a, **k: None)
    channel = get_channel(inb.channel)

    # (A) resolve the bound AGENT first, then create the Conversation (agent_id NOT NULL)
    with session_factory() as db:
        conv = db.query(Conversation).filter_by(channel=inb.channel, external_id=inb.chat_id).first()
        if conv is None:
            agent = resolve_agent_for_channel(db, inb.channel)
            if agent is None:
                return await channel.send(inb.chat_id, NO_AGENT_REPLY)  # nothing bound → reply + stop
            conv = Conversation(channel=inb.channel, external_id=inb.chat_id, tenant_id=agent.tenant_id,
                                agent_id=agent.id, title=inb.user_display or inb.chat_id)
            db.add(conv)
            try:
                db.commit()
            except IntegrityError:  # concurrent first message (unique constraint) → re-read
                db.rollback()
                conv = db.query(Conversation).filter_by(
                    channel=inb.channel, external_id=inb.chat_id).first()
        agent = db.get(Agent, conv.agent_id)
        if agent is None:
            return await channel.send(inb.chat_id, AGENT_DELETED_REPLY)
        spec = build_agent_spec(agent)
        conv_id, agent_name, summary = conv.id, agent.name, conv.summary
        conv_curr_agent = conv.curr_agent
        window = spec.memory_config.get("window", 12)
        want_summary = bool(spec.memory_config.get("summary"))

    # If this chat is workflow-bound (or its agent IS a router), route each turn through the router.
    routing = effective_routing(session_factory, conv_id)

    # (B) load PRIOR history (before persisting the current msg → no dup), then persist inbound
    history = _load_history(session_factory, str(conv_id), window=window)
    _persist_message(session_factory, conversation_id=str(conv_id), from_agent="user",
                     to_agent=agent_name, channel=inb.channel, role="user", content=inb.text)

    # (C) produce the reply — per-turn routed (router → specialist) OR single-agent 1:1
    if routing is not None:
        turn = await run_routed_turn(session_factory, routing, text=inb.text, history=history,
                                     summary=summary, curr_agent=conv_curr_agent,
                                     chat_id=inb.chat_id, conv_id=conv_id)
        reply_text, out_from, out_tokens, out_tools = turn.reply, turn.active_agent, turn.total_tokens, turn.tools
        new_curr = turn.active_agent if turn.advance_curr_agent else None
    else:
        result = await AgentRunner(spec, bus=None, emit=emit).run(AgentInput(
            input=inb.text, history=history, summary=summary, allowed_routes=[],
            ctx=ToolContext(conversation_id=str(conv_id), chat_id=inb.chat_id, agent_name=agent_name)))
        reply_text, out_from, out_tokens, out_tools, new_curr = (
            result.text, agent_name, result.usage.total_tokens, None, None)

    # (D) persist outbound + roll counters (+ sticky curr_agent on a routed turn)
    _persist_message(session_factory, conversation_id=str(conv_id), from_agent=out_from,
                     to_agent="user", channel=inb.channel, role="assistant",
                     content=reply_text, tokens=out_tokens, tool_calls=out_tools)
    with session_factory() as db:
        c = db.get(Conversation, conv_id)
        if c:
            c.total_tokens += out_tokens
            c.last_at = datetime.now(UTC)
            if new_curr is not None:
                c.curr_agent = new_curr
            db.commit()

    # (E) reply FIRST — delivery must never be gated by the optional (LLM-backed) summary step
    send_result = await channel.send(inb.chat_id, reply_text)

    # (F) best-effort rolling summary — a summariser failure must not suppress the reply
    if want_summary:
        try:
            await _refresh_summary(session_factory, conv_id, window, spec.model)
        except Exception:
            log.exception("summary refresh failed for conversation %s", conv_id)
    return send_result


async def converse(session_factory, *, text, agent_id=None, conversation_id=None,
                   chat_id=None, channel="web", tenant_id=None, workflow_id=None) -> dict:
    """One multi-turn conversation turn (the in-app/web chat path). Same memory + persistence as the
    Telegram dispatcher — load prior history, persist inbound, run the turn, persist outbound, roll
    the rolling summary — but the reply is RETURNED (no external channel send). To START a chat pass
    `agent_id` (plain 1:1) OR `workflow_id` (each turn routed through that workflow's router); pass
    `conversation_id` to CONTINUE one (its binding is fixed at creation — a workflow_id sent on a
    continue is ignored). Returns active_agent/routed_from so the UI can show who handled the turn."""
    tools_used: list[dict] = []

    def emit(etype, payload=None, **_):
        if str(etype) == EventType.TOOL_CALL and payload:
            tools_used.append({"tool": payload.get("tool"), "ok": payload.get("ok", True)})
        return {}

    # (A) resolve / create the Conversation
    with session_factory() as db:
        if conversation_id is not None:
            conv = db.get(Conversation, conversation_id)
            if conv is None or (tenant_id is not None and conv.tenant_id != tenant_id):
                raise ValueError("conversation not found")
        elif workflow_id is not None:
            # START a workflow-routed chat — bind to the workflow's router (the entry agent IS the router)
            wf = db.get(Workflow, workflow_id)
            if wf is None or (tenant_id is not None and wf.tenant_id != tenant_id):
                raise ValueError("workflow not found")
            r = resolve_routing(session_factory, workflow_id)
            if r is None:
                raise ValueError("this workflow has no router to route through")
            router_agent = db.get(Agent, r.router_node.ref)
            if router_agent is None or (tenant_id is not None and router_agent.tenant_id != tenant_id):
                raise ValueError("workflow router agent not found")
            conv = Conversation(channel=channel, external_id=uuid4().hex, agent_id=router_agent.id,
                                workflow_id=workflow_id, tenant_id=router_agent.tenant_id, title="In-app chat")
            db.add(conv)
            db.commit()
            db.refresh(conv)
        else:
            if agent_id is None:
                raise ValueError("agent_id or workflow_id is required to start a conversation")
            agent = db.get(Agent, agent_id)
            if agent is None or (tenant_id is not None and agent.tenant_id != tenant_id):
                raise ValueError("agent not found")
            conv = Conversation(channel=channel, external_id=uuid4().hex, agent_id=agent_id,
                                tenant_id=agent.tenant_id, title="In-app chat")
            db.add(conv)
            db.commit()
            db.refresh(conv)
        agent = db.get(Agent, conv.agent_id)
        if agent is None:
            raise ValueError("the agent for this conversation is no longer available")
        spec = build_agent_spec(agent)
        conv_id, agent_name, summary = conv.id, agent.name, conv.summary
        conv_curr_agent, conv_workflow_id = conv.curr_agent, conv.workflow_id
        window = spec.memory_config.get("window", 12)
        want_summary = bool(spec.memory_config.get("summary"))

    # resolve the router for this turn (web binding is explicit at creation — no lazy bind)
    routing = resolve_routing(session_factory, conv_workflow_id)

    # (B) prior history (before persisting the new turn → no dup), then persist inbound
    history = _load_history(session_factory, str(conv_id), window=window)
    _persist_message(session_factory, conversation_id=str(conv_id), from_agent="user",
                     to_agent=agent_name, channel=channel, role="user", content=text)

    # (C) produce the reply — per-turn routed (router → specialist) OR single-agent 1:1 with its tools
    if routing is not None:
        turn = await run_routed_turn(session_factory, routing, text=text, history=history,
                                     summary=summary, curr_agent=conv_curr_agent,
                                     chat_id=chat_id, conv_id=conv_id)
        reply_text, out_from, out_tokens, out_tools, stopped = (
            turn.reply, turn.active_agent, turn.total_tokens, turn.tools, turn.stopped_reason)
        active_agent, routed_from = turn.active_agent, turn.routed_from
        new_curr = turn.active_agent if turn.advance_curr_agent else None
    else:
        result = await AgentRunner(spec, bus=None, emit=emit).run(AgentInput(
            input=text, history=history, summary=summary, allowed_routes=[],
            ctx=ToolContext(conversation_id=str(conv_id), chat_id=chat_id, agent_name=agent_name)))
        reply_text, out_from, out_tokens, out_tools, stopped = (
            result.text, agent_name, result.usage.total_tokens, tools_used, result.stopped_reason)
        active_agent, routed_from, new_curr = None, None, None

    # (D) persist outbound (with the tools this turn invoked → visible in the conversation flow) + roll counters
    _persist_message(session_factory, conversation_id=str(conv_id), from_agent=out_from,
                     to_agent="user", channel=channel, role="assistant",
                     content=reply_text, tokens=out_tokens, tool_calls=out_tools)
    with session_factory() as db:
        c = db.get(Conversation, conv_id)
        if c:
            c.total_tokens += out_tokens
            c.last_at = datetime.now(UTC)
            if new_curr is not None:
                c.curr_agent = new_curr
            db.commit()

    # (E) best-effort rolling summary (never blocks the reply)
    if want_summary:
        try:
            await _refresh_summary(session_factory, conv_id, window, spec.model)
        except Exception:
            log.exception("summary refresh failed for conversation %s", conv_id)

    return {
        "conversation_id": conv_id,
        "reply": reply_text,
        "tools": out_tools or [],
        "total_tokens": out_tokens,
        "stopped_reason": stopped,
        "active_agent": active_agent,
        "routed_from": routed_from,
    }


# ── persistence / memory helpers ──────────────────────────────────────
def _persist_message(session_factory, *, conversation_id, from_agent, to_agent, channel,
                     role, content, tokens=0, tool_calls=None) -> None:
    with session_factory() as db:
        db.add(Message(conversation_id=conversation_id, from_agent=from_agent, to_agent=to_agent,
                       channel=channel, role=role, content=content, tokens=tokens,
                       tool_calls=tool_calls or None))
        db.commit()


def _to_openai(m: Message) -> dict:
    role = m.role if m.role in ("user", "assistant", "system") else "user"
    return {"role": role, "content": m.content}


def _load_history(session_factory, conversation_id: str, window: int = 12) -> list[dict]:
    # Called BEFORE the current inbound is persisted → these are prior turns only (no dup with input).
    # run_id IS NULL keeps this to CHAT turns — workflow-run messages reuse the numeric id space in
    # Message.conversation_id (executor writes str(run_id)), so without this a chat could inherit them.
    with session_factory() as db:
        rows = (db.query(Message)
                .filter(Message.conversation_id == conversation_id, Message.run_id.is_(None))
                .order_by(Message.id.asc()).all())
    if window and window > 0:
        rows = rows[-window:]
    return [_to_openai(m) for m in rows]


async def _refresh_summary(session_factory, conv_id, window: int, model: str | None) -> None:
    """Truly rolling: summarise ONLY the messages that newly aged out of the window since the
    last refresh, folded into the prior summary. A watermark (`summarized_upto`) prevents
    re-summarising (and double-counting) old turns, so the summariser input stays bounded."""
    with session_factory() as db:
        rows = (db.query(Message).filter_by(conversation_id=str(conv_id))
                .order_by(Message.id.asc()).all())
        conv = db.get(Conversation, conv_id)
        prior = conv.summary if conv else ""
        already = (conv.summarized_upto if conv else 0) or 0
    cutoff = max(0, len(rows) - window)  # everything before cutoff has aged out of the window
    if cutoff <= already:
        return  # nothing newly aged out since the last refresh
    newly = [_to_openai(m) for m in rows[already:cutoff]]
    summary = await summarize_history(newly, prior=prior, model=model)
    with session_factory() as db:
        conv = db.get(Conversation, conv_id)
        if conv:
            conv.summary = summary
            conv.summarized_upto = cutoff
            db.commit()
