"""Conversational per-turn routing (the stretch on LLD 07).

A workflow-bound Conversation routes EACH turn through the workflow's ROUTER — the agent with
>= 2 unconditional agent out-edges (e.g. IKEA's "Supervisor"/Riya). The router reads the new
message + who is currently handling the chat (the sticky `curr_agent`) and hands off (supervisor-style
{n, r}) to the best specialist; that specialist answers using the full conversation history. The
chosen specialist becomes the conversation's `curr_agent`, so the next turn stays with them unless
the topic changes. Exactly two LLM calls per routed turn (router → one specialist); the specialist
runs as a leaf (allowed_routes=[]) so it can never re-hand-off — no chaining, no graph walk.

The router is given a LEAN view (the new message + sticky hint + summary, history=[]) so prior
specialist answers don't bias it into "I already answered"; the specialist gets the full window.

the {n, r} + sticky-current-agent pattern is a standard supervisor-routing approach.
This module is DB-light — it builds specs + resolves the graph; the caller
(channels.dispatcher) owns history loading and message/conversation persistence (avoids a cycle).
"""
import logging
from dataclasses import dataclass, field

from app.models import Agent, Workflow
from app.models.enums import EventType
from app.runtime.agent import AgentInput, AgentRunner
from app.runtime.agent_spec import build_agent_spec
from app.runtime.executor import GraphExecutor, find_router
from app.runtime.tools.base import ToolContext

log = logging.getLogger("runtime.conversation_router")


@dataclass
class Routing:
    """A resolved router for a workflow graph (the supervisor + its specialist roster)."""
    graph: object  # executor.Graph (resolved: agent_name_of/agent_role_of populated)
    router_node: object  # executor.Node — the router (its ref is the router agent id)
    routes: list[str]  # specialist names the router may hand off to
    descriptions: dict[str, str]  # specialist name -> role (injected into the router's prompt)


@dataclass
class RoutedTurn:
    reply: str  # the user-visible answer (the specialist's, or the router's own if it answered)
    active_agent: str  # who produced the reply → the new curr_agent (if advance_curr_agent)
    routed_from: str | None = None  # the prior handler when it changed this turn (for the UI chip)
    total_tokens: int = 0  # router + specialist
    tools: list[dict] = field(default_factory=list)  # the SPECIALIST's tool calls (for the chip / audit)
    stopped_reason: str = "complete"  # the call that produced the visible reply
    advance_curr_agent: bool = True  # False on a degenerate router self-answer / specialist error → keep prior


def resolve_routing(session_factory, workflow_id: int | None) -> Routing | None:
    """Resolve a workflow's router, or None when the workflow is gone or has no router (→ the caller
    falls back to single-agent 1:1). The graph is RESOLVED (agent names filled) so find_router works."""
    if workflow_id is None:
        return None
    with session_factory() as db:
        wf = db.get(Workflow, workflow_id)
        graph_json = wf.graph if wf else None
    if graph_json is None:  # workflow deleted mid-chat (SQLite FK is off, so guard at runtime)
        return None
    graph = GraphExecutor(session_factory)._parse_and_resolve(graph_json)
    found = find_router(graph)
    if found is None:  # not a router workflow (linear, or edited down to < 2 routes)
        return None
    node, routes, descriptions = found
    return Routing(graph=graph, router_node=node, routes=routes, descriptions=descriptions)


def workflow_for_router_agent(session_factory, agent_id: int, tenant_id: int | None) -> int | None:
    """The first (by id) non-template workflow IN THIS TENANT whose router node's agent == agent_id.
    Used to auto-bind a channel chat to its router workflow (e.g. IKEA's Supervisor → Abandoned-Cart
    Recovery). Matches by agent id (not name), so a same-named router in another tenant can't satisfy
    it. Returns None when the agent isn't the router of any workflow → plain 1:1."""
    with session_factory() as db:
        candidates = [(w.id, w.graph) for w in db.query(Workflow)
                      .filter_by(tenant_id=tenant_id, is_template=False)
                      .order_by(Workflow.id.asc()).all()]
    for wid, graph_json in candidates:
        graph = GraphExecutor(session_factory)._parse_and_resolve(graph_json)
        found = find_router(graph)
        if found and found[0].ref == agent_id:
            return wid
    return None


def _node_for_name(graph, name: str):
    """The graph node whose resolved agent name == `name` (reverse of agent_name_of)."""
    for nid, nm in graph.agent_name_of.items():
        if nm == name:
            return graph.nodes.get(nid)
    return None


def _spec_for_node(session_factory, node):
    if node is None or node.ref is None:
        return None
    with session_factory() as db:
        agent = db.get(Agent, node.ref)
        return build_agent_spec(agent) if agent else None


async def run_routed_turn(session_factory, routing: Routing, *, text: str, history: list[dict],
                          summary: str, curr_agent: str | None, chat_id: str | None,
                          conv_id: int) -> RoutedTurn:
    """One conversational turn over a router workflow: router decides {n, r}, then specialist n answers
    the ORIGINAL message. Returns a RoutedTurn the caller persists. Never raises to the caller —
    AgentRunner returns a valid result on any internal error, and missing specialists degrade softly."""
    router_spec = _spec_for_node(session_factory, routing.router_node)
    if router_spec is None:  # router agent deleted — caller's agent_id guards usually catch this first
        return RoutedTurn(reply="Sorry — this assistant is unavailable right now.", active_agent="",
                          advance_curr_agent=False, stopped_reason="error")

    ctx = ToolContext(conversation_id=str(conv_id), chat_id=chat_id, agent_name=router_spec.name)
    sticky = curr_agent if curr_agent in routing.routes else None  # drop a stale/removed handler

    # (1) ROUTER — lean view: the new message + sticky hint + summary (history=[] avoids the router
    # reading prior specialist prose as its own answers and refusing to route). bus=None → no peers.
    router_res = await AgentRunner(router_spec, bus=None).run(AgentInput(
        input=text, history=[], summary=summary, allowed_routes=routing.routes,
        route_descriptions=routing.descriptions, current_handler=sticky, ctx=ctx))
    total = router_res.usage.total_tokens

    if router_res.route and router_res.route in routing.routes:
        # (2) SPECIALIST — gets the ORIGINAL message (router_res.forward_text) + the full window, and
        # runs as a leaf (allowed_routes=[]) so it answers, never re-routes.
        specialist_spec = _spec_for_node(session_factory, _node_for_name(routing.graph, router_res.route))
        if specialist_spec is None:  # removed between resolve and run → soft, don't pin curr_agent
            return RoutedTurn(reply="Sorry — I couldn't reach that specialist just now.",
                              active_agent=router_spec.name, total_tokens=total,
                              advance_curr_agent=False, stopped_reason="error")
        spec_tools: list[dict] = []

        def spec_emit(etype, payload=None, **_):
            if str(etype) == EventType.TOOL_CALL and payload:
                spec_tools.append({"tool": payload.get("tool"), "ok": payload.get("ok", True)})
            return {}

        forward = router_res.forward_text or text  # belt-and-suspenders: never the router's ack
        spec_res = await AgentRunner(specialist_spec, bus=None, emit=spec_emit).run(AgentInput(
            input=forward, history=history, summary=summary, allowed_routes=[],
            ctx=ToolContext(conversation_id=str(conv_id), chat_id=chat_id, agent_name=specialist_spec.name)))
        total += spec_res.usage.total_tokens
        active = router_res.route
        return RoutedTurn(
            reply=spec_res.text, active_agent=active,
            routed_from=curr_agent if (curr_agent and curr_agent != active) else None,
            total_tokens=total, tools=spec_tools, stopped_reason=spec_res.stopped_reason,
            advance_curr_agent=spec_res.stopped_reason != "error",  # a transient error must not pin curr_agent
        )

    # Router answered directly (no handoff). Only pin curr_agent on a clean answer — a degenerate
    # stop (max_steps/budget/timeout/error) shouldn't bias the next turn or surface raw filler.
    clean = router_res.stopped_reason == "complete"
    return RoutedTurn(
        reply=router_res.text or "How can I help?", active_agent=router_spec.name, routed_from=None,
        total_tokens=total, tools=[], stopped_reason=router_res.stopped_reason, advance_curr_agent=clean,
    )
