"""Runs router (LLD 09). POST is async (returns run_id immediately; executor runs as a
background task). Reads are sync/threadpooled. The events endpoint is the WS reconnect/replay
mirror — same envelope shape as /ws/monitor. All reads/writes are scoped to the current tenant."""
from datetime import UTC

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool

from app.api.schemas.common import Page
from app.api.schemas.run import EventEnvelopeOut, MessageOut, RunCreate, RunDetailOut, RunOut
from app.core.deps import current_tenant_id, get_db, get_run_service
from app.core.errors import ConflictError, ResourceNotFound
from app.models import Message, Run, Workflow
from app.models.enums import TriggerType
from app.models.event import RunEvent

router = APIRouter(prefix="/runs", tags=["runs"])


def _get(db, run_id: int, tenant_id: int) -> Run:
    run = db.query(Run).filter_by(id=run_id, tenant_id=tenant_id).first()
    if run is None:
        raise ResourceNotFound("run not found")
    return run


@router.post("", response_model=RunOut, status_code=201)
async def create_run(body: RunCreate, rs=Depends(get_run_service), db=Depends(get_db),
                     tenant_id: int = Depends(current_tenant_id)):
    # the workflow must belong to the current tenant (offload the sync read off the loop)
    wf = await run_in_threadpool(
        lambda: db.query(Workflow).filter_by(id=body.workflow_id, tenant_id=tenant_id).first())
    if wf is None:
        raise ResourceNotFound("workflow not found")
    run_id = await rs.start_run(body.workflow_id, body.input, TriggerType(body.trigger))
    return RunOut.model_validate(await run_in_threadpool(db.get, Run, run_id))


@router.get("", response_model=Page[RunOut])
def list_runs(workflow_id: int | None = Query(None), db=Depends(get_db),
              tenant_id: int = Depends(current_tenant_id),
              limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    q = db.query(Run).filter(Run.tenant_id == tenant_id)
    if workflow_id is not None:
        q = q.filter(Run.workflow_id == workflow_id)
    q = q.order_by(Run.id.desc())
    total = q.count()
    items = [RunOut.model_validate(r) for r in q.limit(limit).offset(offset).all()]
    return Page[RunOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/{run_id}", response_model=RunDetailOut)
def get_run(run_id: int, db=Depends(get_db), tenant_id: int = Depends(current_tenant_id)):
    return RunDetailOut.model_validate(_get(db, run_id, tenant_id))


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: int, rs=Depends(get_run_service), db=Depends(get_db),
                     tenant_id: int = Depends(current_tenant_id)):
    await run_in_threadpool(_get, db, run_id, tenant_id)  # 404s if not this tenant's run
    if not await rs.cancel_run(run_id):
        raise ConflictError("run is not active (already finished or unknown)")
    return {"ok": True}


@router.get("/{run_id}/events", response_model=list[EventEnvelopeOut])
def run_events(run_id: int, after_seq: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=2000),
               db=Depends(get_db), tenant_id: int = Depends(current_tenant_id)):
    _get(db, run_id, tenant_id)
    rows = (db.query(RunEvent).filter(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
            .order_by(RunEvent.seq.asc()).limit(limit).all())
    # RunEvent.ts is naive UTC (SQLite func.now()) → stamp UTC so the client converts to local
    # time consistently with the live (tz-aware) WS stream; otherwise it reads as local + drifts.
    return [EventEnvelopeOut(run_id=r.run_id, seq=r.seq, type=r.type,
                             ts=r.ts.replace(tzinfo=UTC).isoformat() if r.ts else None,
                             event_id=r.id, payload=r.payload)
            for r in rows]


@router.get("/{run_id}/messages", response_model=Page[MessageOut])
def run_messages(run_id: int, db=Depends(get_db), tenant_id: int = Depends(current_tenant_id),
                 limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)):
    _get(db, run_id, tenant_id)
    q = db.query(Message).filter(Message.run_id == run_id).order_by(Message.id.asc())
    total = q.count()
    items = [MessageOut.model_validate(m) for m in q.limit(limit).offset(offset).all()]
    return Page[MessageOut](items=items, total=total, limit=limit, offset=offset)
