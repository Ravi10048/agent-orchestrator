"""Seed the 3 workflow templates (LLD 11). Idempotent by (name, is_template=True).

Each graph is run through `validate_graph` AT SEED TIME, so a drifted template (a renamed
agent, a dangling ref, an all-conditional branch) fails loud at startup — never mid-demo."""
from app.models import Workflow
from app.runtime.executor import GraphExecutor
from app.seed.graphs import (
    collaborative_brief_graph,
    research_report_notify_graph,
    support_router_graph,
)

SEED_TEMPLATES = [
    dict(
        name="Research → Report → Notify",
        description=(
            "A researcher gathers facts, a writer drafts a brief (looping back for another pass if "
            "the research is thin), and a notifier delivers it over Telegram. Linear pipeline with a "
            "bounded feedback loop."
        ),
        build=research_report_notify_graph,
    ),
    dict(
        name="Support Router",
        description=(
            "A general supervisor reads ANY incoming request and routes it to the best specialist — "
            "Billing, Tech, or Sales — by calling the handoff tool (its prompt lists what each one "
            "handles, injected at runtime). It returns the next agent (n) + a short reply (r); "
            "unresolved cases loop back to re-route. Demonstrates dynamic, supervisor-driven routing "
            "+ agent-to-agent transfer of control."
        ),
        build=support_router_graph,
    ),
    dict(
        name="Collaborative Brief",
        description=(
            "A Coordinator messages an Editor peer (send_message — async, keeping control) with a "
            "scope note, then drafts; the Editor finalizes using the note + draft. Demonstrates "
            "agent-to-agent messaging and populates the inter-agent 'Agents' monitor tab."
        ),
        build=collaborative_brief_graph,
    ),
]


def seed_templates(db, tenant_id) -> int:
    """Upsert templates (by tenant + name); validate each graph at seed time. Returns NEW rows created."""
    created = 0
    validator = GraphExecutor(None)  # validate_graph only needs the passed-in db session
    for spec in SEED_TEMPLATES:
        graph = spec["build"](db, tenant_id)
        validator.validate_graph(graph, db)  # raises GraphValidationError if drifted → fail loud
        wf = db.query(Workflow).filter_by(tenant_id=tenant_id, name=spec["name"], is_template=True).first()
        if wf is None:
            wf = Workflow(tenant_id=tenant_id, name=spec["name"], description=spec["description"],
                          graph=graph, is_template=True)
            db.add(wf)
            created += 1
        else:
            wf.description = spec["description"]
            wf.graph = graph
    db.commit()
    return created
