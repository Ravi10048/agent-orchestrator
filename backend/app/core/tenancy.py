"""Multi-tenant scoping helpers (LLD 01 extension).

The current tenant is resolved from the `X-Tenant-Id` request header; if absent (or non-numeric),
we fall back to the default tenant — auto-created on first access so the app and tests always have
one to scope to. All owned rows (agents, tools, workflows, runs, conversations) filter by tenant_id.
"""
from app.models.tenant import Tenant

DEFAULT_SLUG = "default"


def get_or_create_default_tenant(db) -> Tenant:
    """The fallback tenant: the one flagged is_default, else the earliest, else a freshly-created one."""
    t = (
        db.query(Tenant).filter_by(is_default=True).first()
        or db.query(Tenant).order_by(Tenant.id.asc()).first()
    )
    if t is None:
        t = Tenant(name="Default", slug=DEFAULT_SLUG, is_default=True)
        db.add(t)
        db.commit()
        db.refresh(t)
    return t


def resolve_tenant_id(db, header_value: str | None) -> int:
    """Header value → tenant id, else the default tenant's id."""
    if header_value and header_value.isdigit():
        return int(header_value)
    return get_or_create_default_tenant(db).id
