from __future__ import annotations

from scripts import remote_kg_quality_report_probe as mod


def test_quality_report_is_acceptable_requires_scope_and_summary_counts() -> None:
    report = {
        "summary": {"documents": 1, "events": 1, "entities": 2},
        "scope": {"documents_sampled": 1, "documents_allowed": 1},
    }

    failures = mod.validate_quality_report(report)

    assert failures == []


def test_quality_report_is_acceptable_flags_missing_scope_or_summary() -> None:
    report = {
        "summary": {"documents": 0, "events": 0, "entities": 0},
        "scope": {"documents_sampled": 0, "documents_allowed": 0},
    }

    failures = mod.validate_quality_report(report)

    assert any("summary.documents" in item for item in failures)
    assert any("summary.events" in item for item in failures)
    assert any("scope.documents_allowed" in item for item in failures)
