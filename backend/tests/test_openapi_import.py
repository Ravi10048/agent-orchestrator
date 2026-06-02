"""OpenAPI/Swagger → tools parser + the /api/tools/import endpoint."""
from app.core.tenancy import get_or_create_default_tenant
from app.models import Tool
from app.runtime.tools.openapi_import import parse_openapi

SPEC = {
    "openapi": "3.0.0",
    "servers": [{"url": "https://api.example.com/v1"}],
    "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
    "paths": {
        "/carts/{cart_id}": {
            "get": {
                "operationId": "getCart",
                "summary": "Fetch a cart",
                "parameters": [
                    {"name": "cart_id", "in": "path", "required": True, "schema": {"type": "string"}},
                    {"name": "verbose", "in": "query", "schema": {"type": "boolean"}},
                    {"name": "X-Trace", "in": "header", "schema": {"type": "string"}},
                ],
            }
        },
        "/orders": {
            "post": {
                "operationId": "createOrder",
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {"cart_id": {"type": "string"}, "coupon": {"type": "string"}},
                    "required": ["cart_id"],
                }}}},
            }
        },
    },
}


def test_parse_openapi_maps_operations_to_http_tools():
    tools = {t["name"]: t for t in parse_openapi(SPEC)}
    assert set(tools) == {"get_cart", "create_order"}

    cart = tools["get_cart"]
    assert cart["type"] == "http" and cart["http_method"] == "GET"
    assert cart["endpoint"] == "https://api.example.com/v1/carts/{cart_id}"  # path param stays a placeholder
    assert cart["description"] == "Fetch a cart"
    props = cart["params_schema"]["properties"]
    assert "cart_id" in props and "verbose" in props and "X-Trace" not in props  # header skipped
    assert cart["params_schema"]["required"] == ["cart_id"]  # path param is required
    assert cart["auth"] == {"type": "bearer", "token_env": "IMPORTED_API_TOKEN"}  # scheme detected

    order = tools["create_order"]
    assert order["http_method"] == "POST"
    assert order["endpoint"] == "https://api.example.com/v1/orders"
    assert set(order["params_schema"]["properties"]) == {"cart_id", "coupon"}  # from requestBody
    assert order["params_schema"]["required"] == ["cart_id"]


def test_parse_openapi_base_url_override():
    tools = parse_openapi(SPEC, base_url="http://localhost:8001")
    assert all(t["endpoint"].startswith("http://localhost:8001/") for t in tools)


def test_parse_swagger_2_host_basepath():
    spec = {
        "swagger": "2.0", "host": "api.acme.io", "basePath": "/v2", "schemes": ["https"],
        "paths": {"/ping": {"get": {"operationId": "ping"}}},
    }
    [tool] = parse_openapi(spec)
    assert tool["endpoint"] == "https://api.acme.io/v2/ping" and tool["name"] == "ping"


def test_import_endpoint_creates_tenant_scoped_tools(client, session_factory):
    with session_factory() as db:
        tid = get_or_create_default_tenant(db).id

    r = client.post("/api/tools/import", json={"spec": SPEC})
    assert r.status_code == 201, r.text
    assert {t["name"] for t in r.json()} == {"get_cart", "create_order"}

    # the tools are created in the current tenant and show up in the registry
    names = {t["name"] for t in client.get("/api/tools").json()["items"]}
    assert {"get_cart", "create_order"} <= names
    with session_factory() as db:
        assert db.query(Tool).filter_by(tenant_id=tid, name="get_cart").first() is not None

    # re-import is idempotent (existing names skipped → nothing new created)
    assert client.post("/api/tools/import", json={"spec": SPEC}).json() == []


def test_import_requires_spec_or_url(client):
    assert client.post("/api/tools/import", json={}).status_code == 400


def test_candidate_spec_urls_follows_a_docs_page():
    """A pasted /docs (Swagger-UI) URL should resolve to the real spec — both via the URL embedded
    in the page's HTML and via a conventional sibling fallback."""
    from app.api.routers.tools import _candidate_spec_urls

    html = 'const ui = SwaggerUIBundle({ url: "/openapi.json", dom_id: "#swagger-ui" })'
    cands = _candidate_spec_urls("http://localhost:8002/docs", html)
    assert "http://localhost:8002/openapi.json" in cands          # extracted from the HTML, made absolute
    # even with no embedded URL, the conventional sibling is offered
    assert "http://localhost:8002/openapi.json" in _candidate_spec_urls("http://localhost:8002/docs", "")
