
import pytest


def test_aggregate_must_recall_summary_from_explicit_counts() -> None:
    from app.services.report_service import _aggregate_must_recall_summary

    out = _aggregate_must_recall_summary(
        latest_regression_summary={
            "must_recall_pass_rate": 0.8,
            "must_recall_cases_total": 10,
            "must_recall_cases_passed": 8,
            "must_recall_cases_failed": 2,
        }
    )
    assert out is not None
    assert out.pass_rate == pytest.approx(0.8)
    assert out.cases_total == 10
    assert out.cases_passed == 8
    assert out.cases_failed == 2
    assert out.status == "degraded"


def test_aggregate_must_recall_summary_derives_counts_from_rate_and_total() -> None:
    from app.services.report_service import _aggregate_must_recall_summary

    out = _aggregate_must_recall_summary(
        latest_regression_summary={
            "must_recall_pass_rate": 1.0,
            "retrieval_items_total": 5,
        }
    )
    assert out is not None
    assert out.pass_rate == pytest.approx(1.0)
    assert out.cases_total == 5
    assert out.cases_passed == 5
    assert out.cases_failed == 0
    assert out.status == "healthy"
