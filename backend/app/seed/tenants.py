"""Tenant creation + bootstrap (multi-tenant SaaS).

A NEW tenant is bootstrapped with the default builtin **tools** only (web_fetch / calculator /
send_message) — NOT any agents. The user then creates their own agents and composes workflows: a
workflow only ROUTES when the user adds an agent connected to >= 2 other agents (that agent becomes
the router; the executor passes the workflow's connected sub-agents to it at runtime). The supervisor
is therefore not a forced/default agent — it's just whatever agent the user puts in the routing
position. The seeded demo tenants (Acme, IKEA) ship with full agent teams as worked examples."""
import re

from app.models.tenant import Tenant
from app.runtime.tools.seed import seed_tools


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "tenant"


def get_or_create_tenant(db, name: str, *, slug: str | None = None, is_default: bool = False) -> Tenant:
    """Idempotent by slug. Returns the existing tenant or a freshly-created one."""
    slug = slug or _slugify(name)
    tenant = db.query(Tenant).filter_by(slug=slug).first()
    if tenant is None:
        tenant = Tenant(name=name, slug=slug, is_default=is_default)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
    return tenant


def bootstrap_tenant(db, tenant_id: int) -> None:
    """Give a new tenant its own copies of the default builtin tools (idempotent). No agents — the
    user builds those; routing emerges from how they compose a workflow."""
    seed_tools(db, tenant_id=tenant_id)  # web_fetch, calculator, send_telegram


def create_tenant(db, name: str) -> Tenant:
    """Create a tenant and bootstrap it with the default tools."""
    tenant = get_or_create_tenant(db, name)
    bootstrap_tenant(db, tenant.id)
    return tenant
