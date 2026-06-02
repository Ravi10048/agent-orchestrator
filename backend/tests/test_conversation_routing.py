"""Conversational per-turn routing (the LLD 07 stretch). A workflow-bound chat routes EACH turn
through the workflow's router (supervisor → specialist, {n, r}), with a sticky curr_agent.
Mocks the LLM so a routed turn = [router handoff, specialist answer]."""
import pytest
from sqlalchemy import create_engine

import app.runtime.agent as agent_mod
from app.channels.base import Channel, clear_channels, get_channel, register_channel
from app.channels.dispatcher import InboundMessage, converse, dispatch_inbound
from app.core.db import _migrate_sqlite_add_columns
from app.llm.types import LLMResult, ToolCall, Usage
from app.models import Agent, Conversation, Message, Workflow
from app.runtime.agent import compose_system_prompt
from app.runtime.agent_spec import AgentSpec
from app.runtime.conversation_router import resolve_routing
from app.seed.tenants import get_or_create_tenant


# ── fixtures / helpers ────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _clear_registry():
    clear_channels()
    yield
    clear_channels()


class _FakeChannel(Channel):
    name = "telegram"

    def __init__(self):
        self.sent = []

    async def start(self): ...
    async def stop(self): ...
    async def handle_update(self, update): return None

    async def send(self, chat_id, text):
        self.sent.append((chat_id, text))
        return {"ok": True}


def _agent(db, name, role, prompt, tenant_id, channels=()):
    a = Agent(name=name, tenant_id=tenant_id, role=role, system_prompt=prompt, provider="groq",
              model="m", channels=list(channels), guardrails={}, memory_config={"window": 12})
    db.add(a)
    db.commit()
    return a.id


def _mk_router_workflow(db, tenant_id, *, supervisor_channels=("telegram",)):
    """Minimal router workflow: Supervisor → {Pricing, Care} → end (Supervisor is the router)."""
    sup = _agent(db, "Supervisor", "Routing supervisor", "You route to the best specialist.",
                 tenant_id, channels=supervisor_channels)
    _agent(db, "Pricing", "Price & EMI specialist", "You handle price and EMI questions.", tenant_id)
    _agent(db, "Care", "Care & escalation specialist", "You handle complaints and refunds.", tenant_id)
    graph = {
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "supervisor", "type": "agent", "ref": sup},
                  {"id": "pricing", "type": "agent", "ref": db.query(Agent).filter_by(
                      tenant_id=tenant_id, name="Pricing").one().id},
                  {"id": "care", "type": "agent", "ref": db.query(Agent).filter_by(
                      tenant_id=tenant_id, name="Care").one().id},
                  {"id": "end", "type": "end"}],
        "edges": [{"from": "start", "to": "supervisor"},
                  {"from": "supervisor", "to": "pricing"},
                  {"from": "supervisor", "to": "care"},
                  {"from": "pricing", "to": "end"},
                  {"from": "care", "to": "end"}],
    }
    wf = Workflow(name="Router WF", tenant_id=tenant_id, graph=graph, is_template=False)
    db.add(wf)
    db.commit()
    return sup, wf.id


def _routed_llm(monkeypatch, *, route="Pricing", router_reply="Connecting you…", answer="Here you go."):
    """LLM script for ONE routed turn: the router hands off (n=route, r=router_reply), then the
    chosen specialist answers. Captures each request so tests can assert what each agent received."""
    seen = []
    script = [
        LLMResult(text="", usage=Usage(total_tokens=5),
                  tool_calls=[ToolCall(id="h1", name="handoff",
                                       arguments={"to_agent": route, "response": router_reply})]),
        LLMResult(text=answer, usage=Usage(total_tokens=9)),
    ]

    async def fake(req, provider=None, fallback=None):
        seen.append(req)
        return script.pop(0)

    monkeypatch.setattr(agent_mod, "complete", fake)
    return seen


# ── router resolution (find_router on a resolved graph) ───────────────
def test_resolve_routing_finds_supervisor(session_factory):
    with session_factory() as db:
        t = get_or_create_tenant(db, "T", slug="t")
        sup_id, wf_id = _mk_router_workflow(db, t.id)
    routing = resolve_routing(session_factory, wf_id)
    assert routing is not None
    assert routing.router_node.ref == sup_id  # matched by id, not name
    assert set(routing.routes) == {"Pricing", "Care"}
    assert routing.descriptions["Pricing"] and routing.descriptions["Care"]  # roles injected


def test_resolve_routing_none_for_linear_workflow(session_factory):
    """A single-agent (or <2-route) workflow is NOT a router → None → caller falls back to 1:1."""
    with session_factory() as db:
        t = get_or_create_tenant(db, "T2", slug="t2")
        aid = _agent(db, "Solo", "solo", "You help.", t.id)
        wf = Workflow(name="Linear", tenant_id=t.id, is_template=False, graph={
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "a", "type": "agent", "ref": aid},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "a"}, {"from": "a", "to": "end"}]})
        db.add(wf)
        db.commit()
        wf_id = wf.id
    assert resolve_routing(session_factory, wf_id) is None


def test_resolve_routing_none_for_missing_workflow(session_factory):
    assert resolve_routing(session_factory, 99999) is None  # deleted mid-chat → runtime guard → 1:1


# ── sticky prompt (compose_system_prompt) ─────────────────────────────
def test_sticky_hint_present_absent_and_gated():
    spec = AgentSpec(name="Supervisor", role="router", system_prompt="route", provider="groq",
                     model="m", tools=[], guardrails={}, memory_config={})
    routes, descs = ["Pricing", "Care"], {"Pricing": "price", "Care": "care"}
    assert "currently being handled by Pricing" in compose_system_prompt(
        spec, routes, "", None, descs, "Pricing")
    # stale handler (not a live route) → hint dropped (self-healing)
    assert "currently being handled" not in compose_system_prompt(spec, routes, "", None, descs, "Ghost")
    # no routes at all (1:1) → no hint
    assert "currently being handled" not in compose_system_prompt(spec, [], "", None, {}, "Pricing")


# ── the web routed turn (converse) ────────────────────────────────────
async def test_web_converse_routes_and_specialist_gets_original_message(session_factory, monkeypatch):
    with session_factory() as db:
        t = get_or_create_tenant(db, "WEB", slug="web")
        _mk_router_workflow(db, t.id)
        tid = t.id
        wf_id = db.query(Workflow).filter_by(tenant_id=tid).one().id
    seen = _routed_llm(monkeypatch, route="Pricing", router_reply="Let me help with the price",
                       answer="No-Cost EMI is ₹2,000/mo.")

    r = await converse(session_factory, text="this sofa is too expensive", workflow_id=wf_id, tenant_id=tid)

    assert len(seen) == 2  # exactly two LLM calls: router → specialist
    # the SPECIALIST received the ORIGINAL user message (the {n,r} forward), never the router's ack
    specialist_msgs = " ".join(m.get("content", "") for m in seen[1].messages)
    assert "this sofa is too expensive" in specialist_msgs
    assert "Let me help with the price" not in specialist_msgs
    # the visible reply is the specialist's; routing is surfaced
    assert r["reply"] == "No-Cost EMI is ₹2,000/mo."
    assert r["active_agent"] == "Pricing" and r["routed_from"] is None  # first turn → no prior handler
    assert r["total_tokens"] == 14  # 5 (router) + 9 (specialist)
    cid = r["conversation_id"]
    with session_factory() as db:
        conv = db.get(Conversation, cid)
        assert conv.workflow_id == wf_id and conv.curr_agent == "Pricing"  # sticky persisted
        msgs = db.query(Message).filter_by(conversation_id=str(cid)).order_by(Message.id).all()
        assert [m.role for m in msgs] == ["user", "assistant"]
        assert msgs[1].from_agent == "Pricing"  # the specialist authored the reply → routing is visible


async def test_sticky_then_reroute_on_topic_switch(session_factory, monkeypatch):
    with session_factory() as db:
        t = get_or_create_tenant(db, "STK", slug="stk")
        _mk_router_workflow(db, t.id)
        tid = t.id
        wf_id = db.query(Workflow).filter_by(tenant_id=tid).one().id

    _routed_llm(monkeypatch, route="Pricing", answer="EMI options ready.")
    r1 = await converse(session_factory, text="too expensive", workflow_id=wf_id, tenant_id=tid)
    cid = r1["conversation_id"]

    seen2 = _routed_llm(monkeypatch, route="Care", router_reply="Let me get Care to help", answer="So sorry — refunding now.")
    r2 = await converse(session_factory, text="this is terrible, I want a refund", conversation_id=cid, tenant_id=tid)

    # turn 2: the router's system prompt carried the sticky 'currently handled by Pricing' hint…
    router_system = seen2[0].messages[0]["content"]
    assert "currently being handled by Pricing" in router_system
    # …yet the topic switch re-routed to Care (visible via routed_from)
    assert r2["active_agent"] == "Care" and r2["routed_from"] == "Pricing"
    with session_factory() as db:
        assert db.get(Conversation, cid).curr_agent == "Care"


async def test_router_answers_directly_no_handoff(session_factory, monkeypatch):
    with session_factory() as db:
        t = get_or_create_tenant(db, "DIR", slug="dir")
        _mk_router_workflow(db, t.id)
        tid = t.id
        wf_id = db.query(Workflow).filter_by(tenant_id=tid).one().id

    async def fake(req, provider=None, fallback=None):  # no tool calls → router answers itself
        return LLMResult(text="Hi! How can I help today?", usage=Usage(total_tokens=4))

    monkeypatch.setattr(agent_mod, "complete", fake)
    r = await converse(session_factory, text="hello", workflow_id=wf_id, tenant_id=tid)
    assert r["reply"] == "Hi! How can I help today?"
    assert r["active_agent"] == "Supervisor" and r["routed_from"] is None
    with session_factory() as db:
        assert db.get(Conversation, r["conversation_id"]).curr_agent == "Supervisor"  # clean self-answer pins


async def test_converse_rejects_cross_tenant_workflow(session_factory):
    with session_factory() as db:
        owner = get_or_create_tenant(db, "OWN", slug="own")
        _mk_router_workflow(db, owner.id)
        wf_id = db.query(Workflow).filter_by(tenant_id=owner.id).one().id
        other = get_or_create_tenant(db, "OTHER", slug="other").id
    with pytest.raises(ValueError, match="workflow not found"):  # tenant B can't bind tenant A's workflow
        await converse(session_factory, text="hi", workflow_id=wf_id, tenant_id=other)


# ── Telegram: lazy-bind a channel chat to its router workflow ─────────
async def test_telegram_lazy_binds_and_routes(session_factory, monkeypatch):
    ch = _FakeChannel()
    register_channel(ch)
    with session_factory() as db:
        t = get_or_create_tenant(db, "TG", slug="tg")
        _mk_router_workflow(db, t.id)  # Supervisor has channels=["telegram"]
        wf_id = db.query(Workflow).filter_by(tenant_id=t.id).one().id
    _routed_llm(monkeypatch, route="Pricing", answer="EMI plan ready.")

    await dispatch_inbound(InboundMessage("telegram", "tg-1", "the price is too high", "Bob"),
                           session_factory=session_factory)

    assert get_channel("telegram").sent == [("tg-1", "EMI plan ready.")]  # specialist's answer delivered
    with session_factory() as db:
        conv = db.query(Conversation).filter_by(external_id="tg-1").one()
        assert conv.workflow_id == wf_id  # lazily bound on first turn
        assert conv.curr_agent == "Pricing"
        msgs = db.query(Message).filter_by(conversation_id=str(conv.id)).order_by(Message.id).all()
        assert msgs[-1].from_agent == "Pricing"  # routing visible in the persisted transcript


# ── the dev-safe SQLite column shim ───────────────────────────────────
def test_migrate_sqlite_add_columns_is_idempotent(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as c:  # simulate a pre-feature table (missing the new columns)
        c.exec_driver_sql("CREATE TABLE conversations (id INTEGER PRIMARY KEY, channel VARCHAR)")
    _migrate_sqlite_add_columns(eng)
    _migrate_sqlite_add_columns(eng)  # second call is a no-op (idempotent)
    with eng.begin() as c:
        cols = {row[1] for row in c.exec_driver_sql("PRAGMA table_info(conversations)")}
    assert {"workflow_id", "curr_agent"} <= cols
