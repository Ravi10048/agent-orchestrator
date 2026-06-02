"""LLD 09 — API & WebSocket tests (critical-path 'agent creation' + contract)."""
import pytest
from fastapi.testclient import TestClient

import app.runtime.agent as agent_mod
import app.ws.monitor as monitor_mod
from app.core.deps import get_db
from app.core.tenancy import get_or_create_default_tenant
from app.llm.types import LLMResult, Usage
from app.main import create_app
from app.models import Run, Tool, Workflow
from app.models.event import RunEvent
from app.runtime.run_service import RunService
from app.runtime.scheduler import SchedulerService
from app.runtime.tools.seed import seed_tools
from app.ws.hub import MonitorHub


@pytest.fixture
def client(session_factory):
    # Wire the app's services to an in-memory DB; skip lifespan (no `with`) and set state manually.
    app = create_app()
    hub = MonitorHub()
    rs = RunService(session_factory, hub=hub)
    app.state.hub = hub
    app.state.run_service = rs
    app.state.scheduler = SchedulerService(rs, session_factory)  # unstarted; upsert → pending jobs

    def _db():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def _agent(client, **kw):
    return client.post("/api/agents", json={"name": "A", **kw}).json()["id"]


# ── agents (critical path: creation) ──────────────────────────────────
def test_agent_crud_and_tool_mapping(client, session_factory):
    with session_factory() as db:
        tid = get_or_create_default_tenant(db).id  # the tenant the API will scope to (no header)
        seed_tools(db, tenant_id=tid)
        tool_id = db.query(Tool).filter_by(tenant_id=tid, name="calculator").first().id

    r = client.post("/api/agents", json={"name": "Researcher", "tool_ids": [tool_id]})
    assert r.status_code == 201
    aid = r.json()["id"]
    assert [t["name"] for t in r.json()["tools"]] == ["calculator"]

    assert [t["name"] for t in client.get(f"/api/agents/{aid}").json()["tools"]] == ["calculator"]
    assert client.get("/api/agents").json()["total"] >= 1
    assert client.patch(f"/api/agents/{aid}", json={"role": "web researcher"}).json()["role"] == "web researcher"
    assert client.put(f"/api/agents/{aid}/tools", json={"tool_ids": []}).json()["tools"] == []
    assert client.delete(f"/api/agents/{aid}").status_code == 204
    assert client.get(f"/api/agents/{aid}").status_code == 404


def test_agent_bad_schedule_400_before_persist(client):
    r = client.post("/api/agents", json={"name": "Sched",
                                         "schedule": {"enabled": True, "kind": "cron", "cron": "garbage"}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "schedule_invalid"
    assert client.get("/api/agents").json()["total"] == 0  # not persisted


def test_unknown_field_rejected_422(client):
    r = client.post("/api/agents", json={"name": "X", "bogus": 1})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_404_envelope(client):
    r = client.get("/api/agents/99999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


# ── tools (registry + secret handling) ────────────────────────────────
def test_tool_crud_and_mapped_delete_conflict(client):
    tid = client.post("/api/tools", json={
        "name": "weather", "type": "http", "endpoint": "https://api.x/{city}", "http_method": "GET",
        "params_schema": {"type": "object", "properties": {"city": {"type": "string"}}}}).json()["id"]
    assert client.post("/api/tools", json={"name": "weather", "type": "http"}).status_code == 409  # dup
    _agent(client, tool_ids=[tid])
    assert client.delete(f"/api/tools/{tid}").status_code == 409  # mapped, no force
    assert client.delete(f"/api/tools/{tid}?force=true").status_code == 204


def test_tool_secret_handling(client):
    r = client.post("/api/tools", json={"name": "sec", "type": "http", "endpoint": "https://api.x",
                                        "http_method": "GET", "auth": {"type": "bearer", "token_env": "MY_TOKEN"}})
    assert r.status_code == 201 and r.json()["auth"]["token_env"] == "MY_TOKEN"  # env-var name kept
    # a raw secret value is rejected outright (extra='forbid' on AuthDTO)
    assert client.post("/api/tools", json={"name": "sec2", "type": "http",
                                           "auth": {"type": "bearer", "token": "raw-secret"}}).status_code == 422


def test_tool_header_secrets_redacted(client):
    # a secret parked in headers must not leak back out of read endpoints (LLD09 review regression)
    r = client.post("/api/tools", json={"name": "hdr", "type": "http", "endpoint": "https://api.x",
                                        "http_method": "GET",
                                        "headers": {"Authorization": "Bearer RAW", "X-Trace": "ok"}})
    assert r.status_code == 201
    hdrs = client.get(f"/api/tools/{r.json()['id']}").json()["headers"]
    assert hdrs["Authorization"] == "***" and hdrs["X-Trace"] == "ok"  # only the credential masked


def test_framework_errors_use_envelope(client):
    # unknown route (404) and wrong method (405) also return the {error:{code,message}} envelope
    r404 = client.get("/api/does-not-exist")
    assert r404.status_code == 404 and r404.json()["error"]["code"] == "not_found"
    r405 = client.put("/api/agents")  # collection has POST/GET, not PUT
    assert r405.status_code == 405 and r405.json()["error"]["code"] == "method_not_allowed"


# ── workflows ─────────────────────────────────────────────────────────
def test_workflow_invalid_graph_400(client):
    r = client.post("/api/workflows", json={"name": "wf",
                    "graph": {"nodes": [{"id": "start", "type": "start"}], "edges": []}})  # no end
    assert r.status_code == 400 and r.json()["error"]["code"] == "graph_invalid"
    assert isinstance(r.json()["error"]["details"], list) and r.json()["error"]["details"]


def test_workflow_validate_endpoint_200(client):
    r = client.post("/api/workflows/validate",
                    json={"graph": {"nodes": [{"id": "s", "type": "start"}], "edges": []}})
    assert r.status_code == 200 and r.json()["valid"] is False and r.json()["errors"]


def test_workflow_create_template_and_instantiate(client):
    aid = _agent(client)
    graph = {"nodes": [{"id": "start", "type": "start"}, {"id": "a", "type": "agent", "ref": aid},
                       {"id": "end", "type": "end"}],
             "edges": [{"from": "start", "to": "a"}, {"from": "a", "to": "end"}]}
    tpl = client.post("/api/workflows", json={"name": "T", "graph": graph, "is_template": True}).json()
    assert tpl["is_template"] is True
    assert any(w["id"] == tpl["id"] for w in client.get("/api/templates").json())
    inst = client.post(f"/api/workflows/{tpl['id']}/instantiate", json={}).json()
    assert inst["is_template"] is False
    assert inst["graph"]["nodes"][1]["ref"] == aid  # agent ref reused


def test_save_as_template_is_idempotent(client):
    """Regression: clicking 'Save as template' twice on one workflow must not create duplicates."""
    aid = _agent(client)
    graph = {"nodes": [{"id": "start", "type": "start"}, {"id": "a", "type": "agent", "ref": aid},
                       {"id": "end", "type": "end"}],
             "edges": [{"from": "start", "to": "a"}, {"from": "a", "to": "end"}]}
    wf = client.post("/api/workflows", json={"name": "My Flow", "graph": graph}).json()

    t1 = client.post(f"/api/workflows/{wf['id']}/save-as-template").json()
    t2 = client.post(f"/api/workflows/{wf['id']}/save-as-template").json()  # second click
    assert t1["is_template"] is True
    assert t1["id"] == t2["id"]  # upsert by (tenant, name) → same template, not a duplicate
    named = [w for w in client.get("/api/templates").json() if w["name"] == "My Flow"]
    assert len(named) == 1  # exactly one, no dup
    # the source workflow is untouched (still runnable, not flipped into a template)
    assert client.get(f"/api/workflows/{wf['id']}").json()["is_template"] is False


# ── runs ──────────────────────────────────────────────────────────────
def test_create_run_returns_run_id(client, monkeypatch):
    aid = _agent(client)
    graph = {"nodes": [{"id": "start", "type": "start"}, {"id": "a", "type": "agent", "ref": aid},
                       {"id": "end", "type": "end"}],
             "edges": [{"from": "start", "to": "a"}, {"from": "a", "to": "end"}]}
    wf = client.post("/api/workflows", json={"name": "w", "graph": graph}).json()

    async def fake(req, provider=None, fallback=None):
        return LLMResult(text="done", usage=Usage(total_tokens=3))

    monkeypatch.setattr(agent_mod, "complete", fake)
    r = client.post("/api/runs", json={"workflow_id": wf["id"], "input": {"text": "hi"}})
    assert r.status_code == 201 and r.json()["workflow_id"] == wf["id"]
    run_id = r.json()["id"]
    assert client.get(f"/api/runs/{run_id}").status_code == 200
    assert isinstance(client.get(f"/api/runs/{run_id}/events").json(), list)


def test_run_missing_workflow_404(client):
    assert client.post("/api/runs", json={"workflow_id": 9999}).status_code == 404


def test_cancel_finished_run_409(client, session_factory):
    with session_factory() as db:
        tid = get_or_create_default_tenant(db).id
        wf = Workflow(name="w", graph={}, tenant_id=tid)
        db.add(wf)
        db.commit()
        run = Run(workflow_id=wf.id, tenant_id=tid, status="completed", trigger="manual", input={})
        db.add(run)
        db.commit()
        rid = run.id
    r = client.post(f"/api/runs/{rid}/cancel")
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"


def test_events_seq_ordering_and_after_seq(client, session_factory):
    with session_factory() as db:
        tid = get_or_create_default_tenant(db).id
        wf = Workflow(name="w", graph={}, tenant_id=tid)
        db.add(wf)
        db.commit()
        run = Run(workflow_id=wf.id, tenant_id=tid, status="running", trigger="manual", input={})
        db.add(run)
        db.commit()
        rid = run.id
        for i in range(1, 6):
            db.add(RunEvent(run_id=rid, seq=i, type="node_started", payload={"i": i}))
        db.commit()
    assert [e["seq"] for e in client.get(f"/api/runs/{rid}/events").json()] == [1, 2, 3, 4, 5]
    assert [e["seq"] for e in client.get(f"/api/runs/{rid}/events?after_seq=3").json()] == [4, 5]


# ── meta ──────────────────────────────────────────────────────────────
def test_health_and_models(client):
    h = client.get("/api/health").json()
    assert h["ok"] is True and "llm_provider" in h and "telegram_present" in h
    assert "llama-3.3-70b-versatile" in client.get("/api/models?provider=groq").json()["models"]
    assert client.get("/health").json()["ok"] is True  # root ops probe


# ── websocket monitor (subscribe → backfill, seq-ordered) ─────────────
def test_ws_monitor_backfill(client, session_factory, monkeypatch):
    monkeypatch.setattr(monitor_mod, "SessionLocal", session_factory)  # backfill reads the test DB
    with session_factory() as db:
        wf = Workflow(name="w", graph={})
        db.add(wf)
        db.commit()
        run = Run(workflow_id=wf.id, status="running", trigger="manual", input={})
        db.add(run)
        db.commit()
        rid = run.id
        db.add_all([RunEvent(run_id=rid, seq=1, type="run_started", payload={}),
                    RunEvent(run_id=rid, seq=2, type="node_started", payload={"node_id": "a"})])
        db.commit()
    with client.websocket_connect("/ws/monitor") as ws:
        ws.send_json({"action": "subscribe", "run_id": rid})
        e1, e2 = ws.receive_json(), ws.receive_json()
        assert (e1["seq"], e2["seq"]) == (1, 2) and e1["type"] == "run_started"


def test_agent_draft_test_uses_unsaved_config_without_persisting(client, monkeypatch):
    """The editor's Test box runs the LIVE (unsaved) form config and persists nothing."""

    async def fake(req, provider=None, fallback=None):
        sys = next((m["content"] for m in req.messages if m["role"] == "system"), "")
        return LLMResult(text=f"[sys]{sys}", usage=Usage(total_tokens=5))

    monkeypatch.setattr(agent_mod, "complete", fake)
    before = client.get("/api/agents").json()["total"]
    r = client.post("/api/agents/test", json={"message": "hi", "model": "llama-3.3-70b-versatile",
                                              "system_prompt": "You are Zeta, a test bot."})
    assert r.status_code == 200
    assert "You are Zeta, a test bot." in r.json()["reply"]      # the UNSAVED prompt was used
    assert client.get("/api/agents").json()["total"] == before   # nothing persisted
