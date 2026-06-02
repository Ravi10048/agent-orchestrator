"""Tools router (LLD 09). Sync `def` handlers → threadpooled (non-blocking).
Tools are tenant-scoped — each tenant has its own tools (incl. its own default builtins)."""
import re
from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool

from app.api.schemas.common import Page
from app.api.schemas.tool import ToolCreate, ToolImportIn, ToolOut, ToolTest, ToolTestResult, ToolUpdate
from app.api.serializers import tool_out
from app.core.deps import current_tenant_id, get_db
from app.core.errors import BadRequest, ConflictError, ResourceNotFound
from app.models import Tool
from app.models.agent import agent_tools
from app.runtime.tools.base import ToolContext
from app.runtime.tools.openapi_import import parse_openapi
from app.runtime.tools.registry import execute_tool_call

router = APIRouter(prefix="/tools", tags=["tools"])


def _looks_like_spec(d: object) -> bool:
    return isinstance(d, dict) and ("openapi" in d or "swagger" in d or "paths" in d)


def _parse_spec_text(text: str) -> dict | None:
    """Parse spec text as JSON, then YAML; return the dict or None (not a spec / unparseable)."""
    import json

    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        import yaml

        v = yaml.safe_load(text)
        return v if isinstance(v, dict) else None
    except Exception:
        return None


def _candidate_spec_urls(page_url: str, html: str) -> list[str]:
    """Given a docs / Swagger-UI page (HTML), find likely spec URLs: ones EMBEDDED in the page
    (Swagger UI `url:`, Redoc `spec-url`, Scalar `data-url`, or any *openapi*/*swagger*.json|yaml),
    plus conventional siblings (…/openapi.json). All resolved absolute against the page URL."""
    cands: list[str] = re.findall(r'(?:spec-url|data-url|\burl)\s*[:=]\s*["\']([^"\']+)["\']', html)
    cands += re.findall(r'["\']([^"\']*(?:openapi|swagger)[^"\']*\.(?:json|ya?ml))["\']', html)
    stripped = re.sub(r"/(docs|api-?docs|swagger(?:-ui)?|redoc)/?$", "", urlparse(page_url).path)
    cands += ["/openapi.json", "/swagger.json", "/openapi.yaml", f"{stripped}/openapi.json", "/api/openapi.json"]
    out, seen = [], set()
    for c in cands:
        full = urljoin(page_url, c)
        if full and full != page_url and full not in seen:
            seen.add(full)
            out.append(full)
    return out


def _fetch_spec(url: str) -> dict:
    """Fetch an OpenAPI spec from a URL. Accepts the spec itself (JSON or YAML) OR a Swagger-UI /
    docs page — in which case it follows the page to the real spec (the spec URL is embedded in the
    HTML), so users can paste either `.../openapi.json` or `.../docs`."""
    import httpx

    try:
        r = httpx.get(url, timeout=10, follow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        raise BadRequest(f"could not fetch the OpenAPI spec from url: {e}") from e

    spec = _parse_spec_text(r.text)
    if _looks_like_spec(spec):
        return spec  # the URL was the spec itself

    for cand in _candidate_spec_urls(url, r.text):  # the URL was a docs page → follow it to the spec
        try:
            rr = httpx.get(cand, timeout=10, follow_redirects=True)
            if rr.status_code == 200 and _looks_like_spec(s := _parse_spec_text(rr.text)):
                return s
        except Exception:
            continue
    raise BadRequest(
        "couldn't find an OpenAPI spec at that URL. Point it at the spec itself "
        "(e.g. …/openapi.json) — not the Swagger UI page (…/docs)."
    )


def _get(db, tool_id: int, tenant_id: int) -> Tool:
    tool = db.query(Tool).filter_by(id=tool_id, tenant_id=tenant_id).first()
    if tool is None:
        raise ResourceNotFound("tool not found")
    return tool


@router.get("", response_model=Page[ToolOut])
def list_tools(db=Depends(get_db), tenant_id: int = Depends(current_tenant_id),
               limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    q = db.query(Tool).filter(Tool.tenant_id == tenant_id).order_by(Tool.id.asc())
    total = q.count()
    items = [tool_out(t) for t in q.limit(limit).offset(offset).all()]
    return Page[ToolOut](items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=ToolOut, status_code=201)
def create_tool(body: ToolCreate, db=Depends(get_db), tenant_id: int = Depends(current_tenant_id)):
    if db.query(Tool).filter_by(tenant_id=tenant_id, name=body.name).first():
        raise ConflictError(f"tool '{body.name}' already exists")
    tool = Tool(
        tenant_id=tenant_id,
        name=body.name, description=body.description, type=body.type,
        params_schema=body.params_schema, builtin_key=body.builtin_key,
        http_method=body.http_method, endpoint=body.endpoint, headers=body.headers,
        auth=body.auth.model_dump() if body.auth else None, body_template=body.body_template,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool_out(tool)


@router.post("/import", response_model=list[ToolOut], status_code=201)
def import_tools(body: ToolImportIn, db=Depends(get_db), tenant_id: int = Depends(current_tenant_id)):
    """Import HTTP tools from an OpenAPI/Swagger spec — one tool per operation, into this tenant.
    Idempotent: operation names already present in the tenant are skipped."""
    spec = body.spec or (_fetch_spec(body.url) if body.url else None)
    if not isinstance(spec, dict) or not spec:
        raise BadRequest("provide an OpenAPI spec (`spec`) or a `url` to fetch it from")
    defs = parse_openapi(spec, base_url=body.base_url, source_url=body.url)
    if not defs:
        raise BadRequest("no operations found in the spec")
    created = []
    for d in defs:
        if db.query(Tool).filter_by(tenant_id=tenant_id, name=d["name"]).first():
            continue  # name already taken in this tenant → skip (idempotent re-import)
        tool = Tool(tenant_id=tenant_id, **d)
        db.add(tool)
        created.append(tool)
    db.commit()
    for t in created:
        db.refresh(t)
    return [tool_out(t) for t in created]


@router.get("/{tool_id}", response_model=ToolOut)
def get_tool(tool_id: int, db=Depends(get_db), tenant_id: int = Depends(current_tenant_id)):
    return tool_out(_get(db, tool_id, tenant_id))


@router.patch("/{tool_id}", response_model=ToolOut)
def update_tool(tool_id: int, body: ToolUpdate, db=Depends(get_db),
                tenant_id: int = Depends(current_tenant_id)):
    tool = _get(db, tool_id, tenant_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(tool, k, v)
    db.commit()
    db.refresh(tool)
    return tool_out(tool)


@router.delete("/{tool_id}", status_code=204)
def delete_tool(tool_id: int, force: bool = Query(False), db=Depends(get_db),
                tenant_id: int = Depends(current_tenant_id)):
    tool = _get(db, tool_id, tenant_id)
    mapped = db.query(agent_tools).filter(agent_tools.c.tool_id == tool_id).count()
    if mapped and not force:
        raise ConflictError(f"tool is mapped to {mapped} agent(s); pass ?force=true to delete")
    db.delete(tool)
    db.commit()


@router.post("/{tool_id}/test", response_model=ToolTestResult)
async def test_tool(tool_id: int, body: ToolTest, db=Depends(get_db),
                    tenant_id: int = Depends(current_tenant_id)):
    tool = await run_in_threadpool(_get, db, tool_id, tenant_id)  # offload sync read off the loop
    result = await execute_tool_call(tool, body.args, ToolContext())
    return ToolTestResult(ok=result.ok, output=result.output, error=result.error,
                          latency_ms=result.latency_ms)
