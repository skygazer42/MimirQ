from __future__ import annotations

from pathlib import Path


def test_retrieval_quality_issue_template_exists_and_has_required_fields() -> None:
    path = Path(".github/ISSUE_TEMPLATE/retrieval-quality-regression.yml")
    text = path.read_text(encoding="utf-8")

    assert "name: Retrieval Quality Regression" in text
    assert "- retrieval" in text
    assert "- regression" in text
    assert "id: query" in text
    assert "id: dataset_scope" in text
    assert "id: retrieval_profile" in text
    assert "id: expected_citations" in text
    assert "id: regression_artifacts" in text
    assert "required: true" in text
