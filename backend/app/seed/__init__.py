"""Seed entrypoint (LLD 09 lifespan calls run_seed; `python -m app.seed` for `make seed`).

Multi-tenant: the demo content is seeded into the **"Acme Support"** tenant (the default). Order
matters: **tenant → tools → agents → templates**. Each step upserts by a unique key scoped to the
tenant, so the whole thing is idempotent and safe to run on every startup. Templates are validated
at seed time (see seed/templates). (A second, sample tenant is added in seed/sample_tenant.py.)"""
from app.runtime.tools.seed import seed_tools
from app.seed.agents import seed_agents
from app.seed.sample_tenant import seed_sample_tenant
from app.seed.templates import seed_templates
from app.seed.tenants import get_or_create_tenant


def run_seed(db) -> dict:
    # the default "Acme Support" tenant (the generic agents/templates) ...
    tenant = get_or_create_tenant(db, "Acme Support", slug="acme", is_default=True)
    tools = seed_tools(db, tenant_id=tenant.id)
    agents = seed_agents(db, tenant.id)
    templates = seed_templates(db, tenant.id)
    seed_sample_tenant(db)  # ... + a sample 2nd tenant (the "Riya" IKEA cart-recovery use case)
    return {"tools": tools, "agents": agents, "templates": templates}
