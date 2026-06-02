"""API router aggregator — everything under /api (LLD 09)."""
from fastapi import APIRouter

from app.api.routers import agents, conversations, meta, runs, tenants, tools, workflows

api_router = APIRouter(prefix="/api")
api_router.include_router(tenants.router)
# NOTE: the demo mock IKEA/payments API is NOT mounted here — it runs as a SEPARATE service on its
# own port (app/mock_api.py, `make mock`), so the IKEA HTTP tools call a genuinely external API.
api_router.include_router(agents.router)
api_router.include_router(tools.router)
api_router.include_router(workflows.router)
api_router.include_router(workflows.templates_router)  # GET /api/templates (sugar)
api_router.include_router(runs.router)
api_router.include_router(conversations.router)
api_router.include_router(meta.router)
