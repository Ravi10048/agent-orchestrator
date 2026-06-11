"""The three critical paths (agent creation · workflow execution · message delivery), exercised
end-to-end against the REAL executor/agent/channel code with a mock LLM (deterministic, no API key / network):

  1. Agent creation     — POST /api/agents persists config + tool mapping; reload is intact.
  2. Workflow execution — template T1 runs incl. ONE feedback loop → completed, ≥2 agents, events.
  3. Message delivery   — an inbound Telegram message → conversation + persisted turns + reply sent.
"""
from app.channels.base import Channel, InboundMessage, clear_channels, register_channel
from app.channels.dispatcher import converse, dispatch_inbound
from app.core.tenancy import get_or_create_default_tenant
from app.llm.types import LLMResult, ToolCall, Usage
from app.models import Agent, Conversation, Message, Run, Tool, Workflow
from app.models.event import RunEvent
from app.runtime.executor import GraphExecutor
from app.runtime.tools.seed import seed_tools
from app.seed import run_seed

T1_NAME = "Research → Report → Notify"


# ── 1. agent creation ──────────────────────────────────────────────────
def test_agent_creation_persists_config_and_tools(client, session_factory):
    with session_factory() as db:
        tid = get_or_create_default_tenant(db).id  # the tenant the API scopes to (no header)
        seed_tools(db, tenant_id=tid)
        calc_id = db.query(Tool).filter_by(tenant_id=tid, name="calculator").first().id

    body = {
        "name": "Analyst",
        "role": "Data analyst",
        "system_prompt": "Analyse the numbers and explain them.",
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "tool_ids": [calc_id],
        "guardrails": {"max_steps": 5, "max_tokens": 800, "max_tokens_total": 6000, "timeout_s": 45},
        "memory_config": {"type": "short_term", "window": 8, "summary": False},
        "channels": ["telegram"],
    }
    r = client.post("/api/agents", json=body)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert [t["name"] for t in r.json()["tools"]] == ["calculator"]

    # reload from a fresh request → every configured dimension + the tool mapping survived
    got = client.get(f"/api/agents/{aid}").json()
    assert got["guardrails"]["max_steps"] == 5
    assert got["memory_config"]["window"] == 8
    assert got["channels"] == ["telegram"]
    assert [t["name"] for t in got["tools"]] == ["calculator"]


# ── 2. workflow execution (with a real feedback loop) ──────────────────
async def test_workflow_execution_with_feedback_loop(session_factory, llm):
    with session_factory() as db:
        run_seed(db)
        t1 = db.query(Workflow).filter_by(name=T1_NAME, is_template=True).first()
        graph = t1.graph
        run = Run(workflow_id=t1.id, status="running", trigger="manual",
                  input={"text": "small language models"})
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

    # script the agents: Writer asks for more once (loop), then finalises; Notifier just confirms.
    llm["queue"] = [
        LLMResult(text="Found initial facts about small language models.", usage=Usage(total_tokens=12)),
        LLMResult(text='Draft brief.\n```json\n{"needs_more": true}\n```', usage=Usage(total_tokens=15)),
        LLMResult(text="Deeper, more specific facts about SLMs.", usage=Usage(total_tokens=12)),
        LLMResult(text='Final brief on SLMs.\n```json\n{"needs_more": false}\n```', usage=Usage(total_tokens=15)),
        LLMResult(text="Brief delivered to the user.", usage=Usage(total_tokens=8)),
    ]

    await GraphExecutor(session_factory).execute(run_id, graph)

    with session_factory() as db:
        run = db.get(Run, run_id)
        assert run.status == "completed"
        assert run.total_tokens > 0

        events = db.query(RunEvent).filter_by(run_id=run_id).order_by(RunEvent.seq.asc()).all()
        seqs = [e.seq for e in events]
        assert seqs == sorted(seqs) and seqs[0] == 1  # ordered + monotonic from 1 (replay contract)
        types = {e.type for e in events}
        assert "run_started" in types and "run_finished" in types

        # the feedback loop actually fired: the researcher node ran twice
        started = [e.payload.get("node_id") for e in events if e.type == "node_started"]
        assert started.count("researcher") == 2

        # 2+ agents collaborated; their outputs were persisted as messages
        agents_ran = {
            e.payload.get("agent_name")
            for e in events
            if e.type == "node_finished" and e.payload.get("agent_name")
        }
        assert len(agents_ran) >= 2
        assert db.query(Message).filter_by(run_id=run_id).count() >= 1


# ── 3. message delivery (inbound channel → reply) ──────────────────────
class _FakeChannel(Channel):
    name = "telegram"

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def start(self):  # pragma: no cover - not used here
        pass

    async def stop(self):  # pragma: no cover
        pass

    async def send(self, chat_id, text):
        self.sent.append((chat_id, text))
        return {"ok": True}

    async def handle_update(self, update):  # pragma: no cover
        return None


async def test_message_delivery_creates_conversation_and_replies(session_factory, llm):
    with session_factory() as db:
        run_seed(db)  # Supervisor is the telegram-reachable agent

    clear_channels()
    fake = _FakeChannel()
    register_channel(fake)
    llm["default"] = LLMResult(text="Thanks — I can help with that.", usage=Usage(total_tokens=9))

    inbound = InboundMessage(channel="telegram", chat_id="555",
                             text="my card was charged twice", user_display="Sam")
    try:
        await dispatch_inbound(inbound, session_factory=session_factory)

        with session_factory() as db:
            conv = db.query(Conversation).filter_by(channel="telegram", external_id="555").first()
            assert conv is not None and conv.agent_id is not None  # bound to an agent (NOT NULL)

            msgs = (db.query(Message).filter_by(conversation_id=str(conv.id))
                    .order_by(Message.id.asc()).all())
            roles = [m.role for m in msgs]
            assert "user" in roles and "assistant" in roles  # inbound + outbound persisted
            assert msgs[0].content == "my card was charged twice"

        # the reply was actually delivered to the right chat
        assert fake.sent and fake.sent[-1][0] == "555"
        assert fake.sent[-1][1] == "Thanks — I can help with that."
    finally:
        clear_channels()


# ── 4. multi-turn conversation (memory + persistence + mid-chat tool use) ──
async def test_multi_turn_chat_remembers_and_invokes_tool(session_factory, monkeypatch):
    import app.runtime.agent as agent_mod

    # a conversational agent that owns the send_telegram tool
    with session_factory() as db:
        seed_tools(db)
        tg = db.query(Tool).filter_by(name="send_telegram").first()
        a = Agent(name="Concierge", provider="groq", model="m", guardrails={}, memory_config={"window": 12})
        a.tools = [tg]
        db.add(a)
        db.commit()
        aid = a.id

    seen = []  # capture each request the agent sends to the LLM
    script = [
        LLMResult(text="What endpoint is affected?", usage=Usage(total_tokens=8)),  # turn 1
        LLMResult(text="Got it — the /orders endpoint.", usage=Usage(total_tokens=8)),  # turn 2
        # turn 3 → the agent decides to notify via the tool, then confirms
        LLMResult(text="", usage=Usage(total_tokens=6),
                  tool_calls=[ToolCall(id="c1", name="send_telegram", arguments={"text": "Summary: /orders 500s"})]),
        LLMResult(text="I've sent a summary to your Telegram.", usage=Usage(total_tokens=7)),
    ]

    async def fake(req, provider=None, fallback=None):
        seen.append(req)
        return script.pop(0)

    monkeypatch.setattr(agent_mod, "complete", fake)

    r1 = await converse(session_factory, text="my API returns 500", agent_id=aid)
    cid = r1["conversation_id"]
    r2 = await converse(session_factory, text="the /orders endpoint", conversation_id=cid)
    r3 = await converse(session_factory, text="no, that's all", conversation_id=cid, chat_id="999")

    # one continuous conversation
    assert r2["conversation_id"] == cid and r3["conversation_id"] == cid

    # MEMORY: by turn 2 the agent's prompt carried the turn-1 exchange
    turn2 = " ".join(m.get("content", "") for m in seen[1].messages)
    assert "my API returns 500" in turn2 and "What endpoint is affected?" in turn2

    # the agent invoked the Telegram tool mid-conversation
    assert any(t["tool"] == "send_telegram" for t in r3["tools"])

    # full transcript persisted: 3 user + 3 assistant turns, in order
    with session_factory() as db:
        roles = [m.role for m in db.query(Message).filter_by(conversation_id=str(cid)).order_by(Message.id).all()]
        assert roles == ["user", "assistant", "user", "assistant", "user", "assistant"]
        assert db.query(Conversation).filter_by(id=cid).one().total_tokens > 0
