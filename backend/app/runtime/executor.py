"""Graph Executor (LLD 06) — sequential single-cursor walk (v1).

Drives a run over the workflow graph: create/advance a cursor, run an AgentRunner per
agent node, decide the next node from the agent's handoff route OR edge conditions
(feedback loops included), persist Run/Message/RunEvent, aggregate token/cost, stream
events. Caps enforced on EVERY path → breach = FAILED (never a silent "completed").
The only component that touches the DB during a run (the Agent is DB-free, LLD 05).
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.models import Agent, Run, Tool
from app.models.enums import EventType, RunStatus
from app.models.message import Message
from app.runtime.agent import AgentInput, AgentRunner
from app.runtime.agent_spec import build_agent_spec
from app.runtime.bus import new_bus
from app.runtime.conditions import EvalContext, eval_condition
from app.runtime.events import EventSink
from app.runtime.tools.base import ToolContext
from app.runtime.tools.registry import execute_tool_call

log = logging.getLogger("runtime.executor")


class GraphValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


class ExecutorAbort(Exception):
    """A cap breach / missing ref → the run FAILS (not a graceful completion)."""


# ── graph value objects ───────────────────────────────────────────────
@dataclass(frozen=True)
class Node:
    id: str
    type: str  # "start" | "agent" | "tool" | "router" | "end"
    ref: int | None = None  # agent_id (agent) / tool_id (tool)
    config: dict = field(default_factory=dict)  # {"max_visits": int, ...}


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    condition: str | None = None  # None/""/"else" = default edge


@dataclass
class Graph:
    nodes: dict[str, Node]
    out_edges: dict[str, list[Edge]]  # insertion order preserved (condition precedence)
    start_id: str | None
    agent_name_of: dict[str, str | None] = field(default_factory=dict)  # node_id -> agent name
    agent_role_of: dict[str, str | None] = field(default_factory=dict)  # node_id -> agent role (route desc)

    @classmethod
    def parse(cls, g: dict) -> "Graph":
        nodes = {
            n["id"]: Node(id=n["id"], type=n["type"], ref=n.get("ref"), config=n.get("config") or {})
            for n in g.get("nodes", [])
        }
        out_edges: dict[str, list[Edge]] = {}
        for e in g.get("edges", []):
            out_edges.setdefault(e["from"], []).append(
                Edge(src=e["from"], dst=e["to"], condition=e.get("condition"))
            )
        starts = [n.id for n in nodes.values() if n.type == "start"]
        return cls(nodes=nodes, out_edges=out_edges, start_id=starts[0] if starts else None)


@dataclass
class NodeOutcome:
    node_id: str
    text: str = ""  # this node's output (for a router: the router's reply `r`, shown in the UI)
    structured: dict = field(default_factory=dict)
    route: str | None = None
    forward_text: str | None = None  # what the NEXT node receives (None → `text`); a router forwards
    #                                  the original request here while `text` holds its reply
    agent_name: str | None = None
    usage_tokens: int = 0
    cost: float = 0.0
    stopped_reason: str = "complete"

    @property
    def next_input(self) -> str:
        return self.forward_text if self.forward_text is not None else self.text


@dataclass
class RunState:
    run_id: int
    input: dict
    last: NodeOutcome | None = None
    outcomes: dict[str, NodeOutcome] = field(default_factory=dict)
    visits: dict[str, int] = field(default_factory=dict)  # node_id -> times executed (loop cap)
    steps: int = 0
    total_tokens: int = 0
    est_cost: float = 0.0
    output: dict | None = None


# ── routing primitives (shared by the executor AND the conversational per-turn router) ──────
# ONE definition of "what is a router", so a workflow RUN and a workflow CHAT can never disagree.
def handoff_routes(node: Node, graph: Graph) -> list[str]:
    """Agents reachable from `node` via UNCONDITIONAL out-edges — the genuine handoff choices.
    Handoff is a real decision only with >= 2 of them; with one (or zero), the agent just produces
    output and the default/condition edges route it (so content flows downstream, not a placeholder)."""
    routes = [graph.agent_name_of[e.dst] for e in graph.out_edges.get(node.id, [])
              if e.condition in (None, "", "else") and graph.agent_name_of.get(e.dst)]
    return routes if len(routes) >= 2 else []


def route_descriptions(node: Node, graph: Graph) -> dict[str, str]:
    """Map each handoff target's name → its role (one-line desc), so a router chooses from INFORMED
    descriptions, not bare names (compose_system_prompt lists these)."""
    out: dict[str, str] = {}
    for e in graph.out_edges.get(node.id, []):
        if e.condition in (None, "", "else"):
            name = graph.agent_name_of.get(e.dst)
            if name:
                out[name] = (graph.agent_role_of.get(e.dst) or "").strip()
    return out


def find_router(graph: Graph) -> tuple[Node, list[str], dict[str, str]] | None:
    """The conversational router for a graph: the first agent node (by stable node-id order) that has
    >= 2 unconditional agent out-edges (the SAME per-node rule the executor uses). Returns
    (node, routes, descriptions) or None when no node qualifies (→ caller falls back to single-agent).
    v1 routes a chat through ONE router; with multiple router-shaped nodes the first deterministically
    wins. Requires a RESOLVED graph (agent_name_of populated) — see GraphExecutor._parse_and_resolve."""
    for nid in sorted(graph.nodes):
        node = graph.nodes[nid]
        if node.type == "agent":
            routes = handoff_routes(node, graph)
            if routes:
                return node, routes, route_descriptions(node, graph)
    return None


class GraphExecutor:
    def __init__(self, session_factory, hub=None, *, max_run_steps: int = 50,
                 default_max_visits: int = 8, run_timeout_s: int = 300):
        self.session_factory = session_factory
        self.hub = hub
        self.max_run_steps = max_run_steps
        self.default_max_visits = default_max_visits
        self.run_timeout_s = run_timeout_s

    # ── validation (workflow save → API 400, and at run start) ─────────
    def validate_graph(self, gj: dict, db) -> Graph:
        errs: list[str] = []
        nodes = gj.get("nodes", [])
        edges = gj.get("edges", [])
        ids = [n["id"] for n in nodes]
        if len(ids) != len(set(ids)):
            errs.append("duplicate node ids")
        starts = [n for n in nodes if n["type"] == "start"]
        ends = [n for n in nodes if n["type"] == "end"]
        if len(starts) != 1:
            errs.append(f"need exactly 1 start, got {len(starts)}")
        if not ends:
            errs.append("need >= 1 end")
        idset = set(ids)
        for e in edges:
            if e["from"] not in idset or e["to"] not in idset:
                errs.append(f"edge {e['from']}->{e['to']} references unknown node")
        for n in nodes:  # refs must resolve to live rows
            if n["type"] == "agent" and not db.get(Agent, n.get("ref")):
                errs.append(f"{n['id']}: agent ref missing")
            if n["type"] == "tool" and not db.get(Tool, n.get("ref")):
                errs.append(f"{n['id']}: tool ref missing")
        if len(starts) == 1:  # reachability + end reachable (BFS)
            adj: dict[str, list[str]] = {}
            for e in edges:
                adj.setdefault(e["from"], []).append(e["to"])
            seen: set[str] = set()
            q = [starts[0]["id"]]
            while q:
                x = q.pop()
                if x in seen:
                    continue
                seen.add(x)
                q += [d for d in adj.get(x, []) if d not in seen]
            if idset - seen:
                errs.append(f"unreachable nodes: {sorted(idset - seen)}")
            if not (seen & {n["id"] for n in ends}):
                errs.append("no end reachable from start")
        for n in nodes:  # a branching node MUST have a default edge (no dead-ends)
            if n["type"] in ("agent", "router"):
                oe = [e for e in edges if e["from"] == n["id"]]
                if oe and not any(e.get("condition") in (None, "", "else") for e in oe):
                    errs.append(f"{n['id']}: all out-edges conditional — add a default ('else') edge")
        if errs:
            raise GraphValidationError(errs)
        return self._resolve_names(Graph.parse(gj), db)

    def _resolve_names(self, graph: Graph, db) -> Graph:
        for n in graph.nodes.values():
            if n.type == "agent":
                a = db.get(Agent, n.ref)
                graph.agent_name_of[n.id] = a.name if a else None
                graph.agent_role_of[n.id] = a.role if a else None  # one-line desc → informs the router
        return graph

    def _parse_and_resolve(self, gj: dict) -> Graph:
        with self.session_factory() as db:
            return self._resolve_names(Graph.parse(gj), db)

    # ── run entry ──────────────────────────────────────────────────────
    async def execute(self, run_id: int, graph_json: dict, stop_event: asyncio.Event | None = None) -> None:
        t_start = time.perf_counter()
        bus = new_bus()
        sink = EventSink(run_id, self.session_factory, hub=self.hub)
        with self.session_factory() as db:
            run = db.get(Run, run_id)
            run_input = run.input or {}
            workflow_id = run.workflow_id
            trigger = run.trigger
        st = RunState(run_id=run_id, input=run_input)
        try:
            graph = self._parse_and_resolve(graph_json)
            sink.emit(EventType.RUN_STARTED, {
                "workflow_id": workflow_id, "trigger": trigger,
                "input_preview": _input_text(run_input)[:200], "node_count": len(graph.nodes),
            })
            await asyncio.wait_for(
                self._run_loop(graph, bus, st, sink, stop_event), timeout=self.run_timeout_s
            )
            self._finalize(run_id, RunStatus.COMPLETED, sink, t_start, output=st.output)
        except ExecutorAbort as e:
            self._finalize(run_id, RunStatus.FAILED, sink, t_start, error=str(e))
        except (asyncio.CancelledError, TimeoutError) as e:
            reason = "cancelled" if isinstance(e, asyncio.CancelledError) else "run timeout"
            sink.emit(EventType.ERROR, {"scope": "run", "error": reason})
            self._finalize(run_id, RunStatus.FAILED, sink, t_start, error=reason)
        except Exception as e:
            sink.emit(EventType.ERROR, {"scope": "run", "error": f"{type(e).__name__}: {e}"})
            self._finalize(run_id, RunStatus.FAILED, sink, t_start, error=f"{type(e).__name__}: {e}")

    def _enforce_caps(self, st, cur, node, sink) -> None:
        if st.steps > self.max_run_steps:  # GLOBAL cap (every iteration)
            sink.emit(EventType.ERROR, {"scope": "run", "error": "max_run_steps exceeded"})
            raise ExecutorAbort("max_run_steps exceeded")
        if st.visits[cur] > node.config.get("max_visits", self.default_max_visits):  # PER-NODE cap
            sink.emit(EventType.ERROR, {"scope": "node", "node_id": cur, "error": "max_visits exceeded"})
            raise ExecutorAbort(f"max_visits exceeded at {cur}")

    # ── the run loop (sequential, every-path-bounded) ──────────────────
    async def _run_loop(self, graph, bus, st, sink, stop_event) -> None:
        if graph.start_id is None:
            raise ExecutorAbort("no start node")
        cur = graph.start_id
        while True:
            st.steps += 1
            node = graph.nodes[cur]
            st.visits[cur] = st.visits.get(cur, 0) + 1
            self._enforce_caps(st, cur, node, sink)  # global + per-node caps → ExecutorAbort on breach
            if stop_event and stop_event.is_set():  # cooperative cancel (between nodes)
                raise asyncio.CancelledError()

            t0 = time.perf_counter()
            sink.emit(EventType.NODE_STARTED, {
                "node_id": cur, "node_type": node.type, "agent_name": graph.agent_name_of.get(cur),
                "visit": st.visits[cur], "step": st.steps,
            })
            outcome = await self._execute_node(node, graph, bus, st, sink)
            st.last, st.outcomes[cur] = outcome, outcome
            st.total_tokens += outcome.usage_tokens
            st.est_cost += outcome.cost
            sink.emit(EventType.NODE_FINISHED, {
                "node_id": cur, "node_type": node.type, "agent_name": outcome.agent_name,
                "stopped_reason": outcome.stopped_reason, "route": outcome.route,
                "tokens": outcome.usage_tokens, "est_cost_usd": round(outcome.cost, 6),
                "duration_ms": int((time.perf_counter() - t0) * 1000), "text_preview": outcome.text[:200],
            })

            if stop_event and stop_event.is_set():  # cancel landed during the node → FAIL on every terminal path
                raise asyncio.CancelledError()
            if node.type == "end":
                st.output = {"text": outcome.text, **outcome.structured}
                return
            nxt = self._pick_next(node, graph, st, outcome, sink)
            if nxt is None:  # DEAD-END policy → graceful completion
                sink.emit(EventType.NODE_FINISHED, {"node_id": cur, "note": "dead_end_terminal"})
                st.output = {"text": outcome.text, **outcome.structured}
                return
            cur = nxt

    async def _execute_node(self, node, graph, bus, st, sink) -> NodeOutcome:
        if node.type == "start":
            return NodeOutcome(node_id=node.id, text=_input_text(st.input),
                               structured=dict(st.input) if isinstance(st.input, dict) else {})
        if node.type in ("end", "router"):  # pass the last output through
            prev = st.last
            return NodeOutcome(node_id=node.id, text=(prev.text if prev else ""),
                               structured=(prev.structured if prev else {}))
        if node.type == "agent":
            return await self._run_agent_node(node, graph, bus, st, sink)
        if node.type == "tool":
            return await self._run_tool_node(node, st, sink)
        return NodeOutcome(node_id=node.id)

    async def _run_agent_node(self, node, graph, bus, st, sink) -> NodeOutcome:
        with self.session_factory() as db:
            agent_row = db.get(Agent, node.ref)
            if agent_row is None:
                sink.emit(EventType.ERROR, {"scope": "node", "node_id": node.id,
                                            "error": f"agent ref {node.ref} missing"})
                raise ExecutorAbort(f"agent ref missing at {node.id}")
            spec = build_agent_spec(agent_row)

        upstream = st.last.next_input if st.last else _input_text(st.input)
        inbox = bus.drain(spec.name)
        allowed = self._handoff_routes(node, graph)
        # `send_message` is offered ONLY to an agent whose instructions actually use it (e.g. the
        # Collaborative Brief's Coordinator). Otherwise a pipeline/router agent can misuse it — e.g.
        # treat a downstream agent as a chat partner and loop until it exhausts max_visits.
        wants_peers = "send_message" in (spec.system_prompt or "").lower()
        peers = self._peer_agents(node, graph) if wants_peers else []
        route_desc = self._route_descriptions(node, graph) if allowed else {}

        def node_emit(etype, payload):
            return sink.emit(etype, payload, node_id=node.id)

        runner = AgentRunner(spec, bus=bus, emit=node_emit)
        result = await runner.run(AgentInput(
            input=upstream, history=[], inbox=inbox, allowed_routes=allowed,
            route_descriptions=route_desc, peers=peers,
            ctx=ToolContext(run_id=st.run_id, conversation_id=str(st.run_id), agent_name=spec.name,
                            chat_id=_chat_id(st.input)),
        ))

        self._persist_message(st.run_id, from_agent=spec.name, to_agent="", content=result.text)
        for bm in result.peer_messages:  # inter-agent messages → Message rows (audit)
            self._persist_message(st.run_id, from_agent=bm.from_agent, to_agent=bm.to_agent, content=bm.content)

        sink.emit(EventType.TOKEN_USAGE, {
            "node_id": node.id, "agent_name": spec.name, "model": spec.model, "provider": spec.provider,
            "prompt_tokens": result.usage.prompt_tokens, "completion_tokens": result.usage.completion_tokens,
            "total_tokens": result.usage.total_tokens, "est_cost_usd": result.usage.est_cost_usd,
        })
        return NodeOutcome(
            node_id=node.id, text=result.text, structured=result.structured, route=result.route,
            forward_text=result.forward_text, agent_name=spec.name,
            usage_tokens=result.usage.total_tokens, cost=result.usage.est_cost_usd,
            stopped_reason=result.stopped_reason,
        )

    async def _run_tool_node(self, node, st, sink) -> NodeOutcome:
        with self.session_factory() as db:
            tool = db.get(Tool, node.ref)
        if tool is None:
            sink.emit(EventType.ERROR, {"scope": "node", "node_id": node.id,
                                        "error": f"tool ref {node.ref} missing"})
            raise ExecutorAbort(f"tool ref missing at {node.id}")
        args = st.input if isinstance(st.input, dict) else {}
        result = await execute_tool_call(
            tool, args, ToolContext(run_id=st.run_id, conversation_id=str(st.run_id),
                                    chat_id=_chat_id(st.input))
        )
        sink.emit(EventType.TOOL_CALL, {"node_id": node.id, "tool": tool.name, "ok": result.ok,
                                        "latency_ms": result.latency_ms, "error": result.error})
        return NodeOutcome(node_id=node.id, text=str(result.output if result.ok else result.error),
                           structured=result.output if isinstance(result.output, dict) else {})

    # ── routing: handoff route → conditions → default ─────────────────
    def _pick_next(self, node, graph, st, outcome, sink) -> str | None:
        edges = graph.out_edges.get(node.id, [])
        if outcome and outcome.route:  # (1) explicit LLM handoff wins if it names a real out-edge
            for e in edges:
                if graph.agent_name_of.get(e.dst) == outcome.route:
                    return e.dst
            sink.emit(EventType.ERROR, {"scope": "node", "node_id": node.id,
                                        "error": f"handoff '{outcome.route}' is not an out-edge; using conditions"})
        ctx = EvalContext(  # (2) edge conditions in declared order; first True wins
            last=_ctx_last(outcome),
            input=st.input if isinstance(st.input, dict) else {},
            attempts=st.visits.get(node.id, 0),
        )
        default = None
        for e in edges:
            if e.condition in (None, "", "else"):
                default = default or e
                continue
            if eval_condition(e.condition, ctx):
                return e.dst
        return default.dst if default else None  # None → dead-end → graceful completion

    def _handoff_routes(self, node, graph) -> list[str]:
        # per-node handoff targets (the executor walks node-by-node) — see module-level handoff_routes
        return handoff_routes(node, graph)

    def _route_descriptions(self, node, graph) -> dict[str, str]:
        return route_descriptions(node, graph)

    def _peer_agents(self, node, graph) -> list[str]:
        """Other agents this node may `send_message` (consult, keeping control); the recipient drains
        its inbox when it next runs. Whether the tool is actually OFFERED is gated by the caller (only
        agents whose instructions use send_message), so pipelines and routers stay clean."""
        me = graph.agent_name_of.get(node.id)
        return sorted({n for n in graph.agent_name_of.values() if n and n != me})

    # ── persistence ────────────────────────────────────────────────────
    def _persist_message(self, run_id, *, from_agent, to_agent, content, channel="internal") -> None:
        try:
            with self.session_factory() as db:
                db.add(Message(run_id=run_id, conversation_id=str(run_id), from_agent=from_agent,
                               to_agent=to_agent, channel=channel, role="assistant", content=content))
                db.commit()
        except Exception:
            log.warning("persist message failed (run=%s from=%s) — swallowed", run_id, from_agent)

    def _finalize(self, run_id, status, sink, t_start, *, output=None, error=None) -> None:
        duration_ms = int((time.perf_counter() - t_start) * 1000)
        try:
            with self.session_factory() as db:
                run = db.get(Run, run_id)
                if run:
                    run.status = str(status)
                    run.output = output
                    run.error = error
                    run.total_tokens = sink.total_tokens
                    run.est_cost = round(sink.est_cost, 6)
                    run.ended_at = datetime.now(UTC)
                    db.commit()
        except Exception:
            log.exception("failed to finalize run %s", run_id)
        log.info("run %s %s (%d tokens, %dms)", run_id, status, sink.total_tokens, duration_ms)
        sink.emit(EventType.RUN_FINISHED, {
            "status": str(status), "total_tokens": sink.total_tokens, "est_cost": round(sink.est_cost, 6),
            "duration_ms": duration_ms,
            "output_preview": _input_text(output)[:200] if output else "", "error": error,
        })


# ── helpers ────────────────────────────────────────────────────────────
def _ctx_last(outcome: NodeOutcome | None) -> dict:
    if outcome is None:
        return {}
    base = {"text": outcome.text, "route": outcome.route, "stopped_reason": outcome.stopped_reason}
    base.update(outcome.structured or {})
    return base


def _input_text(inp) -> str:
    if isinstance(inp, dict):
        return inp.get("text") or inp.get("input") or json.dumps(inp)
    return str(inp or "")


def _chat_id(inp) -> str | None:
    # lets a workflow run target a chat (e.g. the Notifier agent's send_telegram) via run input
    return inp.get("chat_id") if isinstance(inp, dict) else None
