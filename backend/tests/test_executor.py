"""LLD 06 — Graph Executor tests (the critical-path 'workflow execution'). Mock LLM."""
import asyncio

import pytest

import app.runtime.agent as agent_mod
from app.llm.types import LLMResult, ToolCall, Usage
from app.models import Agent, Run, Workflow
from app.models.event import RunEvent
from app.models.message import Message
from app.runtime.conditions import EvalContext, eval_condition
from app.runtime.executor import (
    Edge,
    Graph,
    GraphExecutor,
    GraphValidationError,
    Node,
    NodeOutcome,
    RunState,
)
from app.runtime.run_service import RunService
from app.seed import run_seed


# ── builders / mock LLM ───────────────────────────────────────────────
def _mk_agent(db, name, **kw):
    a = Agent(name=name, system_prompt=kw.get("prompt", ""), provider="groq", model="m",
              guardrails=kw.get("guardrails", {}), memory_config={})
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _mk_workflow(db, graph, name="wf", is_template=False):
    wf = Workflow(name=name, graph=graph, is_template=is_template)
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


def _mk_run(db, workflow_id, input_):
    run = Run(workflow_id=workflow_id, status="running", trigger="manual", input=input_)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _text(t, tokens=10):
    return LLMResult(text=t, usage=Usage(prompt_tokens=tokens, total_tokens=tokens))


def _handoff(to, tokens=5):
    return LLMResult(text="", usage=Usage(prompt_tokens=tokens, total_tokens=tokens),
                     tool_calls=[ToolCall(id="c1", name="handoff", arguments={"to_agent": to})])


def _script(monkeypatch, results):
    seq = list(results)

    async def fake(req, provider=None, fallback=None):
        return seq.pop(0)

    monkeypatch.setattr(agent_mod, "complete", fake)


def _always(monkeypatch, result):
    async def fake(req, provider=None, fallback=None):
        return result

    monkeypatch.setattr(agent_mod, "complete", fake)


class _DummySink:
    def emit(self, *a, **k):
        return {}


# ── run lifecycle ─────────────────────────────────────────────────────
async def test_linear_two_agent_run(session_factory, monkeypatch):
    with session_factory() as db:
        a1, a2 = _mk_agent(db, "A1"), _mk_agent(db, "A2")
        graph = {
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "n1", "type": "agent", "ref": a1.id},
                      {"id": "n2", "type": "agent", "ref": a2.id},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "n1"}, {"from": "n1", "to": "n2"},
                      {"from": "n2", "to": "end"}],
        }
        wf = _mk_workflow(db, graph)
        run = _mk_run(db, wf.id, {"text": "go"})
        run_id, gj = run.id, wf.graph

    _script(monkeypatch, [_text("from a1"), _text("from a2")])
    await GraphExecutor(session_factory).execute(run_id, gj)

    with session_factory() as db:
        run = db.get(Run, run_id)
        assert run.status == "completed"
        assert run.output["text"] == "from a2"
        assert run.total_tokens == 20
        evs = db.query(RunEvent).order_by(RunEvent.id).all()
        types = [e.type for e in evs]
        assert types[0] == "run_started" and types[-1] == "run_finished"
        assert "node_started" in types and "token_usage" in types and "node_finished" in types
        # per-run `seq` is persisted + monotonic (LLD 09 reconnect/replay relies on it)
        assert [e.seq for e in evs] == list(range(1, len(evs) + 1))


async def test_feedback_loop_hits_max_visits(session_factory, monkeypatch):
    with session_factory() as db:
        w = _mk_agent(db, "Writer")
        graph = {
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "writer", "type": "agent", "ref": w.id, "config": {"max_visits": 3}},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "writer"},
                      {"from": "writer", "to": "writer", "condition": "last.needs_more == True"},
                      {"from": "writer", "to": "end"}],
        }
        wf = _mk_workflow(db, graph)
        run = _mk_run(db, wf.id, {"text": "x"})
        run_id, gj = run.id, wf.graph

    _always(monkeypatch, _text('looping ```json\n{"needs_more": true}\n```'))
    await GraphExecutor(session_factory).execute(run_id, gj)

    with session_factory() as db:
        run = db.get(Run, run_id)
        assert run.status == "failed"
        assert "max_visits" in (run.error or "")


async def test_healthy_loop_exits_via_default(session_factory, monkeypatch):
    with session_factory() as db:
        w = _mk_agent(db, "Writer")
        graph = {
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "writer", "type": "agent", "ref": w.id, "config": {"max_visits": 5}},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "writer"},
                      {"from": "writer", "to": "writer", "condition": "last.needs_more == True"},
                      {"from": "writer", "to": "end"}],
        }
        wf = _mk_workflow(db, graph)
        run = _mk_run(db, wf.id, {"text": "x"})
        run_id, gj = run.id, wf.graph

    _script(monkeypatch, [
        _text('more ```json\n{"needs_more": true}\n```'),
        _text('done ```json\n{"needs_more": false}\n```'),
    ])
    await GraphExecutor(session_factory).execute(run_id, gj)

    with session_factory() as db:
        run = db.get(Run, run_id)
        assert run.status == "completed"
        assert "done" in run.output["text"]


async def test_handoff_routing_picks_successor(session_factory, monkeypatch):
    with session_factory() as db:
        router = _mk_agent(db, "Router")
        billing = _mk_agent(db, "Billing")
        tech = _mk_agent(db, "Tech")
        graph = {
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "router", "type": "agent", "ref": router.id},
                      {"id": "billing", "type": "agent", "ref": billing.id},
                      {"id": "tech", "type": "agent", "ref": tech.id},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "router"},
                      {"from": "router", "to": "billing"}, {"from": "router", "to": "tech"},
                      {"from": "billing", "to": "end"}, {"from": "tech", "to": "end"}],
        }
        wf = _mk_workflow(db, graph)
        run = _mk_run(db, wf.id, {"text": "billing issue"})
        run_id, gj = run.id, wf.graph

    _script(monkeypatch, [_handoff("Billing"), _text("billing resolved")])
    await GraphExecutor(session_factory).execute(run_id, gj)

    with session_factory() as db:
        run = db.get(Run, run_id)
        assert run.status == "completed"
        assert "billing resolved" in run.output["text"]


def test_pick_next_valid_route(session_factory):
    ex = GraphExecutor(session_factory)
    graph = Graph(
        nodes={"t": Node("t", "agent", 1), "b": Node("b", "agent", 2), "x": Node("x", "agent", 3)},
        out_edges={"t": [Edge("t", "b"), Edge("t", "x")]},
        start_id="t", agent_name_of={"t": "T", "b": "Billing", "x": "Tech"},
    )
    st = RunState(run_id=1, input={}, visits={"t": 1})
    nxt = ex._pick_next(graph.nodes["t"], graph, st, NodeOutcome("t", route="Tech"), _DummySink())
    assert nxt == "x"


def test_pick_next_invalid_route_falls_to_conditions(session_factory):
    ex = GraphExecutor(session_factory)
    graph = Graph(
        nodes={"t": Node("t", "agent", 1), "b": Node("b", "agent", 2), "e": Node("e", "end")},
        out_edges={"t": [Edge("t", "b", "last.x == 1"), Edge("t", "e")]},
        start_id="t", agent_name_of={"t": "Router", "b": "Billing"},
    )
    st = RunState(run_id=1, input={}, visits={"t": 1})
    out = NodeOutcome("t", route="Ghost", structured={"x": 1})  # invalid route → conditions
    assert ex._pick_next(graph.nodes["t"], graph, st, out, _DummySink()) == "b"


# ── condition evaluator ───────────────────────────────────────────────
def test_eval_condition():
    assert eval_condition("attempts < 3", EvalContext(attempts=2)) is True
    assert eval_condition("attempts < 3", EvalContext(attempts=5)) is False
    assert eval_condition('last.intent == "billing"', EvalContext(last={"intent": "billing"})) is True
    assert eval_condition('last.intent == "billing"', EvalContext(last={"intent": "tech"})) is False
    assert eval_condition("last.resolved == False", EvalContext(last={"resolved": False})) is True
    # lowercase JSON-style booleans — the shipped templates use these (regression: LLD06 review)
    assert eval_condition("last.needs_more == true", EvalContext(last={"needs_more": True})) is True
    assert eval_condition("last.resolved == false", EvalContext(last={"resolved": False})) is True
    assert eval_condition("last.needs_more == true", EvalContext(last={"needs_more": False})) is False
    assert eval_condition('input.kind in ["a", "b"]', EvalContext(input={"kind": "a"})) is True
    assert eval_condition(None, EvalContext()) is True
    assert eval_condition("else", EvalContext()) is True
    # safety / robustness → False
    assert eval_condition("__import__('os')", EvalContext()) is False
    assert eval_condition("len('x') > 0", EvalContext()) is False
    assert eval_condition("foo == 1", EvalContext()) is False  # unknown root
    assert eval_condition("last.missing == 1", EvalContext(last={})) is False  # None == 1


# ── caps / dead-end / cancel ──────────────────────────────────────────
async def test_global_max_run_steps_fails(session_factory, monkeypatch):
    with session_factory() as db:
        w = _mk_agent(db, "W")
        graph = {
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "w", "type": "agent", "ref": w.id, "config": {"max_visits": 1000}},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "w"},
                      {"from": "w", "to": "w", "condition": "last.loop == True"},
                      {"from": "w", "to": "end"}],
        }
        wf = _mk_workflow(db, graph)
        run = _mk_run(db, wf.id, {"text": "x"})
        run_id, gj = run.id, wf.graph

    _always(monkeypatch, _text('```json\n{"loop": true}\n```'))
    await GraphExecutor(session_factory, max_run_steps=5).execute(run_id, gj)

    with session_factory() as db:
        run = db.get(Run, run_id)
        assert run.status == "failed"
        assert "max_run_steps" in (run.error or "")


async def test_dead_end_completes_gracefully(session_factory, monkeypatch):
    with session_factory() as db:
        a = _mk_agent(db, "A")
        graph = {  # branching node, only-conditional edge, no default → dead-end when false
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "a", "type": "agent", "ref": a.id},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "a"},
                      {"from": "a", "to": "end", "condition": "last.go == True"}],
        }
        wf = _mk_workflow(db, graph)
        run = _mk_run(db, wf.id, {"text": "x"})
        run_id, gj = run.id, wf.graph

    _always(monkeypatch, _text('stop ```json\n{"go": false}\n```'))
    await GraphExecutor(session_factory).execute(run_id, gj)

    with session_factory() as db:
        run = db.get(Run, run_id)
        assert run.status == "completed"  # graceful, not failed
        assert "stop" in run.output["text"]


async def test_cancel_fails_run(session_factory, monkeypatch):
    with session_factory() as db:
        a = _mk_agent(db, "A")
        graph = {
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "a", "type": "agent", "ref": a.id},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "a"}, {"from": "a", "to": "end"}],
        }
        wf = _mk_workflow(db, graph)
        run = _mk_run(db, wf.id, {"text": "x"})
        run_id, gj = run.id, wf.graph

    _always(monkeypatch, _text("hi"))
    stop = asyncio.Event()
    stop.set()
    await GraphExecutor(session_factory).execute(run_id, gj, stop)

    with session_factory() as db:
        run = db.get(Run, run_id)
        assert run.status == "failed" and run.error == "cancelled"


async def test_cancel_during_final_dead_end_node_fails(session_factory, monkeypatch):
    """Regression (LLD06 review): a cancel landing while the FINAL node of a dead-end
    graph is in flight must FAIL the run, not silently COMPLETE."""
    stop = asyncio.Event()
    with session_factory() as db:
        a = _mk_agent(db, "A")
        graph = {  # dead-end: only-conditional edge evaluates False → _pick_next returns None
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "a", "type": "agent", "ref": a.id},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "a"},
                      {"from": "a", "to": "end", "condition": "last.go == true"}],
        }
        wf = _mk_workflow(db, graph)
        run = _mk_run(db, wf.id, {"text": "x"})
        run_id, gj = run.id, wf.graph

    async def fake(req, provider=None, fallback=None):
        stop.set()  # cancel lands while node 'a' is in flight (top-of-loop check already passed)
        return _text('stop ```json\n{"go": false}\n```')

    monkeypatch.setattr(agent_mod, "complete", fake)
    await GraphExecutor(session_factory).execute(run_id, gj, stop)

    with session_factory() as db:
        run = db.get(Run, run_id)
        assert run.status == "failed" and run.error == "cancelled"


# ── validation ────────────────────────────────────────────────────────
def test_validate_graph(session_factory):
    ex = GraphExecutor(session_factory)
    with session_factory() as db:
        a = _mk_agent(db, "A")
        good = {
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "a", "type": "agent", "ref": a.id},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "a"}, {"from": "a", "to": "end"}],
        }
        assert ex.validate_graph(good, db).agent_name_of["a"] == "A"

        with pytest.raises(GraphValidationError):  # multi-start
            ex.validate_graph({"nodes": [{"id": "s1", "type": "start"},
                                         {"id": "s2", "type": "start"},
                                         {"id": "end", "type": "end"}], "edges": []}, db)

        with pytest.raises(GraphValidationError):  # missing agent ref
            ex.validate_graph({"nodes": [{"id": "start", "type": "start"},
                                         {"id": "a", "type": "agent", "ref": 9999},
                                         {"id": "end", "type": "end"}],
                               "edges": [{"from": "start", "to": "a"}, {"from": "a", "to": "end"}]}, db)

        with pytest.raises(GraphValidationError):  # branching node with no default edge
            ex.validate_graph({"nodes": [{"id": "start", "type": "start"},
                                         {"id": "a", "type": "agent", "ref": a.id},
                                         {"id": "end", "type": "end"}],
                               "edges": [{"from": "start", "to": "a"},
                                         {"from": "a", "to": "end", "condition": "last.x == 1"}]}, db)

        with pytest.raises(GraphValidationError):  # unreachable node
            ex.validate_graph({"nodes": [{"id": "start", "type": "start"},
                                         {"id": "a", "type": "agent", "ref": a.id},
                                         {"id": "end", "type": "end"},
                                         {"id": "orphan", "type": "agent", "ref": a.id}],
                               "edges": [{"from": "start", "to": "a"}, {"from": "a", "to": "end"}]}, db)


# ── inter-agent message persistence ───────────────────────────────────
async def test_inter_agent_message_persisted(session_factory, monkeypatch):
    with session_factory() as db:
        a1, a2 = _mk_agent(db, "A1"), _mk_agent(db, "A2")
        graph = {
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "n1", "type": "agent", "ref": a1.id},
                      {"id": "n2", "type": "agent", "ref": a2.id},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "n1"}, {"from": "n1", "to": "n2"},
                      {"from": "n2", "to": "end"}],
        }
        wf = _mk_workflow(db, graph)
        run = _mk_run(db, wf.id, {"text": "x"})
        run_id, gj = run.id, wf.graph

    _script(monkeypatch, [
        LLMResult(text="", usage=Usage(total_tokens=5),
                  tool_calls=[ToolCall(id="c1", name="send_message",
                                       arguments={"to_agent": "A2", "content": "hello peer"})]),
        _text("n1 final"),
        _text("n2 final"),
    ])
    await GraphExecutor(session_factory).execute(run_id, gj)

    with session_factory() as db:
        msgs = db.query(Message).filter_by(run_id=run_id).all()
        assert any(m.to_agent == "A2" and "hello peer" in m.content for m in msgs)


# ── RunService (background task + solo workflow) ──────────────────────
async def test_run_service_start_run(session_factory, monkeypatch):
    with session_factory() as db:
        a = _mk_agent(db, "A")
        graph = {
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "a", "type": "agent", "ref": a.id},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "a"}, {"from": "a", "to": "end"}],
        }
        wf_id = _mk_workflow(db, graph).id

    _always(monkeypatch, _text("ok"))
    rs = RunService(session_factory)
    run_id = await rs.start_run(wf_id, {"text": "hi"})
    task = rs._tasks.get(run_id)
    if task:
        await task

    with session_factory() as db:
        run = db.get(Run, run_id)
        assert run.status == "completed" and run.output["text"] == "ok"


async def test_start_agent_run_creates_solo_workflow(session_factory, monkeypatch):
    with session_factory() as db:
        aid = _mk_agent(db, "Solo").id

    _always(monkeypatch, _text("done"))
    rs = RunService(session_factory)
    run_id = await rs.start_agent_run(aid, {"text": "run"})
    task = rs._tasks.get(run_id)
    if task:
        await task

    with session_factory() as db:
        run = db.get(Run, run_id)
        assert run.status == "completed" and run.output["text"] == "done"
        assert db.query(Workflow).filter_by(name=f"__solo_agent_{aid}").count() == 1


async def test_start_run_invalid_graph_no_run_row(session_factory):
    with session_factory() as db:
        bad = {"nodes": [{"id": "start", "type": "start"}], "edges": []}  # no end
        wf_id = _mk_workflow(db, bad).id

    rs = RunService(session_factory)
    with pytest.raises(GraphValidationError):
        await rs.start_run(wf_id, {"text": "x"})
    with session_factory() as db:
        assert db.query(Run).count() == 0  # no Run row created on validation failure


# ── content flow: linear agents produce content (no handoff placeholder) ──
async def test_content_flows_through_linear_pipeline(session_factory, monkeypatch):
    """A → B with one unconditional edge each: no handoff is offered, so each agent produces real
    output and B receives A's OUTPUT as its input (not a 'Handing off to B' placeholder)."""
    with session_factory() as db:
        a = _mk_agent(db, "A")
        b = _mk_agent(db, "B")
        graph = {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "a", "type": "agent", "ref": a.id},
                {"id": "b", "type": "agent", "ref": b.id},
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"from": "start", "to": "a"},
                {"from": "a", "to": "b"},
                {"from": "b", "to": "end"},
            ],
        }
        wf = _mk_workflow(db, graph)
        run = _mk_run(db, wf.id, {"text": "research topic X"})
        run_id = run.id

    seen: list[list[dict]] = []
    seq = iter([_text("RESEARCH FINDINGS"), _text("final brief")])

    async def fake(req, provider=None, fallback=None):
        seen.append(req.messages)
        return next(seq)

    monkeypatch.setattr(agent_mod, "complete", fake)
    await GraphExecutor(session_factory).execute(run_id, graph)

    assert len(seen) == 2  # A then B, one LLM call each (no handoff tool loop)
    a_input = " ".join(str(m.get("content", "")) for m in seen[0])
    b_input = " ".join(str(m.get("content", "")) for m in seen[1])
    assert "research topic X" in a_input  # A received the user input
    assert "RESEARCH FINDINGS" in b_input  # B received A's OUTPUT — content flowed
    assert "Handing off" not in b_input  # ...and NOT a placeholder


async def test_handoff_carries_context_on_a_real_branch(session_factory, monkeypatch):
    """Router has 2 unconditional agent routes → handoff IS offered. When it routes with no text,
    the original issue is carried to the chosen specialist (not a 'Handing off' placeholder)."""
    with session_factory() as db:
        router = _mk_agent(db, "Router")
        billing = _mk_agent(db, "Billing")
        tech = _mk_agent(db, "Tech")
        graph = {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "t", "type": "agent", "ref": router.id},
                {"id": "bill", "type": "agent", "ref": billing.id},
                {"id": "tech", "type": "agent", "ref": tech.id},
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"from": "start", "to": "t"},
                {"from": "t", "to": "bill"},
                {"from": "t", "to": "tech"},
                {"from": "bill", "to": "end"},
                {"from": "tech", "to": "end"},
            ],
        }
        wf = _mk_workflow(db, graph)
        run = _mk_run(db, wf.id, {"text": "I was double charged"})
        run_id = run.id

    seen: list[list[dict]] = []
    seq = iter([_handoff("Billing"), _text("billing reply")])  # Router routes with NO text

    async def fake(req, provider=None, fallback=None):
        seen.append(req.messages)
        return next(seq)

    monkeypatch.setattr(agent_mod, "complete", fake)
    await GraphExecutor(session_factory).execute(run_id, graph)

    billing_input = " ".join(str(m.get("content", "")) for m in seen[1])
    assert "double charged" in billing_input  # the real issue was carried to Billing
    assert "Handing off" not in billing_input


# ── a created/attached tool is offered to the LLM and executed in a run ───
async def test_attached_tool_is_called_in_a_run(session_factory, monkeypatch):
    """A tool ATTACHED to an agent (exactly as the API's create-tool + set-tools flow does) is
    offered to the LLM and executed during a run — same path as a seeded tool. (Deterministic;
    proves dynamically-created tools get called without needing live LLM tokens.)"""
    from app.models import Tool
    from app.runtime.tools.seed import seed_tools

    with session_factory() as db:
        seed_tools(db)  # provides the 'calculator' builtin
        calc = db.query(Tool).filter_by(name="calculator").first()
        agent = _mk_agent(db, "Analyst")
        agent.tools = [calc]  # attach the tool to the agent (as PUT /agents/{id}/tools does)
        db.commit()
        graph = {
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "a", "type": "agent", "ref": agent.id},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "a"}, {"from": "a", "to": "end"}],
        }
        wf = _mk_workflow(db, graph)
        run_id = _mk_run(db, wf.id, {"text": "add 2 and 3"}).id

    _script(monkeypatch, [
        LLMResult(text="", usage=Usage(total_tokens=5),
                  tool_calls=[ToolCall(id="c1", name="calculator", arguments={"expression": "2+3"})]),
        _text("The total is 5."),
    ])
    await GraphExecutor(session_factory).execute(run_id, graph)

    with session_factory() as db:
        evs = db.query(RunEvent).filter_by(run_id=run_id).all()
        called = [e.payload.get("tool") for e in evs if e.type == "tool_call"]
        assert "calculator" in called  # the attached tool was actually invoked


# ── general supervisor/router: any query → the right specialist ───────────
async def test_supervisor_runtime_prompt_includes_subagent_roster(session_factory, monkeypatch):
    """At RUNTIME the workflow's sub-agents + their capabilities (roles) are injected into the
    Supervisor's system prompt, so its routing decision is informed — not a guess from bare names.
    Captures the exact system prompt the LLM receives on the Supervisor's turn."""
    with session_factory() as db:
        run_seed(db)
        wf = db.query(Workflow).filter_by(name="Support Router", is_template=True).first()
        run_id = _mk_run(db, wf.id, {"text": "I was charged twice"}).id
        graph = wf.graph

    seen: list[list[dict]] = []
    seq = iter([_handoff("Billing"), _text('done ```json\n{"resolved": true}\n```')])

    async def fake(req, provider=None, fallback=None):
        seen.append(req.messages)
        return next(seq)

    monkeypatch.setattr(agent_mod, "complete", fake)
    await GraphExecutor(session_factory).execute(run_id, graph)

    sup_system = seen[0][0]["content"]  # Supervisor's turn = first LLM call; messages[0] = system prompt
    # the roster (the candidate next-agents `n`)…
    assert "Billing" in sup_system and "Tech" in sup_system and "Sales" in sup_system
    # …WITH each one's capability (its role) so routing is informed…
    assert "Billing support" in sup_system and "Technical support" in sup_system
    # …and it's told to route via the handoff tool.
    assert "handoff" in sup_system


async def test_supervisor_routes_each_query_to_its_specialist(session_factory, monkeypatch):
    """The seeded Support Router's Supervisor routes by `handoff`: a billing query → Billing, a tech
    query → Tech, a sales query → Sales — and ONLY the chosen specialist runs (routing is exclusive)."""
    with session_factory() as db:
        run_seed(db)
        wf = db.query(Workflow).filter_by(name="Support Router", is_template=True).first()
        wf_id, graph = wf.id, wf.graph

    cases = [
        ("Billing", "billing", "I was charged twice this month"),
        ("Tech", "tech", "the API returns 502 errors after the last deploy"),
        ("Sales", "sales", "what's included in the Enterprise plan?"),
    ]
    for agent_name, node_id, query in cases:
        with session_factory() as db:
            run_id = _mk_run(db, wf_id, {"text": query}).id

        # Supervisor hands off to the matching specialist; the specialist resolves → run ends.
        _script(monkeypatch, [
            _handoff(agent_name),
            _text(f'{agent_name} handled it.\n```json\n{{"resolved": true}}\n```'),
        ])
        await GraphExecutor(session_factory).execute(run_id, graph)

        with session_factory() as db:
            run = db.get(Run, run_id)
            assert run.status == "completed", f"{agent_name}: {run.error}"
            evs = db.query(RunEvent).filter_by(run_id=run_id).order_by(RunEvent.seq.asc()).all()
            started = [e.payload.get("node_id") for e in evs if e.type == "node_started"]
            assert "supervisor" in started and node_id in started  # supervisor ran, then the specialist
            others = {"billing", "tech", "sales"} - {node_id}
            assert not (set(started) & others), f"{agent_name}: other specialists ran: {started}"
            sup_finish = next(e for e in evs if e.type == "node_finished"
                              and e.payload.get("node_id") == "supervisor")
            assert sup_finish.payload.get("route") == agent_name  # the recorded routing decision
