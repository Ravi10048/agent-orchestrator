"""Safe arithmetic via an AST whitelist (no eval, no names/calls/attributes)."""
import ast
import operator

from app.runtime.tools.registry import builtin

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(expr: str):
    return _ev(ast.parse(expr, mode="eval").body)


def _ev(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_ev(node.left), _ev(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_ev(node.operand))
    raise ValueError(f"disallowed expression: {type(node).__name__}")


@builtin("calculator")
async def calculator(args, ctx):
    return {"result": _safe_eval(args["expression"])}
