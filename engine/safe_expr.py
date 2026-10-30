"""Safe evaluator for the routing expressions in domain packs.

Replaces `eval`. Only comparisons, boolean logic, arithmetic, names (extracted fields)
and constants are allowed. Anything else (calls, attribute access, subscripts, lambdas,
comprehensions) raises UnsafeExpression, so a pack file cannot run code.
"""

from __future__ import annotations

import ast
import operator as op

_BIN = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv}
_CMP = {ast.Lt: op.lt, ast.LtE: op.le, ast.Gt: op.gt, ast.GtE: op.ge, ast.Eq: op.eq, ast.NotEq: op.ne}


class UnsafeExpression(ValueError):
    pass


def evaluate(expr: str, names: dict):
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise UnsafeExpression(f"invalid expression: {expr!r}") from e
    return _ev(tree.body, names)


def _ev(n: ast.AST, names: dict):
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float, str, bool, type(None))):
        return n.value
    if isinstance(n, ast.Name):
        if n.id in ("True", "False", "None"):
            return {"True": True, "False": False, "None": None}[n.id]
        return names[n.id]  # KeyError -> caller treats the rule as not applicable
    if isinstance(n, ast.BoolOp):
        vals = (_ev(v, names) for v in n.values)
        return all(vals) if isinstance(n.op, ast.And) else any(vals)
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
        return not _ev(n.operand, names)
    if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
        return _BIN[type(n.op)](_ev(n.left, names), _ev(n.right, names))
    if isinstance(n, ast.Compare) and all(type(o) in _CMP for o in n.ops):
        left = _ev(n.left, names)
        for o, comp in zip(n.ops, n.comparators):
            right = _ev(comp, names)
            if not _CMP[type(o)](left, right):
                return False
            left = right
        return True
    raise UnsafeExpression(f"disallowed syntax: {type(n).__name__}")
