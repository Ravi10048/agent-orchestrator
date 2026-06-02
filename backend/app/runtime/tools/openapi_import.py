"""Parse an OpenAPI / Swagger spec into HTTP Tool definitions (no-code tool import).

Each operation (path × method) becomes one HTTP tool:
  • name        — operationId (snake_cased), else a `method_path` slug (unique within the import)
  • description — summary → description → "METHOD /path"
  • endpoint    — base URL + path, with path params LEFT as `{placeholders}`
  • params_schema — a JSON-Schema built from the operation's path + query params + JSON requestBody

Our `http_executor` already routes args by location at call time (`{placeholders}`→URL path, leftover
GET args→query string, POST/PUT/PATCH args→JSON body), so we do NOT need to persist each param's
`in:` location — keeping path params as placeholders in the endpoint is enough.

Supports OpenAPI 3.x (servers[].url) and Swagger 2.0 (schemes+host+basePath); resolves `$ref`
(cycle-guarded). Clean-room: the approach is informed by the OpenAPI spec + the company toolregistry's
parsing logic, but no code was copied.
"""
import re
from urllib.parse import urlparse

_METHODS = ("get", "post", "put", "patch", "delete")


def parse_openapi(spec: dict, *, base_url: str | None = None, source_url: str | None = None) -> list[dict]:
    """Return a list of Tool-creation dicts (name/description/type/http_method/endpoint/params_schema/auth).

    `base_url` overrides the spec's server URL. If the resolved base is empty or relative (e.g. a
    FastAPI spec with no `servers`), it's made absolute against `source_url`'s origin (the URL the
    spec was fetched from) — so imported tools get a callable absolute endpoint."""
    base = base_url or _base_url(spec) or ""
    if source_url and (not base or base.startswith("/")):
        base = _origin(source_url) + base
    base = base.rstrip("/")
    tools: list[dict] = []
    seen: set[str] = set()
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method in _METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            tools.append({
                "name": _unique(_tool_name(op, method, path), seen),
                "description": op.get("summary") or op.get("description") or f"{method.upper()} {path}",
                "type": "http",
                "http_method": method.upper(),
                "endpoint": f"{base}{path}",  # path params stay as {placeholders}
                "params_schema": _params_schema(spec, item, op),
                "auth": _auth(spec),
                "body_template": None,
            })
    return tools


# ── base URL ──────────────────────────────────────────────────────────
def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""


def _base_url(spec: dict) -> str:
    servers = spec.get("servers")
    if isinstance(servers, list) and servers and isinstance(servers[0], dict):
        return str(servers[0].get("url") or "")
    if spec.get("host"):  # Swagger 2.0
        scheme = (spec.get("schemes") or ["https"])[0]
        return f"{scheme}://{spec['host']}{spec.get('basePath', '')}"
    return ""


# ── naming ──────────────────────────────────────────────────────────────
def _tool_name(op: dict, method: str, path: str) -> str:
    op_id = op.get("operationId")
    if op_id:
        s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", op_id)  # camelCase → camel_Case
        s = re.sub(r"[^0-9a-zA-Z]+", "_", s).lower().strip("_")
        if s:
            return s
    parts = [p for p in re.split(r"[^0-9a-zA-Z]+", path) if p]  # braces are non-alnum → dropped
    return "_".join([method, *parts]) or method


def _unique(name: str, seen: set[str]) -> str:
    candidate, i = name, 2
    while candidate in seen:
        candidate, i = f"{name}_{i}", i + 1
    seen.add(candidate)
    return candidate


# ── $ref resolution (cycle-guarded) ──────────────────────────────────────
def _resolve(spec: dict, node, _seen: frozenset[str] = frozenset()):
    if isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if ref in _seen:
            return {}
        target = spec
        for part in ref.lstrip("#/").split("/"):
            target = target.get(part, {}) if isinstance(target, dict) else {}
        return _resolve(spec, target, _seen | {ref})
    return node


# ── parameters → JSON-Schema ──────────────────────────────────────────────
def _prop(spec: dict, schema: dict, description: str | None) -> dict:
    schema = _resolve(spec, schema) or {}
    out: dict = {"type": schema.get("type", "string")}
    if description:
        out["description"] = description
    for k in ("enum", "format"):
        if schema.get(k) is not None:
            out[k] = schema[k]
    return out


def _params_schema(spec: dict, path_item: dict, op: dict) -> dict:
    props: dict = {}
    required: list[str] = []
    params = [_resolve(spec, p) for p in (path_item.get("parameters") or []) + (op.get("parameters") or [])]

    for p in params:
        loc = p.get("in")
        name = p.get("name")
        if not name:
            continue
        if loc in ("path", "query"):  # header/cookie skipped (usually auth)
            props[name] = _prop(spec, p.get("schema") or {}, p.get("description"))
            if p.get("required") or loc == "path":  # path params are always required
                required.append(name)
        elif loc == "body":  # Swagger 2.0 body
            _merge_body(spec, _resolve(spec, p.get("schema") or {}), props, required)

    body = _resolve(spec, op.get("requestBody") or {})  # OpenAPI 3 body
    content = body.get("content") or {}
    media = content.get("application/json") or (next(iter(content.values()), {}) if content else {})
    _merge_body(spec, _resolve(spec, (media or {}).get("schema") or {}), props, required)

    return {"type": "object", "properties": props, "required": required}


def _merge_body(spec: dict, body_schema: dict, props: dict, required: list[str]) -> None:
    for name, sch in (body_schema.get("properties") or {}).items():
        props[name] = _prop(spec, sch, _resolve(spec, sch).get("description"))
    for r in body_schema.get("required") or []:
        if r not in required:
            required.append(r)


# ── auth (scheme only; secrets are env-var NAMES the user fills) ──────────
def _auth(spec: dict) -> dict | None:
    schemes = (spec.get("components") or {}).get("securitySchemes") or spec.get("securityDefinitions") or {}
    scheme = next((s for s in schemes.values() if isinstance(s, dict)), None)
    if not scheme:
        return None
    kind = (scheme.get("type") or "").lower()
    if kind == "apikey":
        return {"type": "header", "name": scheme.get("name", "X-API-Key"), "value_env": "IMPORTED_API_KEY"}
    if kind in ("oauth2", "http") or scheme.get("scheme") == "bearer":
        return {"type": "bearer", "token_env": "IMPORTED_API_TOKEN"}
    return None
