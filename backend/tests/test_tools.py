"""LLD 03 — Tool system tests (specs, dispatcher safety, builtins, HTTP, seed)."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.models.tool import Tool
from app.runtime.tools import build_tool_specs, execute_tool_call
from app.runtime.tools.base import ToolContext
from app.runtime.tools.builtins.calculator import _safe_eval
from app.runtime.tools.http_executor import _apply_auth, _render
from app.runtime.tools.registry import BUILTINS
from app.runtime.tools.seed import seed_tools
from app.runtime.tools.spec import to_openai_spec


# ── specs / allow-list ────────────────────────────────────────────────
def test_build_tool_specs_only_mapped():
    t1 = Tool(name="web_fetch", description="fetch a page",
              params_schema={"type": "object", "properties": {"url": {"type": "string"}}})
    t2 = Tool(name="calculator", params_schema={})
    agent = SimpleNamespace(tools=[t1, t2])

    specs = build_tool_specs(agent)
    assert [s["function"]["name"] for s in specs] == ["web_fetch", "calculator"]
    assert specs[0]["type"] == "function"
    assert specs[0]["function"]["parameters"]["properties"]["url"]["type"] == "string"
    # empty schema → defaulted object schema
    assert to_openai_spec(t2)["function"]["parameters"] == {"type": "object", "properties": {}}


# ── dispatcher (never raises) ─────────────────────────────────────────
async def test_execute_builtin_happy_path():
    tool = Tool(name="calculator", type="builtin", builtin_key="calculator", params_schema={})
    res = await execute_tool_call(tool, {"expression": "2+2*3"}, ToolContext())
    assert res.ok and res.output == {"result": 8}
    assert res.latency_ms >= 0


async def test_execute_unknown_builtin():
    tool = Tool(name="x", type="builtin", builtin_key="nope", params_schema={})
    res = await execute_tool_call(tool, {}, ToolContext())
    assert res.ok is False and "not registered" in res.error


async def test_execute_unknown_type():
    tool = Tool(name="x", type="weird", params_schema={})
    res = await execute_tool_call(tool, {}, ToolContext())
    assert res.ok is False and "unknown tool type" in res.error


async def test_execute_timeout():
    async def _slow(args, ctx):
        await asyncio.sleep(1.0)

    BUILTINS["_slow"] = _slow
    tool = Tool(name="slow", type="builtin", builtin_key="_slow", params_schema={})
    res = await execute_tool_call(tool, {}, ToolContext(), timeout=0.05)
    assert res.ok is False and "timed out" in res.error


async def test_execute_raising_tool_never_raises():
    async def _boom(args, ctx):
        raise RuntimeError("boom")

    BUILTINS["_boom"] = _boom
    tool = Tool(name="boom", type="builtin", builtin_key="_boom", params_schema={})
    res = await execute_tool_call(tool, {}, ToolContext())
    assert res.ok is False and "boom" in res.error


async def test_execute_bad_args_rejected():
    schema = {"type": "object", "properties": {"x": {"type": "number"}}, "required": ["x"]}
    tool = Tool(name="needs_x", type="builtin", builtin_key="calculator", params_schema=schema)
    res = await execute_tool_call(tool, {}, ToolContext())  # missing required 'x'
    assert res.ok is False and "invalid args" in res.error


# ── calculator AST safety ─────────────────────────────────────────────
def test_calculator_safe_eval():
    assert _safe_eval("2+2*3") == 8
    assert _safe_eval("(1+2)**3") == 27
    assert _safe_eval("-5 + 3") == -2
    with pytest.raises(ValueError):
        _safe_eval("__import__('os').system('ls')")
    with pytest.raises(ValueError):
        _safe_eval("len('abc')")


# ── HTTP executor ─────────────────────────────────────────────────────
def test_http_render_and_auth(monkeypatch):
    assert _render("https://api.x/users/{user_id}", {"user_id": 7}) == "https://api.x/users/7"
    headers: dict = {}
    monkeypatch.setenv("MY_TOKEN", "secret123")
    _apply_auth(headers, {"type": "bearer", "token_env": "MY_TOKEN"})
    assert headers["Authorization"] == "Bearer secret123"
    headers2: dict = {}
    _apply_auth(headers2, {"type": "header", "name": "X-Api-Key", "value": "literal"})
    assert headers2["X-Api-Key"] == "literal"


async def test_http_execute_get_with_template_and_query(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"path": request.url.path,
                                         "q": dict(request.url.params)})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: real_client(transport=transport))

    tool = Tool(name="get_user", type="http", http_method="GET",
                endpoint="https://api.x/users/{user_id}", params_schema={})
    res = await execute_tool_call(tool, {"user_id": 7, "verbose": "1"}, ToolContext())

    assert res.ok and res.output["status"] == 200
    assert res.output["body"]["path"] == "/users/7"          # template filled
    assert res.output["body"]["q"] == {"verbose": "1"}       # leftover arg → query param


# ── seed (idempotent) ─────────────────────────────────────────────────
def test_seed_tools_idempotent(db):
    assert seed_tools(db) == 3
    assert db.query(Tool).count() == 3
    assert seed_tools(db) == 0  # re-run upserts, no new rows
    assert db.query(Tool).count() == 3
    wf = db.query(Tool).filter_by(name="web_fetch").first()
    assert wf.builtin_key == "web_fetch" and wf.type == "builtin"
