"""Workflows router (LLD 09). validate_graph is the single source of truth (LLD 06).
All reads/writes are scoped to the current tenant."""
from copy import deepcopy

from fastapi import APIRouter, Depends, Query

from app.api.schemas.common import Page
from app.api.schemas.workflow import (
    InstantiateBody,
    ValidateResult,
    WorkflowCreate,
    WorkflowOut,
    WorkflowUpdate,
    WorkflowValidateBody,
)
from app.core.deps import current_tenant_id, get_db, get_run_service
from app.core.errors import ResourceNotFound
from app.models import Workflow
from app.runtime.executor import GraphValidationError

router = APIRouter(prefix="/workflows", tags=["workflows"])
templates_router = APIRouter(tags=["workflows"])  # exposes GET /templates (sugar)


def _get(db, wf_id: int, tenant_id: int) -> Workflow:
    wf = db.query(Workflow).filter_by(id=wf_id, tenant_id=tenant_id).first()
    if wf is None:
        raise ResourceNotFound("workflow not found")
    return wf


@router.get("", response_model=Page[WorkflowOut])
def list_workflows(is_template: bool | None = Query(None), db=Depends(get_db),
                   tenant_id: int = Depends(current_tenant_id),
                   limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    q = db.query(Workflow).filter(Workflow.tenant_id == tenant_id)
    if is_template is not None:
        q = q.filter(Workflow.is_template == is_template)
    q = q.order_by(Workflow.id.desc())
    total = q.count()
    items = [WorkflowOut.model_validate(w) for w in q.limit(limit).offset(offset).all()]
    return Page[WorkflowOut](items=items, total=total, limit=limit, offset=offset)


@templates_router.get("/templates", response_model=list[WorkflowOut])
def list_templates(db=Depends(get_db), tenant_id: int = Depends(current_tenant_id)):
    rows = (db.query(Workflow).filter_by(tenant_id=tenant_id, is_template=True)
            .order_by(Workflow.id.asc()).all())
    return [WorkflowOut.model_validate(w) for w in rows]


@router.post("", response_model=WorkflowOut, status_code=201)
def create_workflow(body: WorkflowCreate, db=Depends(get_db), rs=Depends(get_run_service),
                    tenant_id: int = Depends(current_tenant_id)):
    graph = body.graph.to_graph()
    if not body.is_template:  # templates are seeded/trusted
        rs.executor.validate_graph(graph, db)  # raises GraphValidationError → 400
    wf = Workflow(tenant_id=tenant_id, name=body.name, description=body.description,
                  graph=graph, is_template=body.is_template)
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return WorkflowOut.model_validate(wf)


@router.post("/validate", response_model=ValidateResult)
def validate_workflow(body: WorkflowValidateBody, db=Depends(get_db), rs=Depends(get_run_service)):
    try:
        rs.executor.validate_graph(body.graph.to_graph(), db)
        return ValidateResult(valid=True, errors=[])
    except GraphValidationError as e:
        return ValidateResult(valid=False, errors=e.errors)  # 200 — it's a check, not a failure


@router.get("/{wf_id}", response_model=WorkflowOut)
def get_workflow(wf_id: int, db=Depends(get_db), tenant_id: int = Depends(current_tenant_id)):
    return WorkflowOut.model_validate(_get(db, wf_id, tenant_id))


@router.put("/{wf_id}", response_model=WorkflowOut)
def update_workflow(wf_id: int, body: WorkflowUpdate, db=Depends(get_db), rs=Depends(get_run_service),
                    tenant_id: int = Depends(current_tenant_id)):
    wf = _get(db, wf_id, tenant_id)
    data = body.model_dump(exclude_unset=True)
    if body.graph is not None:
        graph = body.graph.to_graph()
        if not wf.is_template:
            rs.executor.validate_graph(graph, db)
        wf.graph = graph
    data.pop("graph", None)
    for k, v in data.items():
        setattr(wf, k, v)
    db.commit()
    db.refresh(wf)
    return WorkflowOut.model_validate(wf)


@router.post("/{wf_id}/save-as-template", response_model=WorkflowOut)
def save_as_template(wf_id: int, db=Depends(get_db), tenant_id: int = Depends(current_tenant_id)):
    """Publish a workflow as a reusable template — a separate is_template=True copy (non-destructive
    to the source, so its runs + channel routing bindings are untouched). IDEMPOTENT per (tenant,
    name): re-publishing the same-named workflow UPDATES its existing template instead of creating a
    duplicate, so clicking twice can't litter the org with copies."""
    src = _get(db, wf_id, tenant_id)
    existing = (db.query(Workflow)
                .filter_by(tenant_id=tenant_id, is_template=True, name=src.name).first())
    if existing is not None:
        existing.graph = deepcopy(src.graph)
        existing.description = src.description
        db.commit()
        db.refresh(existing)
        return WorkflowOut.model_validate(existing)
    tpl = Workflow(tenant_id=tenant_id, name=src.name, description=src.description,
                   graph=deepcopy(src.graph), is_template=True)
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return WorkflowOut.model_validate(tpl)


@router.post("/{wf_id}/instantiate", response_model=WorkflowOut, status_code=201)
def instantiate_workflow(wf_id: int, body: InstantiateBody, db=Depends(get_db),
                         tenant_id: int = Depends(current_tenant_id)):
    tpl = _get(db, wf_id, tenant_id)
    copy = Workflow(tenant_id=tenant_id, name=body.name or f"{tpl.name} (copy)",
                    description=tpl.description, graph=deepcopy(tpl.graph), is_template=False)
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return WorkflowOut.model_validate(copy)


@router.delete("/{wf_id}", status_code=204)
def delete_workflow(wf_id: int, db=Depends(get_db), tenant_id: int = Depends(current_tenant_id)):
    db.delete(_get(db, wf_id, tenant_id))
    db.commit()
