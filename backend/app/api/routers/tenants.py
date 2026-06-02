"""Tenants router (multi-tenant SaaS). Listing the tenants powers the UI's tenant switcher;
creating one bootstraps it with a default Supervisor + the default builtin tools."""
from fastapi import APIRouter, Depends

from app.api.schemas.tenant import TenantCreate, TenantOut
from app.core.deps import get_db
from app.core.errors import ResourceNotFound
from app.models import Tenant
from app.seed.tenants import create_tenant

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("", response_model=list[TenantOut])
def list_tenants(db=Depends(get_db)):
    return [TenantOut.model_validate(t) for t in db.query(Tenant).order_by(Tenant.id.asc()).all()]


@router.post("", response_model=TenantOut, status_code=201)
def create_tenant_endpoint(body: TenantCreate, db=Depends(get_db)):
    return TenantOut.model_validate(create_tenant(db, body.name))


@router.get("/{tenant_id}", response_model=TenantOut)
def get_tenant(tenant_id: int, db=Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise ResourceNotFound("tenant not found")
    return TenantOut.model_validate(tenant)
