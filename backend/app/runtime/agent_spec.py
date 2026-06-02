"""In-memory AgentSpec (an Agent row + resolved tools) and the control-tool specs
(handoff / send_message) injected only when a node has peer routes (LLD 05)."""
from dataclasses import dataclass


@dataclass
class AgentSpec:
    name: str
    role: str
    system_prompt: str
    provider: str
    model: str
    tools: list  # resolved Tool rows (the allow-list / "skills")
    guardrails: dict  # {max_steps, max_tokens, max_tokens_total, timeout_s}
    memory_config: dict  # {type, window, summary}


def build_agent_spec(agent) -> AgentSpec:
    """Build the in-memory spec the Executor/Channel hand to AgentRunner (DB → spec)."""
    return AgentSpec(
        name=agent.name,
        role=agent.role or "",
        system_prompt=agent.system_prompt or "",
        provider=agent.provider or "groq",
        model=agent.model,
        tools=list(agent.tools),
        guardrails=dict(agent.guardrails or {}),
        memory_config=dict(agent.memory_config or {}),
    )


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def control_tool_specs(handoff_routes: list[str], peers: list[str] | None = None) -> list[dict]:
    """Routing rides native tool-calling. Two DISTINCT controls, offered independently:
    - `handoff` (transfer control) only when there's a genuine choice — handoff_routes has the
      candidates (the executor passes them only when >= 2 unconditional agent routes exist).
    - `send_message` (async peer consult, keeps control) whenever there are peer agents to talk to.
    """
    peers = peers or []
    specs: list[dict] = []
    if handoff_routes:
        # The routing decision, supervisor-style: `to_agent` is the NEXT agent (n) and `response` is the
        # router's own reply to the user (r). The chosen specialist still receives the original
        # request; `response` is shown as the router's message (see AgentRunner handoff handling).
        specs.append(
            _fn(
                "handoff",
                "Route the task to the chosen specialist and end your turn. `to_agent` is the next "
                "agent (the routing decision); `response` is a short message to the user about who is "
                "handling it (optional).",
                {"to_agent": {"type": "string", "enum": handoff_routes,
                              "description": "Exact name of the specialist to route to (the next agent)."},
                 "response": {"type": "string",
                              "description": "A brief reply to the user about who is handling this (optional)."}},
                ["to_agent"],
            )
        )
    if peers:
        specs.append(
            _fn(
                "send_message",
                "Send an async message to a peer agent (e.g. a heads-up or a question); you keep control.",
                {"to_agent": {"type": "string", "enum": peers}, "content": {"type": "string"}},
                ["to_agent", "content"],
            )
        )
    return specs
