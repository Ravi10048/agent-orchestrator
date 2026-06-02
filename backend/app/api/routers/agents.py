"""Agents router (LLD 09). CRUD is sync (threadpooled); /test is async (LLM call).
All reads/writes are scoped to the current tenant (multi-tenant isolation)."""
from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool

from app.api.schemas.agent import (
    AgentCreate,
    AgentOut,
    AgentTest,
    AgentTestDraft,
    AgentTestResult,
    AgentToolsUpdate,
    AgentUpdate,
)
from app.api.schemas.common import Page, ScheduleDTO
from app.api.serializers import agent_out
from app.core.deps import current_tenant_id, get_db, get_scheduler
from app.core.errors import ResourceNotFound
from app.models import Agent, Tool
from app.runtime.agent import AgentInput, AgentRunner
from app.runtime.agent_spec import AgentSpec, build_agent_spec
from app.runtime.scheduler import validate_schedule

router = APIRouter(prefix="/agents", tags=["agents"])


def _get(db, agent_id: int, tenant_id: int) -> Agent:
    agent = db.query(Agent).filter_by(id=agent_id, tenant_id=tenant_id).first()
    if agent is None:
        raise ResourceNotFound("agent not found")
    return agent


@router.get("", response_model=Page[AgentOut])
def list_agents(db=Depends(get_db), tenant_id: int = Depends(current_tenant_id),
                limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    q = db.query(Agent).filter(Agent.tenant_id == tenant_id).order_by(Agent.id.desc())
    total = q.count()
    items = [agent_out(a) for a in q.limit(limit).offset(offset).all()]
    return Page[AgentOut](items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=AgentOut, status_code=201)
def create_agent(body: AgentCreate, db=Depends(get_db), scheduler=Depends(get_scheduler),
                 tenant_id: int = Depends(current_tenant_id)):
    schedule = body.schedule.model_dump() if body.schedule else None
    if schedule and schedule.get("enabled"):
        validate_schedule(schedule)  # → 400 BEFORE persisting
    agent = Agent(
        tenant_id=tenant_id,
        name=body.name, role=body.role, system_prompt=body.system_prompt,
        provider=body.provider, model=body.model, channels=body.channels,
        guardrails=body.guardrails.model_dump(), memory_config=body.memory_config.model_dump(),
        schedule=schedule,
    )
    if body.tool_ids:  # only this tenant's tools
        agent.tools = db.query(Tool).filter(Tool.tenant_id == tenant_id, Tool.id.in_(body.tool_ids)).all()
    db.add(agent)
    db.commit()
    db.refresh(agent)
    if schedule:
        scheduler.upsert_agent_schedule(agent)  # AFTER commit
    return agent_out(agent)


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: int, db=Depends(get_db), tenant_id: int = Depends(current_tenant_id)):
    return agent_out(_get(db, agent_id, tenant_id))


@router.patch("/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: int, body: AgentUpdate, db=Depends(get_db),
                 tenant_id: int = Depends(current_tenant_id)):
    agent = _get(db, agent_id, tenant_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(agent, k, v)
    db.commit()
    db.refresh(agent)
    return agent_out(agent)


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: int, db=Depends(get_db), scheduler=Depends(get_scheduler),
                 tenant_id: int = Depends(current_tenant_id)):
    agent = _get(db, agent_id, tenant_id)
    scheduler.remove_agent_schedule(agent_id)
    db.delete(agent)
    db.commit()


@router.put("/{agent_id}/tools", response_model=AgentOut)
def set_agent_tools(agent_id: int, body: AgentToolsUpdate, db=Depends(get_db),
                    tenant_id: int = Depends(current_tenant_id)):
    agent = _get(db, agent_id, tenant_id)
    agent.tools = (db.query(Tool).filter(Tool.tenant_id == tenant_id, Tool.id.in_(body.tool_ids)).all()
                   if body.tool_ids else [])
    db.commit()
    db.refresh(agent)
    return agent_out(agent)


@router.put("/{agent_id}/schedule", response_model=AgentOut)
def set_agent_schedule(agent_id: int, body: ScheduleDTO, db=Depends(get_db),
                       scheduler=Depends(get_scheduler), tenant_id: int = Depends(current_tenant_id)):
    agent = _get(db, agent_id, tenant_id)
    schedule = body.model_dump()
    validate_schedule(schedule)  # → 400 BEFORE persisting
    agent.schedule = schedule
    db.commit()
    db.refresh(agent)
    scheduler.upsert_agent_schedule(agent)
    return agent_out(agent)


@router.post("/test", response_model=AgentTestResult)
async def test_agent_draft(body: AgentTestDraft, db=Depends(get_db),
                           tenant_id: int = Depends(current_tenant_id)):
    """Run the in-progress (UNSAVED) agent config 1:1 — nothing is persisted. Powers the editor's
    Test box so it reflects the live form, and works for not-yet-created agents. Tools are resolved
    from the current tenant by id."""
    tools = await run_in_threadpool(
        lambda: db.query(Tool).filter(Tool.tenant_id == tenant_id, Tool.id.in_(body.tool_ids)).all()
        if body.tool_ids else [])
    spec = AgentSpec(
        name=body.name or "Draft agent", role=body.role or "", system_prompt=body.system_prompt or "",
        provider=body.provider or "groq", model=body.model, tools=list(tools),
        guardrails=body.guardrails.model_dump(), memory_config=body.memory_config.model_dump(),
    )
    result = await AgentRunner(spec).run(AgentInput(input=body.message))  # 1:1, no persist
    return AgentTestResult(reply=result.text, stopped_reason=result.stopped_reason,
                           total_tokens=result.usage.total_tokens, est_cost_usd=result.usage.est_cost_usd)


@router.post("/{agent_id}/test", response_model=AgentTestResult)
async def test_agent(agent_id: int, body: AgentTest, db=Depends(get_db),
                     tenant_id: int = Depends(current_tenant_id)):
    agent = await run_in_threadpool(_get, db, agent_id, tenant_id)  # offload sync read off the loop
    spec = build_agent_spec(agent)
    result = await AgentRunner(spec).run(AgentInput(input=body.message))  # 1:1, no persist
    return AgentTestResult(reply=result.text, stopped_reason=result.stopped_reason,
                           total_tokens=result.usage.total_tokens, est_cost_usd=result.usage.est_cost_usd)
