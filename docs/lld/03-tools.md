# LLD 03 — Tool system

> Tool registry + custom tools + agent↔tool mapping (mirrors the platform tool-registry pattern). Depends on [LLD 01](01-data-model.md) (`Tool`, `agent_tools`) and [LLD 02](02-llm-gateway.md) (tool specs go in `LLMRequest.tools`). Used by the Agent ([LLD 05](05-agent.md)). Status: **for review**.

## Responsibility
Turn `Tool` records into **OpenAI function specs** the LLM can call, and **execute** the tool calls the LLM emits — for two tool types:
- **`builtin`** — a registered Python function (seeded: `web_fetch`, `calculator`, `send_telegram`).
- **`http`** — a **user-defined REST call** created in the UI with no code (method, URL template, headers/auth, body mapping).

An agent only ever sees/executes the tools **mapped to it** (`agent.tools` — the allow-list, = the PDF's "skills"). The runtime *executes real tools* (the "not a UI mockup" requirement).

## Files
```
backend/app/runtime/tools/
  __init__.py          # public: build_tool_specs(agent), execute_tool_call(tool, args, ctx)
  base.py              # ToolResult, ToolContext
  spec.py              # Tool row → OpenAI function spec
  registry.py          # BUILTINS registry (@builtin) + dispatcher
  http_executor.py     # generic HTTP tool execution (template, auth, body)
  builtins/
    web_fetch.py · calculator.py · send_telegram.py
  seed.py              # seed Tool rows for the 3 built-ins (idempotent)
```

## Core types — `tools/base.py`
```python
from dataclasses import dataclass
from typing import Any

@dataclass
class ToolResult:
    ok: bool
    output: Any = None          # JSON-serialisable
    error: str | None = None
    latency_ms: int = 0

@dataclass
class ToolContext:              # what channel-/run-aware tools need
    run_id: int | None = None
    conversation_id: str | None = None
    chat_id: str | None = None  # e.g. Telegram chat → used by send_telegram
    agent_name: str = ""
```

## Advertise tools to the LLM — `tools/spec.py`
```python
def to_openai_spec(tool) -> dict:
    return {"type": "function", "function": {
        "name": tool.name,
        "description": tool.description or "",
        "parameters": tool.params_schema or {"type": "object", "properties": {}},
    }}

def build_tool_specs(agent) -> list[dict]:
    # ONLY the agent's mapped tools (allow-list / "skills")
    return [to_openai_spec(t) for t in agent.tools]
```
`Tool.params_schema` is JSON-Schema, passed straight through as the function `parameters` — so the same schema validates args (below) *and* tells the LLM what to send. Single source of truth.

## Built-in registry + dispatcher — `tools/registry.py`
```python
import asyncio, time
from typing import Awaitable, Callable
from app.runtime.tools.base import ToolResult, ToolContext

BUILTINS: dict[str, Callable[[dict, ToolContext], Awaitable]] = {}

def builtin(key: str):
    def deco(fn): BUILTINS[key] = fn; return fn
    return deco

async def execute_tool_call(tool, args: dict, ctx: ToolContext, timeout: float = 20.0) -> ToolResult:
    t0 = time.perf_counter()
    try:
        _validate_args(tool, args)                       # soft JSON-Schema check
        if tool.type == "builtin":
            fn = BUILTINS.get(tool.builtin_key or "")
            if not fn:
                return ToolResult(False, error=f"builtin '{tool.builtin_key}' not registered")
            out = await asyncio.wait_for(fn(args, ctx), timeout)
        elif tool.type == "http":
            from app.runtime.tools.http_executor import http_execute
            out = await asyncio.wait_for(http_execute(tool, args, ctx, timeout), timeout)
        else:
            return ToolResult(False, error=f"unknown tool type '{tool.type}'")
        return ToolResult(True, output=out, latency_ms=_ms(t0))
    except asyncio.TimeoutError:
        return ToolResult(False, error=f"tool '{tool.name}' timed out after {timeout}s", latency_ms=_ms(t0))
    except Exception as e:                                # never let a tool crash the run
        return ToolResult(False, error=f"{type(e).__name__}: {e}", latency_ms=_ms(t0))
```
- **Every tool runs under a timeout** and **never raises** to the caller — a bad tool returns `ToolResult(ok=False, error=...)`, which the Agent feeds back to the LLM as a tool message (so the agent can recover or apologise).
- `_validate_args` uses `jsonschema` against `params_schema` (lenient: on mismatch, return an error result rather than calling the tool).

## HTTP tool execution — `tools/http_executor.py`
```python
import os, httpx

async def http_execute(tool, args: dict, ctx, timeout: float) -> dict:
    url = _render(tool.endpoint, args)                  # "{placeholders}" filled from args
    method = (tool.http_method or "GET").upper()
    headers = dict(tool.headers or {})
    _apply_auth(headers, tool.auth or {})               # bearer/header/basic — secrets via env
    json_body = _render_body(tool.body_template, args) if method in ("POST","PUT","PATCH") else None
    params = _leftover_args(tool, args) if method == "GET" else None
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.request(method, url, headers=headers, params=params, json=json_body)
    return {"status": r.status_code, "ok": r.is_success,
            "body": _safe_body(r)}                       # json if parseable else text (truncated)

def _apply_auth(headers, auth):
    t = auth.get("type")
    if t == "bearer":
        token = os.getenv(auth["token_env"]) if auth.get("token_env") else auth.get("token")
        headers["Authorization"] = f"Bearer {token}"
    elif t == "header":
        val = os.getenv(auth["value_env"]) if auth.get("value_env") else auth.get("value")
        headers[auth["name"]] = val
    # type == "basic" → httpx BasicAuth (omitted for brevity); "none"/missing → no auth
```
- **URL template**: `https://api.x.com/users/{user_id}` → `{user_id}` filled from `args`; leftover args become query params (GET) or are merged via `body_template` (writes).
- **Secrets via env** (`token_env`/`value_env`), not stored in the DB in plaintext — a deliberate security choice (and a clean talking point).

## Seed built-ins — `tools/builtins/*` + `tools/seed.py`
```python
# web_fetch.py
@builtin("web_fetch")
async def web_fetch(args, ctx):
    import httpx
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.get(args["url"])
    return {"status": r.status_code, "text": r.text[:4000]}   # truncated

# calculator.py — safe arithmetic (AST whitelist, no eval())
@builtin("calculator")
async def calculator(args, ctx):
    return {"result": _safe_eval(args["expression"])}         # +,-,*,/,**,(),numbers only

# send_telegram.py — replies on the current chat (channel-aware via ctx.chat_id)
@builtin("send_telegram")
async def send_telegram(args, ctx):
    from app.channels import get_channel
    await get_channel("telegram").send(ctx.chat_id, args["text"])
    return {"sent": True}
```
`seed.py` inserts/updates the corresponding `Tool` rows (idempotent, by unique `name`) so they appear in the registry/UI with the right `params_schema`, e.g.:
```python
SEED = [
  dict(name="web_fetch", type="builtin", builtin_key="web_fetch",
       description="Fetch the text of a web page.",
       params_schema={"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}),
  dict(name="calculator", type="builtin", builtin_key="calculator",
       description="Evaluate a math expression.",
       params_schema={"type":"object","properties":{"expression":{"type":"string"}},"required":["expression"]}),
  dict(name="send_telegram", type="builtin", builtin_key="send_telegram",
       description="Send a message to the current Telegram chat.",
       params_schema={"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}),
]
```

## How the Agent (LLD 05) uses it — the tool loop
```python
specs = build_tool_specs(agent)                  # allow-list of this agent's tools
res = await llm.complete(LLMRequest(messages=msgs, tools=specs, ...))
for call in res.tool_calls:                      # call.name, call.arguments(dict)
    tool = tools_by_name.get(call.name)          # resolved from agent.tools ONLY (enforces allow-list)
    if not tool:
        result = ToolResult(False, error=f"tool '{call.name}' not allowed for this agent")
    else:
        result = await execute_tool_call(tool, call.arguments, ctx)
    msgs.append({"role":"tool","tool_call_id":call.id,"content":json.dumps(result.output or result.error)})
    emit(TOOL_CALL, {...})                        # → live monitor + RunEvent
# loop back to the LLM with tool results until it returns a final text (guardrail-capped)
```
Allow-list is enforced here (resolve names only within `agent.tools`); the executor stays generic.

## "How to add a tool" (the challenge asks for this — goes in README)
- **HTTP tool (no code):** create a `Tool` in the UI → set `type=http`, `endpoint` (with `{placeholders}`), `http_method`, `params_schema`, optional `headers`/`auth` → map it to an agent. Done.
- **Built-in tool (code):** add an `@builtin("key")` async function in `tools/builtins/`, add a `seed.py` entry (or create the `Tool` row via UI with `builtin_key="key"`). Done.

## Security notes (prototype-level, documented as prod next-steps)
- **SSRF**: HTTP tools call user-supplied URLs. Prototype: timeout + no internal use. Prod: domain allow-list + block private/link-local IPs.
- **Secrets**: tool auth tokens read from **env**, not stored plaintext in the DB.
- **Sandboxing**: `calculator` uses an AST whitelist (no `eval`); built-ins are trusted code; HTTP tools can't execute code.
- **Allow-list**: agents can only call their mapped tools.

## Tests (`backend/tests/test_tools.py`)
- `to_openai_spec` / `build_tool_specs` → only mapped tools, correct shape.
- `execute_tool_call` builtin happy path; unknown `builtin_key` → `ok=False`; timeout → `ok=False`; raising tool → `ok=False` (never raises).
- `calculator` safe-eval (allows `2+2*3`, rejects `__import__`).
- HTTP executor: URL template render, auth header injection (env), `httpx.MockTransport` for a fake endpoint.
- **Critical-path "message delivery"** partly covered by `send_telegram` (full path in LLD 07).

## Decisions / tradeoffs
- **`params_schema` is the single source of truth** — it's both the LLM-advertised `parameters` and the arg validator. No duplication.
- **Two tool types only** (`builtin` + `http`) — covers "real tools" + fully-configurable custom tools without the complexity of the platform's AI-generated-Lua approach (which we deliberately *don't* port — it's company IP and overkill here). HTTP-from-the-UI is the lean equivalent of "define a tool → map to agent → runtime executes."
- **Executor never raises**; failures become tool messages the agent can recover from — important for an autonomous multi-agent loop.
- **Channel-aware tools via `ToolContext`** (e.g. `send_telegram` uses `ctx.chat_id`) — keeps tools decoupled from the channel layer (lazy import of the channel registry).
- **Allow-list enforced in the Agent**, executor stays generic and reusable.

---
*Next: [LLD 04 — Message Bus](04-message-bus.md). Reply "go" to continue, or flag changes.*
