from __future__ import annotations

import ast
import math
import re
from typing import Any, Callable

FORMULA_CALCULATION_SCHEMA_V1 = "mimirq.formula_calculation.v1"

_ALLOWED_FUNCTIONS: dict[str, Callable[..., float]] = {
    "abs": abs,
    "max": max,
    "min": min,
    "round": round,
    "sqrt": math.sqrt,
}


class _FormulaError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _normalize_expression(expression: str) -> str:
    text = re.sub(r"\s+", " ", str(expression or "")).strip()
    return text.replace("^", "**")


def _coerce_number(value: Any, *, name: str) -> float:
    if isinstance(value, bool):
        raise _FormulaError("invalid_variable", f"{name} is boolean")
    try:
        out = float(value)
    except Exception as exc:
        raise _FormulaError("invalid_variable", f"{name} is not numeric") from exc
    if not math.isfinite(out):
        raise _FormulaError("invalid_variable", f"{name} is not finite")
    return out


class _Evaluator(ast.NodeVisitor):
    def __init__(self, variables: dict[str, float]) -> None:
        self.variables = variables
        self.variables_used: set[str] = set()

    def visit_Expression(self, node: ast.Expression) -> float:  # noqa: N802
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> float:  # noqa: N802
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise _FormulaError("unsupported_expression", "only numeric constants are supported")
        return float(node.value)

    def visit_Name(self, node: ast.Name) -> float:  # noqa: N802
        if node.id not in self.variables:
            raise _FormulaError("unknown_variable", f"unknown variable: {node.id}")
        self.variables_used.add(node.id)
        return self.variables[node.id]

    def visit_UnaryOp(self, node: ast.UnaryOp) -> float:  # noqa: N802
        value = self.visit(node.operand)
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
        raise _FormulaError("unsupported_expression", "unsupported unary operator")

    def visit_BinOp(self, node: ast.BinOp) -> float:  # noqa: N802
        left = self.visit(node.left)
        right = self.visit(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise _FormulaError("division_by_zero", "division by zero")
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise _FormulaError("division_by_zero", "modulo by zero")
            return left % right
        raise _FormulaError("unsupported_expression", "unsupported binary operator")

    def visit_Call(self, node: ast.Call) -> float:  # noqa: N802
        if not isinstance(node.func, ast.Name):
            raise _FormulaError("unsupported_expression", "only simple function calls are supported")
        fn = _ALLOWED_FUNCTIONS.get(node.func.id)
        if fn is None:
            raise _FormulaError("unsupported_expression", f"unsupported function: {node.func.id}")
        if node.keywords:
            raise _FormulaError("unsupported_expression", "keyword arguments are not supported")
        args = [self.visit(arg) for arg in node.args]
        try:
            out = float(fn(*args))
        except Exception as exc:
            raise _FormulaError("calculation_failed", str(exc)) from exc
        if not math.isfinite(out):
            raise _FormulaError("calculation_failed", "result is not finite")
        return out

    def generic_visit(self, node: ast.AST) -> float:
        raise _FormulaError("unsupported_expression", f"unsupported node: {node.__class__.__name__}")


def evaluate_formula_expression(
    expression: str,
    *,
    variables: dict[str, Any] | None = None,
    precision: int = 10,
) -> dict[str, Any]:
    normalized = _normalize_expression(expression)
    base: dict[str, Any] = {
        "schema": FORMULA_CALCULATION_SCHEMA_V1,
        "ok": False,
        "value": None,
        "normalized_expression": normalized,
        "variables_used": [],
        "error_code": None,
        "error": None,
    }
    if not normalized:
        return {**base, "error_code": "empty_expression", "error": "empty expression"}
    if len(normalized) > 512:
        return {**base, "error_code": "expression_too_long", "error": "expression too long"}

    coerced_variables: dict[str, float] = {}
    try:
        for key, value in (variables or {}).items():
            name = str(key or "").strip()
            if not name:
                continue
            coerced_variables[name] = _coerce_number(value, name=name)
    except _FormulaError as exc:
        return {**base, "error_code": exc.code, "error": str(exc)}

    try:
        tree = ast.parse(normalized, mode="eval")
        evaluator = _Evaluator(coerced_variables)
        value = evaluator.visit(tree)
    except _FormulaError as exc:
        return {**base, "error_code": exc.code, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {**base, "error_code": "unsupported_expression", "error": str(exc)}

    rounded = round(float(value), max(0, int(precision or 0)))
    return {
        **base,
        "ok": True,
        "value": rounded,
        "variables_used": sorted(evaluator.variables_used),
    }


__all__ = ["FORMULA_CALCULATION_SCHEMA_V1", "evaluate_formula_expression"]
