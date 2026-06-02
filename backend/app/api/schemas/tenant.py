"""Tenant DTOs (multi-tenant SaaS)."""
from datetime import datetime

from pydantic import Field

from app.api.schemas.common import OutModel, StrictModel


class TenantCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)


class TenantOut(OutModel):
    id: int
    name: str
    slug: str
    is_default: bool
    created_at: datetime
