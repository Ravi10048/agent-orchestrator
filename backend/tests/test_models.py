"""LLD 01 — data model tests (foundation of the critical-path 'agent creation')."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Agent, Conversation, Message, Run, RunEvent, Tenant, Tool, Workflow


def test_agent_tool_mapping_roundtrip(db):
    tool = Tool(name="web_fetch", type="builtin", builtin_key="web_fetch",
                params_schema={"type": "object", "properties": {"url": {"type": "string"}}})
    agent = Agent(name="Researcher", role="Web researcher", tools=[tool])
    db.add(agent)
    db.commit()
    aid = agent.id

    db.expire_all()  # force a real reload
    reloaded = db.get(Agent, aid)
    assert [t.name for t in reloaded.tools] == ["web_fetch"]


def test_query_templates(db):
    db.add_all([
        Workflow(name="T1", is_template=True, graph={"nodes": [], "edges": []}),
        Workflow(name="adhoc", is_template=False, graph={"nodes": [], "edges": []}),
    ])
    db.commit()
    templates = db.query(Workflow).filter_by(is_template=True).all()
    assert [w.name for w in templates] == ["T1"]


def test_run_cascade_delete(db):
    wf = Workflow(name="wf", graph={"nodes": [], "edges": []})
    db.add(wf)
    db.commit()

    run = Run(workflow_id=wf.id, status="running")
    run.messages.append(Message(conversation_id="1", from_agent="a", to_agent="b", content="hi"))
    run.events.append(RunEvent(type="node_started", payload={"node_id": "start"}))
    db.add(run)
    db.commit()
    rid = run.id

    assert db.query(Message).count() == 1
    assert db.query(RunEvent).count() == 1

    db.delete(db.get(Run, rid))
    db.commit()
    assert db.query(Message).count() == 0
    assert db.query(RunEvent).count() == 0


def test_conversation_unique_constraint(db):
    tenant = Tenant(name="T", slug="t")
    db.add(tenant)
    db.commit()
    agent = Agent(name="Support", tenant_id=tenant.id)
    db.add(agent)
    db.commit()

    # uniqueness is per (tenant_id, channel, external_id)
    db.add(Conversation(tenant_id=tenant.id, channel="telegram", external_id="chat-1", agent_id=agent.id))
    db.commit()

    db.add(Conversation(tenant_id=tenant.id, channel="telegram", external_id="chat-1", agent_id=agent.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_enums_values():
    from app.models.enums import EventType, RunStatus, ToolType, TriggerType

    assert RunStatus.COMPLETED.value == "completed"
    assert TriggerType.SCHEDULE.value == "schedule"
    assert ToolType.HTTP.value == "http"
    assert EventType.RUN_FINISHED.value == "run_finished"


def test_agent_defaults_applied(db):
    """Agent created with only a name → JSON-column defaults materialize on reload."""
    agent = Agent(name="Bare")
    db.add(agent)
    db.commit()
    db.expire_all()
    reloaded = db.get(Agent, agent.id)
    assert reloaded.provider == "groq"
    assert reloaded.channels == []
    assert reloaded.guardrails == {}
    assert reloaded.memory_config == {}
    assert reloaded.schedule is None
