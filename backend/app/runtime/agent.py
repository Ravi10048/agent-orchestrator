"""AgentRunner — one agent's turn (LLD 05).

Build prompt → LLM → tool-calling loop → optionally hand off / message peers → return a
structured AgentResult. DB-free and context-agnostic: the Executor/Channel assemble
history and persist results, so the SAME runner serves workflow nodes AND 1:1 channel chat.
Every stop path returns a valid AgentResult (stopped_reason); it never hangs or raises.
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field
from uuid import uuid4

from app.llm import complete
from app.llm.types import LLMRequest, LLMResult, Usage
from app.models.enums import EventType
from app.runtime.agent_spec import AgentSpec, control_tool_specs
from app.runtime.bus.base import BusMessage
from app.runtime.tools.base import ToolContext, ToolResult
from app.runtime.tools.registry import execute_tool_call
from app.runtime.tools.spec import build_tool_specs

log = logging.getLogger("runtime.agent")


@dataclass
class AgentInput:
    input: str  # triggering content
    history: list[dict] = field(default_factory=list)  # prior msgs (OpenAI format), already windowed
    summary: str = ""  # rolling summary memory (optional)
    inbox: list[BusMessage] = field(default_factory=list)  # peer messages (drained by Executor)
    allowed_routes: list[str] = field(default_factory=list)  # agents this node may HAND OFF to (transfer)
    route_descriptions: dict[str, str] = field(default_factory=dict)  # route name -> role/desc (informs routing)
    peers: list[str] = field(default_factory=list)  # agents this node may send_message to (consult, keep control)
    current_handler: str | None = None  # specialist currently holding a routed chat (sticky hint to a router)
    ctx: ToolContext = field(default_factory=ToolContext)


@dataclass
class AgentResult:
    text: str  # this agent's reply (for a router handoff: `r`, the router's own message to the user)
    route: str | None = None  # chosen next agent — the `n` (set iff handoff was called)
    forward_text: str | None = None  # text passed to the NEXT node (None → use `text`); on a router
    #                                  handoff this is the ORIGINAL request, so the specialist gets it
    structured: dict = field(default_factory=dict)  # optional fields for edge conditions
    usage: Usage = field(default_factory=Usage)  # accumulated across the whole turn
    steps: int = 0
    stopped_reason: str = "complete"  # complete | handoff | max_steps | budget | timeout | error
    tool_runs: list[dict] = field(default_factory=list)  # audit (name, ok, latency)
    peer_messages: list[BusMessage] = field(default_factory=list)


# ── prompt assembly ───────────────────────────────────────────────────
def compose_system_prompt(spec: AgentSpec, allowed_routes: list[str], summary: str,
                          peers: list[str] | None = None,
                          route_descriptions: dict[str, str] | None = None,
                          current_handler: str | None = None) -> str:
    peers = peers or []
    route_descriptions = route_descriptions or {}
    parts = [spec.system_prompt.strip()]
    if spec.role:
        parts.append(f"Your role: {spec.role}.")
    if summary:
        parts.append(f"Conversation summary so far:\n{summary}")
    if allowed_routes:
        # When the handoff targets have descriptions (a supervisor/router), list each specialist and
        # what it handles so the routing decision is INFORMED — not a guess from bare names.
        if any(route_descriptions.get(r) for r in allowed_routes):
            roster = "\n".join(f"- {r} — {route_descriptions.get(r) or 'specialist'}" for r in allowed_routes)
            parts.append(
                "You coordinate a team of specialists. Read the request, pick the SINGLE best "
                "specialist for it, and call the `handoff` tool with their exact name "
                f"(one of: {', '.join(allowed_routes)}). Available specialists:\n{roster}\n"
                # glue-aware (this is the LAST line a recency-biased model reads, so it must AGREE with a
                # supervisor prompt that owns greetings/closings — not fight it by always preferring handoff)
                "Hand off ONLY for a substantive request; for a greeting, acknowledgement, goodbye, or an "
                "unclear or off-topic message, answer the user yourself instead of handing off."
            )
        else:
            parts.append(
                "You are part of a multi-agent workflow. When another agent should take over the task, "
                f"call the `handoff` tool with one of: {', '.join(allowed_routes)}. Otherwise, answer directly."
            )
        # Sticky per-turn routing (conversational stretch): bias toward the specialist already helping
        # so a multi-turn thread stays put, while still letting a topic switch re-route. Gated on the
        # handler still being a live route, so a renamed/removed specialist silently drops the hint.
        if current_handler and current_handler in allowed_routes:
            parts.append(
                f"This conversation is currently being handled by {current_handler}. Keep it with "
                f"{current_handler} for a follow-up on the SAME topic; but if the new message is a "
                "greeting, acknowledgement, or goodbye, or clearly needs a different specialist, do "
                "not keep it there — answer glue yourself and route a new topic fresh."
            )
    if peers:
        parts.append(
            "To consult or notify a peer agent WITHOUT giving up control, call `send_message` with one "
            f"of: {', '.join(peers)} and your message; then continue."
        )
    return "\n\n".join(p for p in parts if p)


def build_messages(spec: AgentSpec, inp: AgentInput) -> list[dict]:
    msgs = [{"role": "system",
             "content": compose_system_prompt(spec, inp.allowed_routes, inp.summary, inp.peers,
                                              inp.route_descriptions, inp.current_handler)}]
    msgs += inp.history  # windowed short-term memory
    if inp.inbox:  # peer messages → one framed user turn
        peers = "\n".join(f"[from {m.from_agent}] {m.content}" for m in inp.inbox)
        msgs.append({"role": "user", "content": f"Messages from other agents:\n{peers}"})
    if inp.input:
        msgs.append({"role": "user", "content": inp.input})
    return msgs


# ── the turn ──────────────────────────────────────────────────────────
class AgentRunner:
    def __init__(self, spec: AgentSpec, *, bus=None, emit=None):
        self.spec = spec
        self.bus = bus
        self.emit = emit or (lambda *a, **k: None)
        self.tools_by_name = {t.name: t for t in spec.tools}

    async def run(self, inp: AgentInput) -> AgentResult:
        g = self.spec.guardrails
        msgs = build_messages(self.spec, inp)
        specs = build_tool_specs(self.spec) + control_tool_specs(inp.allowed_routes, inp.peers)
        usage, steps = Usage(), 0
        tool_runs: list[dict] = []
        peer_messages: list[BusMessage] = []
        deadline = time.monotonic() + g.get("timeout_s", 60)

        def _make(text, *, route=None, forward=None, structured=None, reason="complete") -> AgentResult:
            return AgentResult(
                text=text, route=route, forward_text=forward, structured=structured or {}, usage=usage,
                steps=steps, stopped_reason=reason, tool_runs=tool_runs, peer_messages=peer_messages,
            )

        try:
            while steps < g.get("max_steps", 6):
                steps += 1
                res = await complete(
                    LLMRequest(messages=msgs, tools=specs or None, model=self.spec.model,
                               temperature=0.4, max_tokens=g.get("max_tokens", 1024)),
                    provider=self.spec.provider,
                )
                usage = usage + res.usage

                if not res.tool_calls:  # final answer
                    return _make(res.text, structured=_extract_structured(res.text))

                msgs.append(_assistant_tool_turn(res))  # echo assistant tool_calls
                for call in res.tool_calls:
                    if call.name == "handoff":
                        route = call.arguments.get("to_agent")
                        ok = route in inp.allowed_routes
                        msgs.append(_tool_msg(call.id, {"ok": ok, "routed_to": route if ok else None}))
                        if ok:
                            # supervisor-style {r, n}: `route` is the next agent (n); `r` is the router's own
                            # reply to the user. The chosen specialist must receive the ORIGINAL request
                            # (not the router's acknowledgment), so FORWARD the input and SHOW `r`.
                            r = call.arguments.get("response") or res.text or ""
                            forward = inp.input or r or f"Routing to {route}."
                            return _make(r or forward, route=route, forward=forward, reason="handoff")
                    elif call.name == "send_message" and self.bus:
                        bm = BusMessage(id=uuid4().hex, from_agent=self.spec.name,
                                        to_agent=call.arguments["to_agent"], content=call.arguments["content"],
                                        run_id=inp.ctx.run_id)
                        await self.bus.publish(bm)
                        peer_messages.append(bm)
                        self.emit(EventType.AGENT_MESSAGE, _ev(bm))
                        msgs.append(_tool_msg(call.id, {"sent": True}))
                    else:
                        tool = self.tools_by_name.get(call.name)  # allow-list enforced here
                        result = (
                            ToolResult(False, error=f"tool '{call.name}' not allowed")
                            if not tool
                            else await execute_tool_call(tool, call.arguments, inp.ctx)
                        )
                        tool_runs.append({"tool": call.name, "ok": result.ok, "latency_ms": result.latency_ms})
                        self.emit(EventType.TOOL_CALL, {"agent_name": self.spec.name, "tool": call.name,
                                                        "ok": result.ok, "latency_ms": result.latency_ms,
                                                        "error": result.error})
                        msgs.append(_tool_msg(call.id, result.output if result.ok else {"error": result.error}))

                if usage.total_tokens >= g.get("max_tokens_total", 8000):
                    text = _last_text(msgs) or "(token budget reached)"
                    return _make(text, structured=_extract_structured(text), reason="budget")
                if time.monotonic() > deadline:
                    return _make("(turn timed out)", reason="timeout")

            text = _last_text(msgs) or "(max steps reached)"
            return _make(text, structured=_extract_structured(text), reason="max_steps")
        except Exception as e:
            log.warning("agent '%s' turn error: %s: %s", self.spec.name, type(e).__name__, e)
            self.emit(EventType.ERROR, {"scope": "node", "agent_name": self.spec.name,
                                        "error": f"{type(e).__name__}: {e}", "stopped_reason": "error"})
            return _make("Sorry — I hit an error completing that.", reason="error")


# ── helpers ───────────────────────────────────────────────────────────
def _assistant_tool_turn(res: LLMResult) -> dict:
    return {
        "role": "assistant",
        "content": res.text or "",
        "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
            for tc in res.tool_calls
        ],
    }


def _tool_msg(call_id: str, payload) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(payload, default=str)}


def _last_text(msgs: list[dict]) -> str:
    for m in reversed(msgs):
        if m.get("role") == "assistant" and isinstance(m.get("content"), str) and m["content"].strip():
            return m["content"]
    return ""


def _ev(bm: BusMessage) -> dict:
    return {"msg_id": bm.id, "from_agent": bm.from_agent, "to_agent": bm.to_agent,
            "content_preview": bm.content[:200], "broadcast": bm.to_agent == "*"}


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_structured(text: str) -> dict:
    """Lenient: pull a JSON object from the agent's final text so edge conditions can read
    fields like `last.needs_more` / `last.resolved`. Prefers a fenced ```json block, else a
    bare trailing {...}. Absent/invalid → {} (never raises)."""
    if not text:
        return {}
    candidates = []
    m = _JSON_FENCE.search(text)
    if m:
        candidates.append(m.group(1))
    i, j = text.find("{"), text.rfind("}")
    if i != -1 and j > i:
        candidates.append(text[i : j + 1])
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return {}
