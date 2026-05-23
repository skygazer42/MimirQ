from __future__ import annotations

from pathlib import Path


def test_run_regression_ragas_evaluation_does_not_shadow_dbdocument() -> None:
    text = Path("app/rag/evaluation/ragas.py").read_text(encoding="utf-8")
    _, fn_body = text.split("def run_regression_ragas_evaluation(", 1)

    assert "from app.models.document import Document as DBDocument" not in fn_body
