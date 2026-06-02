"""LLD 05 — Agent tests (core of the critical-path 'workflow execution'). Mock LLM."""
import app.runtime.agent as agent_mod
import app.runtime.agent_memory as mem
from app.llm.types import LLMResult, ToolCall, Usage
from app.models.enums import EventType
from app.models.tool import Tool
from app.runtime.agent import AgentInput, AgentRunner, compose_system_prompt
from app.runtime.agent_spec import AgentSpec
from app.runtime.bus import new_bus


# ── helpers ───────────────────────────────────────────────────────────
def _spec(tools=None, name="Agent", guardrails=None) -> AgentSpec:
    return AgentSpec(name=name, role="", system_prompt="You are helpful.", provider="groq",
                     model="llama-3.3-70b-versatile", tools=tools or [],
                     guardrails=guardrails or {}, memory_config={})


def _tc(name, args, cid="c1") -> ToolCall:
    return ToolCall(id=cid, name=name, arguments=args)


def _result(text="", tool_calls=None, tokens=10) -> LLMResult:
    return LLMResult(text=text, tool_calls=tool_calls or [],
                     usage=Usage(prompt_tokens=tokens, total_tokens=tokens))


def _scripted(*results):
    seq = list(results)

    async def fake_complete(req, provider=None, fallback=None):
        return seq.pop(0)

    return fake_complete


def _calc_tool() -> Tool:
    return Tool(name="calculator", type="builtin", builtin_key="calculator", params_schema={})


# ── tests ─────────────────────────────────────────────────────────────
async def test_final_answer(monkeypatch):
    monkeypatch.setattr(agent_mod, "complete", _scripted(_result(text="hello")))
    res = await AgentRunner(_spec()).run(AgentInput(input="hi"))
    assert res.text == "hello"
    assert res.stopped_reason == "complete"
    assert res.usage.total_tokens == 10


async def test_tool_loop_executes_and_emits(monkeypatch):
    monkeypatch.setattr(agent_mod, "complete", _scripted(
        _result(tool_calls=[_tc("calculator", {"expression": "2+3"})]),
        _result(text="The answer is 5."),
    ))
    events = []
    res = await AgentRunner(_spec(tools=[_calc_tool()]),
                            emit=lambda t, p: events.append((t, p))).run(AgentInput(input="add"))
    assert res.text == "The answer is 5."
    assert res.stopped_reason == "complete"
    assert any(t == EventType.TOOL_CALL for t, _ in events)
    assert res.tool_runs and res.tool_runs[0]["ok"] is True


async def test_handoff_sets_route(monkeypatch):
    monkeypatch.setattr(agent_mod, "complete",
                        _scripted(_result(tool_calls=[_tc("handoff", {"to_agent": "billing"})])))
    res = await AgentRunner(_spec()).run(AgentInput(input="x", allowed_routes=["billing", "tech"]))
    assert res.route == "billing" and res.stopped_reason == "handoff"


async def test_handoff_returns_response_r_and_forwards_input_n(monkeypatch):
    """supervisor-style {r, n}: handoff carries `to_agent` (n) + `response` (r). The router's reply (r) is
    its display text; the ORIGINAL request is forwarded to the chosen specialist (not the reply)."""
    monkeypatch.setattr(agent_mod, "complete", _scripted(
        _result(tool_calls=[_tc("handoff", {"to_agent": "billing",
                                             "response": "Connecting you to Billing."})])))
    res = await AgentRunner(_spec()).run(
        AgentInput(input="I was double charged", allowed_routes=["billing", "tech"]))
    assert res.route == "billing" and res.stopped_reason == "handoff"
    assert res.text == "Connecting you to Billing."   # r — the router's own reply (display)
    assert res.forward_text == "I was double charged"  # the specialist receives the request, not r


async def test_handoff_invalid_target_falls_through(monkeypatch):
    monkeypatch.setattr(agent_mod, "complete", _scripted(
        _result(tool_calls=[_tc("handoff", {"to_agent": "nope"})]),
        _result(text="handled directly"),
    ))
    res = await AgentRunner(_spec()).run(AgentInput(input="x", allowed_routes=["billing"]))
    assert res.route is None and res.text == "handled directly" and res.stopped_reason == "complete"


async def test_send_message_publishes(monkeypatch):
    monkeypatch.setattr(agent_mod, "complete", _scripted(
        _result(tool_calls=[_tc("send_message", {"to_agent": "peer", "content": "fyi"})]),
        _result(text="done"),
    ))
    bus = new_bus()
    bus.has_pending("peer")  # materialize inbox
    events = []
    res = await AgentRunner(_spec(name="A"), bus=bus,
                            emit=lambda t, p: events.append((t, p))).run(
        AgentInput(input="x", allowed_routes=["peer"]))
    assert res.text == "done"
    assert bus.drain("peer")[0].content == "fyi"
    assert any(t == EventType.AGENT_MESSAGE for t, _ in events)
    assert res.peer_messages and res.peer_messages[0].to_agent == "peer"


async def test_guardrail_max_steps(monkeypatch):
    async def always_tool(req, provider=None, fallback=None):
        return _result(tool_calls=[_tc("calculator", {"expression": "1+1"})], tokens=5)

    monkeypatch.setattr(agent_mod, "complete", always_tool)
    res = await AgentRunner(_spec(tools=[_calc_tool()], guardrails={"max_steps": 3})).run(
        AgentInput(input="loop"))
    assert res.stopped_reason == "max_steps" and res.steps == 3


async def test_guardrail_token_budget(monkeypatch):
    async def big_tool(req, provider=None, fallback=None):
        return _result(tool_calls=[_tc("calculator", {"expression": "1+1"})], tokens=5000)

    monkeypatch.setattr(agent_mod, "complete", big_tool)
    res = await AgentRunner(
        _spec(tools=[_calc_tool()], guardrails={"max_steps": 10, "max_tokens_total": 8000})
    ).run(AgentInput(input="x"))
    assert res.stopped_reason == "budget"


async def test_allow_list_blocks_unmapped_tool(monkeypatch):
    monkeypatch.setattr(agent_mod, "complete", _scripted(
        _result(tool_calls=[_tc("secret", {})]),
        _result(text="ok"),
    ))
    res = await AgentRunner(_spec(tools=[])).run(AgentInput(input="x"))
    assert res.text == "ok"
    assert res.tool_runs and res.tool_runs[0]["ok"] is False  # reported not-allowed, not executed


async def test_exception_returns_graceful(monkeypatch):
    async def boom(req, provider=None, fallback=None):
        raise RuntimeError("llm down")

    monkeypatch.setattr(agent_mod, "complete", boom)
    events = []
    res = await AgentRunner(_spec(), emit=lambda t, p: events.append((t, p))).run(AgentInput(input="x"))
    assert res.stopped_reason == "error"
    assert any(t == EventType.ERROR for t, _ in events)


async def test_structured_extraction(monkeypatch):
    monkeypatch.setattr(agent_mod, "complete", _scripted(
        _result(text='Report done.\n```json\n{"needs_more": false, "summary": "ok"}\n```')))
    res = await AgentRunner(_spec()).run(AgentInput(input="x"))
    assert res.structured.get("needs_more") is False
    assert res.structured.get("summary") == "ok"


def test_compose_system_prompt_includes_routes():
    p = compose_system_prompt(_spec(), ["billing", "tech"], "prior summary")
    assert "handoff" in p and "billing" in p and "prior summary" in p


async def test_summarize_history(monkeypatch):
    async def fake_complete(req, provider=None, fallback=None):
        return _result(text="A short summary.")

    monkeypatch.setattr(mem, "complete", fake_complete)
    out = await mem.summarize_history(
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}], prior="")
    assert out == "A short summary."


def test_window_history():
    h = [{"i": i} for i in range(20)]
    assert len(mem.window_history(h, 12)) == 12
    assert mem.window_history(h, 0) == h


def test_build_agent_spec(db):
    from app.models import Agent, Tool
    from app.runtime.agent_spec import build_agent_spec
    from app.runtime.tools.seed import seed_tools

    seed_tools(db)
    wf = db.query(Tool).filter_by(name="web_fetch").first()
    a = Agent(name="R", role="researcher", system_prompt="do it", provider="groq", model="m",
              guardrails={"max_steps": 5}, memory_config={"window": 8}, tools=[wf])
    db.add(a)
    db.commit()
    spec = build_agent_spec(a)
    assert spec.name == "R" and spec.tools[0].name == "web_fetch"
    assert spec.guardrails["max_steps"] == 5 and spec.memory_config["window"] == 8


def test_control_tools_decouple_handoff_and_send_message():
    from app.runtime.agent_spec import control_tool_specs

    # a genuine routing choice → handoff only
    assert {s["function"]["name"] for s in control_tool_specs(["a", "b"], peers=[])} == {"handoff"}
    # a peer to consult but no routing choice → send_message only (keeps control)
    assert {s["function"]["name"] for s in control_tool_specs([], peers=["x"])} == {"send_message"}
    # both available
    assert {s["function"]["name"] for s in control_tool_specs(["a", "b"], peers=["x"])} == {"handoff", "send_message"}
    # neither
    assert control_tool_specs([], peers=[]) == []
