"""Built-in registry (@builtin) + the execute dispatcher. Every tool runs under a
timeout and NEVER raises to the caller — failures become ToolResult(ok=False) which the
Agent feeds back to the LLM as a tool message (so the agent can recover)."""
import asyncio
import time
from collections.abc import Awaitable, Callable

import jsonschema

from app.runtime.tools.base import ToolContext, ToolResult

BUILTINS: dict[str, Callable[[dict, ToolContext], Awaitable]] = {}


def builtin(key: str):
    def deco(fn):
        BUILTINS[key] = fn
        return fn

    return deco


async def execute_tool_call(tool, args: dict, ctx: ToolContext, timeout: float = 20.0) -> ToolResult:
    t0 = time.perf_counter()
    try:
        _validate_args(tool, args)  # soft JSON-Schema check
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
    except TimeoutError:
        return ToolResult(False, error=f"tool '{tool.name}' timed out after {timeout}s", latency_ms=_ms(t0))
    except Exception as e:  # never let a tool crash the run
        return ToolResult(False, error=f"{type(e).__name__}: {e}", latency_ms=_ms(t0))


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _validate_args(tool, args: dict) -> None:
    """Lenient JSON-Schema check against params_schema; on mismatch raise (the
    dispatcher turns it into an error result rather than calling the tool)."""
    schema = tool.params_schema or {}
    if not schema:
        return
    try:
        jsonschema.validate(args, schema)
    except jsonschema.ValidationError as e:
        raise ValueError(f"invalid args: {e.message}") from None
