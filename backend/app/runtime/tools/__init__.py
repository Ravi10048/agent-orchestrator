"""Tool system public API (LLD 03)."""
from app.runtime.tools import builtins  # noqa: F401 — registers @builtin functions on import
from app.runtime.tools.base import ToolContext, ToolResult
from app.runtime.tools.registry import execute_tool_call
from app.runtime.tools.seed import seed_tools
from app.runtime.tools.spec import build_tool_specs, to_openai_spec

__all__ = [
    "build_tool_specs",
    "to_openai_spec",
    "execute_tool_call",
    "ToolContext",
    "ToolResult",
    "seed_tools",
]
