from __future__ import annotations

from pathlib import Path


def test_contributing_links_retrieval_pr_checklist() -> None:
    text = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "retrieval_pr_checklist" in text


def test_retrieval_pr_checklist_includes_regression_evidence_requirements() -> None:
    text = Path("docs/contributing/retrieval_pr_checklist.md").read_text(encoding="utf-8")
    lower = text.lower()
    assert "ablation" in lower or "regression" in lower
    assert "regression_gate.py" in text or "run_sample_retrieval_benchmark.py" in text
