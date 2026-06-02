"""FastAPI dependencies (LLD 09). Services live on app.state (wired in lifespan)."""
from fastapi import Depends, Request

from app.core.db import SessionLocal
from app.core.tenancy import resolve_tenant_id


def get_db():
    """Request-scoped DB session. CRUD handlers are sync `def`, so FastAPI runs them in a
    threadpool — concurrent and non-blocking for the event loop."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_tenant_id(request: Request, db=Depends(get_db)) -> int:
    """The tenant every request is scoped to — from the `X-Tenant-Id` header, else the default
    tenant. (Per-tenant JWT auth is the production next-step; this is the v1 isolation hook.)"""
    return resolve_tenant_id(db, request.headers.get("X-Tenant-Id"))


def get_run_service(request: Request):
    return request.app.state.run_service


def get_scheduler(request: Request):
    return request.app.state.scheduler


def get_hub(request: Request):
    return request.app.state.hub
