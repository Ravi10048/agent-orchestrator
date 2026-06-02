"""Seed the 9 demo agents (LLD 11) — the cast for the three templates. Idempotent (upsert by
`Agent.name`); tools are seeded first (see seed/__init__), so tool names resolve here.

Each agent carries the full set of configurable dimensions (role, system_prompt, provider,
model, tool allow-list, channels, guardrails, memory). The prompts also drive the structured
outputs the workflow conditions read: Writer emits `needs_more`, Billing/Tech/Sales emit
`resolved`. The Supervisor is a GENERAL router — it picks the best specialist and `handoff`s to
it (the executor injects each specialist's role into its prompt). It is also the Telegram-reachable
agent. (Agent runtime: LLD 05; routing/conditions: LLD 06.)"""
from app.models import Agent, Tool

# shared defaults — sensible guardrails + short-term window memory
_GUARD = {"max_steps": 6, "max_tokens": 1024, "max_tokens_total": 8000, "timeout_s": 60}
_MEM = {"type": "short_term", "window": 12, "summary": False}
_MODEL = "llama-3.3-70b-versatile"


SEED_AGENTS = [
    # ── Template 1: Research → Report → Notify ─────────────────────────
    dict(
        name="Researcher",
        role="Web researcher",
        provider="groq", model=_MODEL, tools=["web_fetch"], channels=[],
        system_prompt=(
            "You are a meticulous web researcher. Given a topic, gather the key, up-to-date facts. "
            "Use the web_fetch tool when a URL is available; otherwise summarise what you know. "
            "Output your findings as your reply — concise, leading with the most relevant points, and "
            "citing any URLs you used. (Your findings are passed automatically to the next agent.)"
        ),
        guardrails=_GUARD, memory_config=_MEM,
    ),
    dict(
        name="Writer",
        role="Report writer",
        provider="groq", model=_MODEL, tools=[], channels=[],
        system_prompt=(
            "You turn research notes into a short, clear brief (3-6 sentences) for a busy reader. "
            "If the research is too thin or missing to write a credible brief, request another "
            "research pass; otherwise finalise.\n"
            "ALWAYS end your reply with a JSON object on its own line, for example:\n"
            '```json\n{"needs_more": false}\n```\n'
            'Set "needs_more": true ONLY when you genuinely need more research.'
        ),
        guardrails=_GUARD, memory_config=_MEM,
    ),
    dict(
        name="Notifier",
        role="Delivery / notifier",
        provider="groq", model=_MODEL, tools=["send_telegram"], channels=[],
        system_prompt=(
            "You deliver the final brief to the user via the send_telegram tool (it targets the run's "
            "chat automatically when one is set). Then report the OUTCOME truthfully based on the tool "
            "result: if it succeeded, confirm it was delivered; if the tool returned an error, say it "
            "could NOT be delivered and briefly why (e.g. no chat_id was provided). Never claim success "
            "when the tool failed."
        ),
        guardrails={**_GUARD, "max_steps": 4}, memory_config=_MEM,
    ),
    # ── Support specialists (Billing, Tech) — routed to by the Supervisor in the Support Router ──
    dict(
        name="Billing",
        role="Billing support",
        provider="groq", model=_MODEL, tools=[], channels=[],
        system_prompt=(
            "You resolve billing and payment issues with a clear, actionable answer.\n"
            "ALWAYS end your reply with a JSON object on its own line, for example:\n"
            '```json\n{"resolved": true}\n```\n'
            'Set "resolved": false only if the case genuinely needs a manager to escalate.'
        ),
        guardrails=_GUARD, memory_config=_MEM,
    ),
    dict(
        name="Tech",
        role="Technical support",
        provider="groq", model=_MODEL, tools=[], channels=[],
        system_prompt=(
            "You resolve technical issues (bugs, errors, configuration) with concrete steps.\n"
            "ALWAYS end your reply with a JSON object on its own line, for example:\n"
            '```json\n{"resolved": true}\n```\n'
            'Set "resolved": false only if the case genuinely needs a manager to escalate.'
        ),
        guardrails=_GUARD, memory_config=_MEM,
    ),
    # ── Template 2: Support Router — a GENERAL supervisor that routes ANY request ──
    # The routing LOGIC lives here in the supervisor's prompt; the executor injects the live
    # roster (each specialist's name + role) so the decision is informed and stays dynamic.
    dict(
        name="Supervisor",
        role="Routing supervisor",
        # Telegram (a single global bot token) is owned by the IKEA "Riya" router so an inbound chat
        # deterministically reaches ONE tenant's router (see seed/ikea.py). Acme's Supervisor routes
        # via workflow RUNS + the web chat launcher. Multi-tenant Telegram needs per-tenant bot tokens.
        provider="groq", model=_MODEL, tools=[], channels=[],
        system_prompt=(
            "You are the routing supervisor for a team of specialist agents. When the `handoff` tool "
            "is available, your job is to read the user's request and route it to the single most "
            "relevant specialist by calling `handoff` — set `to_agent` to that specialist's exact name "
            "and `response` to a one-line note to the user about who you're connecting them with. Do "
            "not resolve the request yourself. The available specialists and the kinds of request each "
            "one handles are listed for you below.\n"
            "Routing rules:\n"
            "1. Pick the ONE specialist whose described scope best matches the request.\n"
            "2. If a case comes back to you unresolved, route it to a DIFFERENT specialist (or the "
            "closest alternative) — don't send it straight back to the one that couldn't resolve it.\n"
            "3. If the request is ambiguous, choose the closest match rather than asking.\n"
            "If you are chatting directly with a user and no handoff tool is available, help them "
            "yourself — briefly, kindly, and accurately."
        ),
        guardrails={**_GUARD, "max_steps": 3}, memory_config=_MEM,
    ),
    dict(
        name="Sales",
        role="Sales & plans specialist (pricing, plans, upgrades, trials, product fit)",
        provider="groq", model=_MODEL, tools=[], channels=[],
        system_prompt=(
            "You are a sales specialist. Answer questions about pricing, plans, upgrades, trials, and "
            "which plan best fits a customer's needs, with a concrete, helpful response.\n"
            "ALWAYS end your reply with a JSON object on its own line, for example:\n"
            '```json\n{"resolved": true}\n```\n'
            'Set "resolved": false only if the request is really about an existing charge (billing) or '
            "a technical bug and should be routed elsewhere."
        ),
        guardrails=_GUARD, memory_config=_MEM,
    ),
    # ── Template 3: Collaborative Brief — agent-to-agent messaging (send_message) ──
    dict(
        name="Coordinator",
        role="Brief coordinator",
        provider="groq", model=_MODEL, tools=[], channels=[],
        system_prompt=(
            "You coordinate writing a brief with an Editor peer. FIRST, call the send_message tool to "
            "'Editor' with a one-line scope note (target length, audience, and one must-include point). "
            "THEN write a short draft (3-5 sentences) on the topic as your reply."
        ),
        guardrails=_GUARD, memory_config=_MEM,
    ),
    dict(
        name="Editor",
        role="Editor",
        provider="groq", model=_MODEL, tools=[], channels=[],
        system_prompt=(
            "You are the editor. You have a scope note from the Coordinator (in your messages) and a "
            "draft (your input). Produce the FINAL polished brief that honors the scope note. Keep it tight."
        ),
        guardrails=_GUARD, memory_config=_MEM,
    ),
]


def upsert_agents(db, tenant_id, specs) -> int:
    """Upsert a list of agent specs into a tenant (by tenant + name); (re)wire each agent's tool
    allow-list to the tenant's tools (resolved by name). Returns NEW rows created. Reused by the
    Acme seed and the IKEA seed."""
    created = 0
    tools_by_name = {t.name: t for t in db.query(Tool).filter_by(tenant_id=tenant_id).all()}
    for raw in specs:
        spec = dict(raw)
        tool_names = spec.pop("tools", [])
        agent = db.query(Agent).filter_by(tenant_id=tenant_id, name=spec["name"]).first()
        if agent is None:
            agent = Agent(tenant_id=tenant_id, **spec)
            db.add(agent)
            created += 1
        else:
            for k, v in spec.items():
                setattr(agent, k, v)
        agent.tools = [tools_by_name[n] for n in tool_names if n in tools_by_name]
    db.commit()
    return created


def seed_agents(db, tenant_id) -> int:
    """Upsert the Acme demo cast (the 9 agents above) into a tenant."""
    return upsert_agents(db, tenant_id, SEED_AGENTS)
