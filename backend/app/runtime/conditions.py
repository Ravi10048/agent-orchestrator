"""The ONE safe condition evaluator (LLD 06). AST-whitelist — no eval/exec, no calls, no
dunder/attribute escapes. Supports: `last.intent == "billing"`, `attempts < 3`,
`input.foo in [...]`, and `and/or/not`. Any malformed/illegal expr → False (the default
edge then carries the run forward, so routing never crashes)."""
import ast
import operator
from dataclasses import dataclass, field

_ALLOWED = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
    ast.Compare, ast.Name, ast.Load, ast.Constant, ast.Attribute,
    ast.Subscript, ast.List, ast.Tuple,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
)
_ROOTS = {"last", "input", "attempts"}
# JSON-style literals so authors (and LLM-generated JSON flags) can write `== true/false/null`
_NAME_LITERALS = {"true": True, "false": False, "null": None}
_CMP = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
}


@dataclass
class EvalContext:
    last: dict = field(default_factory=dict)
    input: dict = field(default_factory=dict)
    attempts: int = 0


def eval_condition(expr: str | None, ctx: EvalContext) -> bool:
    if expr in (None, "", "else"):
        return True
    try:
        tree = ast.parse(expr, mode="eval")
        for n in ast.walk(tree):
            if not isinstance(n, _ALLOWED):
                raise ValueError(type(n).__name__)
            if isinstance(n, ast.Name) and n.id not in _ROOTS and n.id not in _NAME_LITERALS:
                raise ValueError(f"name {n.id}")
            if isinstance(n, ast.Attribute) and n.attr.startswith("_"):
                raise ValueError("dunder")
        return bool(_ev(tree.body, ctx))
    except Exception:
        return False  # routing must never crash; the default edge handles it


def _ev(node, ctx: EvalContext):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in _NAME_LITERALS:
            return _NAME_LITERALS[node.id]
        return getattr(ctx, node.id, None)
    if isinstance(node, ast.Attribute):
        base = _ev(node.value, ctx)
        return base.get(node.attr) if isinstance(base, dict) else getattr(base, node.attr, None)
    if isinstance(node, ast.Subscript):
        return _ev_subscript(node, ctx)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_ev(e, ctx) for e in node.elts]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _ev(node.operand, ctx)
    if isinstance(node, ast.BoolOp):
        return _ev_bool(node, ctx)
    if isinstance(node, ast.Compare):
        return _ev_compare(node, ctx)
    raise ValueError(f"unsupported node {type(node).__name__}")


def _ev_subscript(node, ctx: EvalContext):
    base = _ev(node.value, ctx)
    key = _ev(node.slice, ctx)
    try:
        return base.get(key) if isinstance(base, dict) else base[key]
    except Exception:
        return None


def _ev_bool(node, ctx: EvalContext):
    vals = [_ev(v, ctx) for v in node.values]
    return all(vals) if isinstance(node.op, ast.And) else any(vals)


def _ev_compare(node, ctx: EvalContext):
    left = _ev(node.left, ctx)
    for op, comp_node in zip(node.ops, node.comparators, strict=True):
        right = _ev(comp_node, ctx)
        if not _cmp(op, left, right):
            return False
        left = right
    return True


def _cmp(op, a, b) -> bool:
    if isinstance(op, ast.In):
        return a in b
    if isinstance(op, ast.NotIn):
        return a not in b
    fn = _CMP.get(type(op))
    if fn is None:
        raise ValueError("bad comparator")
    return fn(a, b)
