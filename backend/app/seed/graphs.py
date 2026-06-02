"""The three template graphs (LLD 11), built by resolving seeded agent NAMES → ids at seed time.
Keeping the graphs name-based here makes them readable and resilient to whatever ids the DB
assigns. Graph shape matches the executor contract (LLD 06): nodes {id,type,ref,config},
edges {from,to,condition}. Each is run through `validate_graph` in templates.py."""
from app.models import Agent

# Support Router: a specialist sends an unresolved case back to the Supervisor to re-route, bounded
# per specialist by `attempts` (times this node has run) so it can't bounce forever.
_UNRESOLVED_RETRY = "last.resolved == false and attempts < 2"


def _agent_ids(db, tenant_id) -> dict[str, int]:
    return {a.name: a.id for a in db.query(Agent).filter_by(tenant_id=tenant_id).all()}


def research_report_notify_graph(db, tenant_id) -> dict:
    """T1 — linear pipeline with a bounded feedback loop.
    Researcher → Writer → (loops back if `needs_more`) → Notifier → end."""
    ids = _agent_ids(db, tenant_id)
    return {
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "researcher", "type": "agent", "ref": ids["Researcher"], "config": {"max_visits": 3}},
            {"id": "writer", "type": "agent", "ref": ids["Writer"]},
            {"id": "notifier", "type": "agent", "ref": ids["Notifier"]},
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"from": "start", "to": "researcher"},
            {"from": "researcher", "to": "writer"},
            # feedback loop — capped by researcher.max_visits so it can't spin forever
            {"from": "writer", "to": "researcher", "condition": "last.needs_more == true"},
            {"from": "writer", "to": "notifier"},  # default edge
            {"from": "notifier", "to": "end"},
        ],
    }


def support_router_graph(db, tenant_id) -> dict:
    """T3 — a GENERAL supervisor/router (the 'supervisor is the hub' pattern).
    The Supervisor reads ANY request and hands off to the best specialist (Billing / Tech / Sales)
    via the `handoff` tool; that specialist answers (transfer of control). If a specialist can't
    resolve it, the case loops BACK to the Supervisor to re-route (bounded) — the Supervisor owns the
    fallback decision, so there is no separate escalation manager.

    The three unconditional out-edges give the Supervisor allowed_routes=[Billing,Tech,Sales], and the
    executor injects each specialist's role into the Supervisor's prompt so routing is informed."""
    ids = _agent_ids(db, tenant_id)
    return {
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "supervisor", "type": "agent", "ref": ids["Supervisor"], "config": {"max_visits": 5}},
            {"id": "billing", "type": "agent", "ref": ids["Billing"]},
            {"id": "tech", "type": "agent", "ref": ids["Tech"]},
            {"id": "sales", "type": "agent", "ref": ids["Sales"]},
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"from": "start", "to": "supervisor"},
            # 3 unconditional agent out-edges → Supervisor gets handoff with [Billing, Tech, Sales]
            {"from": "supervisor", "to": "billing"},
            {"from": "supervisor", "to": "tech"},
            {"from": "supervisor", "to": "sales"},
            # each specialist: unresolved → back to the Supervisor to re-route (bounded per specialist
            # by `attempts` so it can't bounce forever); otherwise → end (default).
            {"from": "billing", "to": "supervisor", "condition": _UNRESOLVED_RETRY},
            {"from": "billing", "to": "end"},
            {"from": "tech", "to": "supervisor", "condition": _UNRESOLVED_RETRY},
            {"from": "tech", "to": "end"},
            {"from": "sales", "to": "supervisor", "condition": _UNRESOLVED_RETRY},
            {"from": "sales", "to": "end"},
        ],
    }


def collaborative_brief_graph(db, tenant_id) -> dict:
    """T3 — agent-to-agent messaging (send_message). The Coordinator sends a scope note to the Editor
    peer (async, keeping control), then writes a draft; the Editor finalizes using the note + draft.
    No node has a handoff choice → the graph is NOT a router, so the executor offers `send_message`
    (peer messaging) — this is the template that populates the inter-agent 'Agents' tab."""
    ids = _agent_ids(db, tenant_id)
    return {
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "coordinator", "type": "agent", "ref": ids["Coordinator"]},
            {"id": "editor", "type": "agent", "ref": ids["Editor"]},
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"from": "start", "to": "coordinator"},
            {"from": "coordinator", "to": "editor"},
            {"from": "editor", "to": "end"},
        ],
    }
