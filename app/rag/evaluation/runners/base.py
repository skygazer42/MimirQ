
from typing import Any

from app.rag.evaluation.results.schema import normalize_eval_result_row


def build_runner_result(**payload: Any) -> dict[str, Any]:
    return normalize_eval_result_row(dict(payload))
