"""LLD 07 — Channels tests (critical-path 'message delivery'). Mock httpx + LLM."""
import httpx
import pytest

import app.channels.telegram as telegram_mod
import app.runtime.agent as agent_mod
import app.runtime.agent_memory as mem_mod
from app.channels.base import Channel, ChannelNotConfigured, InboundMessage, clear_channels, register_channel
from app.channels.dispatcher import dispatch_inbound
from app.channels.telegram import TelegramChannel
from app.llm.types import LLMResult, ToolCall, Usage
from app.models import Agent, Conversation, Message, Run, Tool, Workflow
from app.runtime.executor import GraphExecutor
from app.runtime.tools.base import ToolContext
from app.runtime.tools.builtins.send_telegram import send_telegram
from app.runtime.tools.seed import seed_tools


@pytest.fixture(autouse=True)
def _clear_registry():
    clear_channels()
    yield
    clear_channels()


# ── fakes ─────────────────────────────────────────────────────────────
class _FakeChannel(Channel):
    name = "telegram"

    def __init__(self):
        self.sent = []

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, chat_id, text):
        self.sent.append((chat_id, text))
        return {"ok": True}

    async def handle_update(self, update):
        return None


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {"ok": True, "result": []}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeClient:
    def __init__(self, get_responses=None, get_fn=None):
        self._get_responses = list(get_responses or [])
        self._get_fn = get_fn
        self.post_calls = []

    async def get(self, url, params=None):
        if self._get_fn:
            return await self._get_fn(url, params)
        return self._get_responses.pop(0) if self._get_responses else _Resp(200, {"ok": True, "result": []})

    async def post(self, url, json=None):
        self.post_calls.append((url, json))
        return _Resp(200, {"ok": True, "result": {}})

    async def aclose(self):
        pass


def _msg_update(uid, text, chat=1, is_bot=False):
    return {"update_id": uid,
            "message": {"text": text, "chat": {"id": chat}, "from": {"first_name": "A", "is_bot": is_bot}}}


def _mock_llm(monkeypatch, text="reply", tokens=7):
    async def fake(req, provider=None, fallback=None):
        return LLMResult(text=text, usage=Usage(total_tokens=tokens))

    monkeypatch.setattr(agent_mod, "complete", fake)


# ── handle_update (pure parsing) ──────────────────────────────────────
async def test_handle_update_parsing():
    ch = TelegramChannel("tok", dispatcher=None)
    got = await ch.handle_update(_msg_update(1, "hi"))
    assert got is not None and got.text == "hi" and got.chat_id == "1" and got.user_display == "A"
    assert await ch.handle_update({"edited_message": {"text": "x"}}) is None  # not a 'message'
    assert await ch.handle_update({"message": {"chat": {"id": 5}}}) is None   # no text
    assert await ch.handle_update(_msg_update(2, "x", is_bot=True)) is None    # from a bot


async def test_send_splits_long_text():
    ch = TelegramChannel("tok", dispatcher=None)
    ch._client = _FakeClient()
    await ch.send("c1", "x" * 5000)
    assert len(ch._client.post_calls) == 2  # 4096 + 904
    assert ch._client.post_calls[0][1]["chat_id"] == "c1"


# ── poll loop: offset / at-least-once / 409 ───────────────────────────
async def test_poll_loop_advances_offset_after_dispatch():
    ch = TelegramChannel("tok", dispatcher=None)
    handled = []

    async def disp(inb):
        handled.append(inb)
        if len(handled) >= 2:
            ch._running = False

    ch._dispatch = disp
    ch._client = _FakeClient([_Resp(200, {"ok": True, "result": [_msg_update(10, "a"), _msg_update(11, "b")]})])
    ch._running = True
    await ch._poll_loop()
    assert len(handled) == 2
    assert ch._offset == 12  # last update_id + 1


async def test_poll_loop_advances_even_on_dispatch_error():
    ch = TelegramChannel("tok", dispatcher=None)

    async def disp(inb):
        ch._running = False
        raise RuntimeError("boom")

    ch._dispatch = disp
    ch._client = _FakeClient([_Resp(200, {"ok": True, "result": [_msg_update(7, "a")]})])
    ch._running = True
    await ch._poll_loop()  # must NOT raise
    assert ch._offset == 8  # advanced despite the dispatch error (no wedge)


async def test_poll_loop_409_backs_off_without_crashing(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(telegram_mod.asyncio, "sleep", fake_sleep)
    ch = TelegramChannel("tok", dispatcher=None)
    calls = {"n": 0}

    async def get_fn(url, params=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(409, {})
        ch._running = False
        return _Resp(200, {"ok": True, "result": []})

    ch._client = _FakeClient(get_fn=get_fn)
    ch._running = True
    await ch._poll_loop()  # must not crash
    assert 5 in slept and calls["n"] >= 2  # 409 → backoff → continued


# ── dispatch_inbound (message delivery) ───────────────────────────────
async def test_dispatch_creates_conversation_persists_and_replies(session_factory, monkeypatch):
    register_channel(_FakeChannel())
    with session_factory() as db:
        a = Agent(name="Support", channels=["telegram"], provider="groq", model="m",
                  guardrails={}, memory_config={})
        db.add(a)
        db.commit()
        aid = a.id
    _mock_llm(monkeypatch, text="hi there", tokens=7)

    ch = __import__("app.channels.base", fromlist=["get_channel"]).get_channel("telegram")
    await dispatch_inbound(InboundMessage("telegram", "chat-1", "hello", "Alice"),
                           session_factory=session_factory)

    assert ch.sent == [("chat-1", "hi there")]
    with session_factory() as db:
        conv = db.query(Conversation).filter_by(channel="telegram", external_id="chat-1").one()
        assert conv.agent_id == aid and conv.total_tokens == 7
        msgs = db.query(Message).filter_by(conversation_id=str(conv.id)).order_by(Message.id).all()
        assert [m.role for m in msgs] == ["user", "assistant"]
        assert msgs[0].content == "hello" and msgs[1].content == "hi there"


async def test_dispatch_no_agent_bound_replies_and_no_conversation(session_factory):
    ch = _FakeChannel()
    register_channel(ch)
    await dispatch_inbound(InboundMessage("telegram", "chat-x", "hi"), session_factory=session_factory)
    assert ch.sent and "No agent" in ch.sent[0][1]
    with session_factory() as db:
        assert db.query(Conversation).count() == 0  # no dangling conversation


async def test_dispatch_agent_deleted_replies(session_factory):
    ch = _FakeChannel()
    register_channel(ch)
    with session_factory() as db:
        a = Agent(name="Gone", channels=["telegram"])
        db.add(a)
        db.commit()
        aid = a.id
        db.add(Conversation(channel="telegram", external_id="c1", agent_id=aid))
        db.commit()
        db.delete(db.get(Agent, aid))
        db.commit()
    await dispatch_inbound(InboundMessage("telegram", "c1", "hi"), session_factory=session_factory)
    assert ch.sent and "no longer available" in ch.sent[0][1]


async def test_dispatch_second_message_history_excludes_current(session_factory, monkeypatch):
    """History fed to the agent contains the prior turn but NOT a duplicate of the current input."""
    register_channel(_FakeChannel())
    with session_factory() as db:
        db.add(Agent(name="S", channels=["telegram"], provider="groq", model="m",
                     guardrails={}, memory_config={"window": 12}))
        db.commit()

    captured = {}

    async def fake(req, provider=None, fallback=None):
        captured["messages"] = req.messages
        return LLMResult(text="ok", usage=Usage(total_tokens=3))

    monkeypatch.setattr(agent_mod, "complete", fake)

    await dispatch_inbound(InboundMessage("telegram", "c2", "first"), session_factory=session_factory)
    await dispatch_inbound(InboundMessage("telegram", "c2", "second"), session_factory=session_factory)

    # on the 2nd turn: system + prior(user 'first', assistant 'ok') + current user 'second'
    contents = [m["content"] for m in captured["messages"]]
    assert contents.count("second") == 1  # current input not duplicated
    assert "first" in contents and "ok" in contents  # prior turn present as history


# ── review regression fixes (LLD07 workflow) ──────────────────────────
async def test_send_before_start_raises_channel_not_configured():
    ch = TelegramChannel("tok", dispatcher=None)
    with pytest.raises(ChannelNotConfigured):
        await ch.send("c1", "hi")  # _client is None until start()


async def test_poll_loop_okfalse_escalates_backoff(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(telegram_mod.asyncio, "sleep", fake_sleep)
    ch = TelegramChannel("tok", dispatcher=None)
    calls = {"n": 0}

    async def get_fn(url, params=None):
        calls["n"] += 1
        if calls["n"] <= 2:
            return _Resp(200, {"ok": False})  # API-level error twice
        ch._running = False
        return _Resp(200, {"ok": True, "result": []})

    ch._client = _FakeClient(get_fn=get_fn)
    ch._running = True
    await ch._poll_loop()
    assert slept[:2] == [1.0, 2.0]  # escalating, not a fixed 1s cadence


async def test_poll_loop_malformed_update_does_not_crash():
    ch = TelegramChannel("tok", dispatcher=None)
    handled = []

    async def disp(inb):
        handled.append(inb)
        ch._running = False

    ch._dispatch = disp
    bad = {"message": {"text": "hi", "chat": {"id": 1}, "from": {"first_name": "A"}}}  # no update_id
    ch._client = _FakeClient([_Resp(200, {"ok": True, "result": [bad]})])
    ch._running = True
    await ch._poll_loop()  # the finally must not raise on the missing update_id
    assert len(handled) == 1
    assert ch._offset is None  # no id → not advanced, but no crash/exception-wedge


async def test_send_telegram_tool_explicit_chat_id():
    ch = _FakeChannel()
    register_channel(ch)
    out = await send_telegram({"text": "yo", "chat_id": "42"}, ToolContext())
    assert out["sent"] and out["chat_id"] == "42"
    assert ch.sent == [("42", "yo")]


async def test_send_telegram_tool_missing_target_raises():
    register_channel(_FakeChannel())
    with pytest.raises(ValueError):
        await send_telegram({"text": "hi"}, ToolContext())  # no chat_id arg, no ctx.chat_id


async def test_send_telegram_workflow_uses_run_input_chat_id(session_factory, monkeypatch):
    """Notifier path: a workflow run carries chat_id in its input → send_telegram delivers."""
    ch = _FakeChannel()
    register_channel(ch)
    with session_factory() as db:
        seed_tools(db)
        st_tool = db.query(Tool).filter_by(name="send_telegram").first()
        notifier = Agent(name="Notifier", provider="groq", model="m", guardrails={}, memory_config={})
        notifier.tools = [st_tool]
        db.add(notifier)
        db.commit()
        nid = notifier.id
        graph = {"nodes": [{"id": "start", "type": "start"},
                           {"id": "n", "type": "agent", "ref": nid},
                           {"id": "end", "type": "end"}],
                 "edges": [{"from": "start", "to": "n"}, {"from": "n", "to": "end"}]}
        wf = Workflow(name="notify", graph=graph)
        db.add(wf)
        db.commit()
        run = Run(workflow_id=wf.id, status="running", trigger="manual",
                  input={"text": "go", "chat_id": "555"})
        db.add(run)
        db.commit()
        run_id, gj = run.id, wf.graph

    seq = [
        LLMResult(text="", usage=Usage(total_tokens=2),
                  tool_calls=[ToolCall(id="c1", name="send_telegram", arguments={"text": "done"})]),
        LLMResult(text="notified", usage=Usage(total_tokens=2)),
    ]

    async def fake(req, provider=None, fallback=None):
        return seq.pop(0)

    monkeypatch.setattr(agent_mod, "complete", fake)
    await GraphExecutor(session_factory).execute(run_id, gj)
    assert ch.sent == [("555", "done")]  # pushed to the run's chat_id (threaded into ToolContext)


async def test_reply_sent_even_if_summary_fails(session_factory, monkeypatch):
    ch = _FakeChannel()
    register_channel(ch)
    with session_factory() as db:
        db.add(Agent(name="S", channels=["telegram"], provider="groq", model="m",
                     guardrails={}, memory_config={"window": 1, "summary": True}))
        db.commit()

    async def answer(req, provider=None, fallback=None):
        return LLMResult(text="REAL ANSWER", usage=Usage(total_tokens=5))

    async def boom(req, provider=None, fallback=None):
        raise RuntimeError("503 summariser down")

    monkeypatch.setattr(agent_mod, "complete", answer)
    monkeypatch.setattr(mem_mod, "complete", boom)

    await dispatch_inbound(InboundMessage("telegram", "c5", "first"), session_factory=session_factory)
    await dispatch_inbound(InboundMessage("telegram", "c5", "second"), session_factory=session_factory)
    assert ch.sent[-1] == ("c5", "REAL ANSWER")  # reply delivered despite summariser failure


async def test_rolling_summary_watermark_advances(session_factory, monkeypatch):
    ch = _FakeChannel()
    register_channel(ch)
    with session_factory() as db:
        db.add(Agent(name="S", channels=["telegram"], provider="groq", model="m",
                     guardrails={}, memory_config={"window": 2, "summary": True}))
        db.commit()

    async def answer(req, provider=None, fallback=None):
        return LLMResult(text="ok", usage=Usage(total_tokens=2))

    summarise_calls = []

    async def fake_sum(req, provider=None, fallback=None):
        summarise_calls.append(req.messages[-1]["content"])
        return LLMResult(text="SUM", usage=Usage(total_tokens=1))

    monkeypatch.setattr(agent_mod, "complete", answer)
    monkeypatch.setattr(mem_mod, "complete", fake_sum)

    for i in range(4):
        await dispatch_inbound(InboundMessage("telegram", "c6", f"m{i}"), session_factory=session_factory)

    with session_factory() as db:
        conv = db.query(Conversation).filter_by(external_id="c6").one()
        # 4 turns → 8 messages, window=2 → watermark at 6 (rolling, not re-summarising from 0)
        assert conv.summarized_upto == 6
    assert len(summarise_calls) == 3  # fired on turns 2,3,4 — each only the newly-aged slice


# ── token redaction (the bot token must never leak into errors/logs/events) ──
def test_scrub_removes_token():
    from app.channels.telegram import _scrub

    s = "Client error '400' for url 'https://api.telegram.org/bot999:ABCdef-123/sendMessage'"
    out = _scrub(s, "999:ABCdef-123")
    assert "999:ABCdef-123" not in out and "ABCdef-123" not in out
    # the generic bot<id>:<secret> URL form is scrubbed even without the exact token
    assert "bot<redacted>" in _scrub(s)


async def test_send_redacts_token_on_http_error():
    ch = TelegramChannel("123456:SUPERSECRET", dispatcher=None)

    class _BoomClient:
        async def post(self, url, json=None):
            raise httpx.RequestError(f"failed sending to '{url}'")  # url carries the token

    ch._client = _BoomClient()
    with pytest.raises(RuntimeError) as ei:
        await ch.send("999", "hi")
    msg = str(ei.value)
    assert "SUPERSECRET" not in msg and "123456:SUPERSECRET" not in msg
    assert "redacted" in msg


async def test_history_excludes_workflow_run_messages(session_factory):
    """A chat must NOT inherit workflow-run messages that share its numeric conversation_id
    (the executor writes Message.conversation_id = str(run_id); chats use str(conversation.id))."""
    from app.channels.dispatcher import _load_history

    with session_factory() as db:
        conv = Conversation(channel="web", external_id="x1", agent_id=1, title="t")
        db.add(conv)
        db.commit()
        cid = conv.id
        db.add(Message(conversation_id=str(cid), from_agent="user", to_agent="A",
                       channel="web", role="user", content="hi"))  # real chat turn (run_id NULL)
        db.add(Message(conversation_id=str(cid), run_id=999, from_agent="Researcher", to_agent="",
                       channel="internal", role="assistant", content="Handing off"))  # colliding run msg
        db.commit()

    hist = _load_history(session_factory, str(cid))
    assert len(hist) == 1 and hist[0]["content"] == "hi"
