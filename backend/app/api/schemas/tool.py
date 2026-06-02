"""Tool DTOs (LLD 09)."""
from datetime import datetime
from typing import Any

from pydantic import Field

from app.api.schemas.common import AuthDTO, OutModel, StrictModel

_SECRET_KEYS = {"token", "value", "password", "secret", "key"}
# header names that commonly carry credentials → mask their values in API responses
_SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "api-key"}


def redact_auth(auth: dict | None) -> dict | None:
    """Strip any raw secret values, keeping only env-var names / structure (defence in depth —
    the API never accepts raw secrets, but a hand-seeded row might carry one)."""
    if not auth:
        return auth
    return {k: ("***" if k in _SECRET_KEYS else v) for k, v in auth.items()}


def redact_headers(headers: dict | None) -> dict | None:
    """Mask credential-bearing header values (Authorization, X-Api-Key, *-token/-secret/-key, …)
    so a header secret can't leak back out of a tool/agent read endpoint."""
    if not headers:
        return headers

    def _sensitive(name: str) -> bool:
        n = name.lower()
        return n in _SECRET_HEADERS or n.endswith(("-token", "-secret", "-key"))

    return {k: ("***" if _sensitive(k) else v) for k, v in headers.items()}


class ToolCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    type: str = "http"  # builtin | http
    params_schema: dict = Field(default_factory=dict)
    builtin_key: str | None = None
    http_method: str | None = None
    endpoint: str | None = None
    headers: dict | None = None
    auth: AuthDTO | None = None
    body_template: dict | None = None


class ToolImportIn(StrictModel):
    """Import HTTP tools from an OpenAPI / Swagger spec. Paste the spec as `spec`, or give a `url`
    to fetch it from (e.g. a service's /openapi.json). `base_url` overrides the spec's server URL
    so you can point the generated tools at your own host."""
    spec: dict | None = None
    url: str | None = None
    base_url: str | None = None


class ToolUpdate(StrictModel):
    description: str | None = None
    params_schema: dict | None = None
    http_method: str | None = None
    endpoint: str | None = None
    headers: dict | None = None
    auth: AuthDTO | None = None
    body_template: dict | None = None


class ToolOut(OutModel):
    id: int
    name: str
    description: str
    type: str
    params_schema: dict
    builtin_key: str | None
    http_method: str | None
    endpoint: str | None
    headers: dict | None
    auth: dict | None
    body_template: dict | None
    created_at: datetime
    updated_at: datetime


class ToolTest(StrictModel):
    args: dict = Field(default_factory=dict)


class ToolTestResult(OutModel):
    ok: bool
    output: Any = None
    error: str | None = None
    latency_ms: int = 0
