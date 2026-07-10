
from typing import Any


def compute_routing_accuracy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = 0
    correct = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        expected = row.get("expected_route")
        if expected in (None, ""):
            continue
        evaluated += 1
        if row.get("actual_route") == expected:
            correct += 1
    accuracy = 0.0 if evaluated <= 0 else round(correct / evaluated, 4)
    return {"evaluated": evaluated, "correct": correct, "routing_accuracy": accuracy}
