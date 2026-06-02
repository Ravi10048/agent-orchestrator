"""LLD 11 + multi-tenant — seed tests: idempotency, all templates valid, agent↔tool/channel
mappings (scoped to the Acme tenant), and the IKEA "Riya" tenant (Phase 2)."""
from app.models import Agent, Tool, Workflow
from app.runtime.executor import GraphExecutor
from app.seed import run_seed
from app.seed.tenants import get_or_create_tenant


def _acme(db):
    return get_or_create_tenant(db, "Acme Support", slug="acme").id


def _ikea(db):
    return get_or_create_tenant(db, "IKEA India", slug="ikea-india").id


def test_run_seed_idempotent(session_factory):
    with session_factory() as db:
        first = run_seed(db)
    assert first == {"tools": 3, "agents": 9, "templates": 3}  # the Acme counts

    with session_factory() as db:
        second = run_seed(db)  # re-run creates nothing new
        assert second == {"tools": 0, "agents": 0, "templates": 0}
        acme = _acme(db)
        assert db.query(Tool).filter_by(tenant_id=acme).count() == 3
        assert db.query(Agent).filter_by(tenant_id=acme).count() == 9
        assert db.query(Workflow).filter_by(tenant_id=acme, is_template=True).count() == 3


def test_all_acme_templates_validate(session_factory):
    with session_factory() as db:
        run_seed(db)
        validator = GraphExecutor(None)
        templates = db.query(Workflow).filter_by(tenant_id=_acme(db), is_template=True).all()
        assert {t.name for t in templates} == {
            "Research → Report → Notify", "Support Router", "Collaborative Brief"}
        for wf in templates:
            g = validator.validate_graph(wf.graph, db)  # raises GraphValidationError if drifted
            assert g.start_id == "start"


def test_acme_agent_tool_and_channel_mapping(session_factory):
    with session_factory() as db:
        run_seed(db)
        acme = _acme(db)
        # the Acme cast is exactly these 9 agents (tenant-scoped)
        assert {a.name for a in db.query(Agent).filter_by(tenant_id=acme).all()} == {
            "Researcher", "Writer", "Notifier", "Billing", "Tech",
            "Supervisor", "Sales", "Coordinator", "Editor"}
        researcher = db.query(Agent).filter_by(tenant_id=acme, name="Researcher").first()
        assert [t.name for t in researcher.tools] == ["web_fetch"]
        supervisor = db.query(Agent).filter_by(tenant_id=acme, name="Supervisor").first()
        # Acme's Supervisor routes via workflow runs + the web chat launcher; Telegram (one global bot
        # token) is owned by IKEA's Riya so an inbound chat reaches exactly one tenant's router.
        assert supervisor.tools == [] and "telegram" not in supervisor.channels


def test_template_refs_point_at_same_tenant_agents(session_factory):
    with session_factory() as db:
        run_seed(db)
        for wf in db.query(Workflow).filter_by(is_template=True).all():
            tenant_agent_ids = {a.id for a in db.query(Agent).filter_by(tenant_id=wf.tenant_id).all()}
            for n in wf.graph["nodes"]:
                if n["type"] == "agent":
                    assert n["ref"] in tenant_agent_ids  # ref resolves to an agent IN THE SAME TENANT


def test_support_router_supervisor_has_informed_routes(session_factory):
    with session_factory() as db:
        run_seed(db)
        ex = GraphExecutor(None)
        wf = db.query(Workflow).filter_by(
            tenant_id=_acme(db), name="Support Router", is_template=True).first()
        graph = ex.validate_graph(wf.graph, db)
        assert graph.agent_name_of["supervisor"] == "Supervisor"
        routes = ex._handoff_routes(graph.nodes["supervisor"], graph)
        assert set(routes) == {"Billing", "Tech", "Sales"}
        descs = ex._route_descriptions(graph.nodes["supervisor"], graph)
        assert all(descs.get(r) for r in routes)  # every route carries a non-empty description


def test_ikea_tenant_seeded_with_riya_router(session_factory):
    """The IKEA India tenant: Riya routes to 6 specialists, the IKEA HTTP tools are present, and the
    tenant is isolated from Acme."""
    with session_factory() as db:
        run_seed(db)
        ikea, acme = _ikea(db), _acme(db)
        # the router is a regular agent named "Supervisor" (persona Riya) + the 6 specialists
        assert {a.name for a in db.query(Agent).filter_by(tenant_id=ikea).all()} == {
            "Supervisor", "Pricing", "Delivery", "Payments", "Product", "Retention", "Care", "Notify"}
        ikea_supervisor = db.query(Agent).filter_by(tenant_id=ikea, name="Supervisor").first()
        assert "telegram" in ikea_supervisor.channels  # Riya is the Telegram-reachable router
        tools = {t.name for t in db.query(Tool).filter_by(tenant_id=ikea).all()}
        assert {"get_cart", "check_pincode", "generate_payment_link", "calculate_emi"} <= tools
        assert "web_fetch" in tools  # default builtins also seeded into the tenant

        ex = GraphExecutor(None)
        wf = db.query(Workflow).filter_by(
            tenant_id=ikea, name="Abandoned-Cart Recovery", is_template=False).first()
        assert wf is not None  # a regular workflow (shows on the Workflows page), not a gallery template
        graph = ex.validate_graph(wf.graph, db)
        # the Supervisor routes to the specialists it's connected to (its sub-agent list)
        routes = ex._handoff_routes(graph.nodes["supervisor"], graph)
        assert set(routes) == {"Pricing", "Delivery", "Payments", "Product", "Retention", "Care", "Notify"}
        descs = ex._route_descriptions(graph.nodes["supervisor"], graph)
        assert all(descs.get(r) for r in routes)  # each connected sub-agent's role is available to inject

        # isolation: IKEA's tools are NOT visible in the Acme tenant
        assert db.query(Tool).filter_by(tenant_id=acme, name="get_cart").first() is None
