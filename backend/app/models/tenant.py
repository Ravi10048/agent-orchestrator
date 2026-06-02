from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Tenant(Base):
    """A customer / organization on the platform (multi-tenant SaaS). A tenant OWNS its own
    agents, tools, workflows, runs, and conversations — nothing is shared across tenants. Every
    owned row carries a nullable `tenant_id`; the API scopes all reads/writes to the current tenant
    (resolved from the `X-Tenant-Id` header, else the default tenant). Per-tenant JWT auth is the
    documented production next-step; row-level scoping is the v1 isolation model."""

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
