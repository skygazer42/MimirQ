from __future__ import annotations

from app.rag.core.formula_calculator import evaluate_formula_expression


def test_formula_calculator_evaluates_controlled_numeric_expression() -> None:
    result = evaluate_formula_expression(
        "revenue / cost * 100",
        variables={"revenue": 120, "cost": 80},
    )

    assert result["ok"] is True
    assert result["value"] == 150.0
    assert result["variables_used"] == ["cost", "revenue"]
    assert result["normalized_expression"] == "revenue / cost * 100"


def test_formula_calculator_supports_power_and_safe_functions() -> None:
    result = evaluate_formula_expression(
        "sqrt(a^2 + b^2)",
        variables={"a": 3, "b": 4},
    )

    assert result["ok"] is True
    assert result["value"] == 5.0
    assert result["variables_used"] == ["a", "b"]


def test_formula_calculator_rejects_unsafe_expressions() -> None:
    result = evaluate_formula_expression("__import__('os').system('echo bad')", variables={})

    assert result["ok"] is False
    assert result["value"] is None
    assert result["error_code"] == "unsupported_expression"


def test_formula_calculator_reports_invalid_variables_without_raising() -> None:
    result = evaluate_formula_expression("revenue + 1", variables={"revenue": "not-a-number"})

    assert result["ok"] is False
    assert result["value"] is None
    assert result["error_code"] == "invalid_variable"
