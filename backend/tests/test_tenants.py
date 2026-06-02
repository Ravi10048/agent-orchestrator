"""Multi-tenant SaaS — tenant bootstrap + cross-tenant isolation (Phase 1)."""
from app.models import Agent, Tool
from app.seed.tenants import create_tenant


def test_create_tenant_bootstraps_default_tools_only(session_factory):
    with session_factory() as db:
        t = create_tenant(db, "IKEA India")
        assert t.slug == "ikea-india"
        # a NEW tenant gets its own copies of the default builtin tools ...
        assert {x.name for x in db.query(Tool).filter_by(tenant_id=t.id).all()} == {
            "web_fetch", "calculator", "send_telegram"}
        # ... and NO agents — the user builds those (the supervisor is not a forced default agent)
        assert db.query(Agent).filter_by(tenant_id=t.id).count() == 0

        # idempotent — re-creating doesn't duplicate the tools
        create_tenant(db, "IKEA India")
        assert db.query(Tool).filter_by(tenant_id=t.id).count() == 3


def test_api_scopes_resources_per_tenant(client):
    a = client.post("/api/tenants", json={"name": "Acme One"}).json()
    b = client.post("/api/tenants", json={"name": "Beta Two"}).json()
    ha, hb = {"X-Tenant-Id": str(a["id"])}, {"X-Tenant-Id": str(b["id"])}

    # an agent created under tenant A ...
    r = client.post("/api/agents", json={"name": "OnlyInA"}, headers=ha)
    assert r.status_code == 201
    aid = r.json()["id"]

    # ... is visible to A but NOT to B (row-level isolation)
    a_names = [x["name"] for x in client.get("/api/agents", headers=ha).json()["items"]]
    b_names = [x["name"] for x in client.get("/api/agents", headers=hb).json()["items"]]
    assert a_names == ["OnlyInA"]
    assert "OnlyInA" not in b_names

    # ... and B cannot fetch A's agent by id
    assert client.get(f"/api/agents/{aid}", headers=hb).status_code == 404
    assert client.get(f"/api/agents/{aid}", headers=ha).status_code == 200


def test_new_tenant_starts_with_default_tools_no_agents(client):
    t = client.post("/api/tenants", json={"name": "Fresh Co"}).json()
    h = {"X-Tenant-Id": str(t["id"])}
    # default tools (3), no agents, no workflows — a blank slate the user builds on
    assert client.get("/api/tools", headers=h).json()["total"] == 3
    assert client.get("/api/agents", headers=h).json()["items"] == []
    assert client.get("/api/workflows", headers=h).json()["total"] == 0
