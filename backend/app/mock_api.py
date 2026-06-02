"""Standalone MOCK IKEA / payments API — runs on its OWN port (default 8001), separate from the
orchestrator. This makes the orchestrator's HTTP tools hit a genuinely EXTERNAL service (like the
real IKEA / Razorpay APIs would be), instead of the backend calling itself.

Being a FastAPI app, it auto-publishes its schema at /openapi.json — so you can IMPORT it as tools:
    POST /api/tools/import  {"url": "http://localhost:8001/openapi.json"}
…which creates one HTTP tool per endpoint (get_cart, generate_payment_link, …) in the current tenant.

Run:  make mock     (or:  cd backend && uvicorn app.mock_api:app --port 8001)
"""
from fastapi import FastAPI

from app.api.routers.mock import router

app = FastAPI(
    title="Mock IKEA / Payments API",
    version="1.0.0",
    description="Demo stand-in endpoints the IKEA cart-recovery tools call. Not real IKEA/Razorpay.",
)
app.include_router(router)


@app.get("/", include_in_schema=False)
def _root():
    return {"ok": True, "service": "mock-ikea-api", "openapi": "/openapi.json", "endpoints": "/mock/*"}


if __name__ == "__main__":  # convenience: python -m app.mock_api
    import uvicorn

    uvicorn.run("app.mock_api:app", host="0.0.0.0", port=8001)
