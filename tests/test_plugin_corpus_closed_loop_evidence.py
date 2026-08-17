
from scripts.plugin_corpus_closed_loop_evidence import _failed_checks


def _thresholds(**overrides: float) -> dict[str, float]:
    values = {
        "min_expected_metadata_hit_rate": 1.0,
        "min_expected_metadata_recall": 1.0,
        "min_retrieval_recall": 1.0,
        "min_retrieval_hit_at_3": 0.8,
        "min_citation_accuracy": 0.0,
        "min_citation_coverage": 0.0,
    }
    values.update(overrides)
    return values


def test_failed_checks_accepts_metrics_at_exact_thresholds() -> None:
    failed = _failed_checks(
        summary={"uploaded_count": 1, "document_count": 1, "completed_documents": 1},
        documents=[{"status": "completed", "chunk_total": 1}],
        golden={
            "case_ids": ["case-1"],
            "import_result": {"errors": []},
            "summary": {
                "retrieval_recall": 1.0,
                "retrieval_hit_at_3": 0.8,
                "expected_metadata_cases_total": 1,
                "expected_metadata_fields_total": 1,
                "expected_metadata_hit_rate": 1.0,
                "expected_metadata_recall": 1.0,
                "citation_accuracy": 0.5,
                "citation_coverage": 0.5,
                "citation_eval_limit_avg": 1,
                "citation_evaluated_count_avg": 1,
                "citation_total_count_avg": 1,
            },
        },
        **_thresholds(min_citation_accuracy=0.5, min_citation_coverage=0.5),
    )

    assert failed == []


def test_failed_checks_preserves_complete_failure_order() -> None:
    failed = _failed_checks(
        summary={"uploaded_count": 0, "document_count": 2, "completed_documents": 1},
        documents=[{"status": "failed", "chunk_total": 0}, "invalid"],
        golden={"import_result": {"errors": ["broken"]}, "summary": {}},
        **_thresholds(min_citation_accuracy=0.5, min_citation_coverage=0.5),
    )

    assert failed == [
        "uploaded_count",
        "completed_documents",
        "document_chunks",
        "golden_import_errors",
        "golden_case_count",
        "retrieval_recall",
        "retrieval_hit_at_3",
        "expected_metadata_cases_total",
        "expected_metadata_fields_total",
        "expected_metadata_hit_rate",
        "expected_metadata_recall",
        "citation_eval_window",
        "citation_accuracy",
        "citation_coverage",
    ]


def test_zero_citation_thresholds_disable_only_the_window_requirement() -> None:
    failed = _failed_checks(
        summary={"uploaded_count": 1, "document_count": 1, "completed_documents": 1},
        documents=[{"chunk_total": 1}],
        golden={
            "import_result": {"created": 1, "errors": []},
            "summary": {
                "retrieval_recall": 1,
                "retrieval_hit_at_3": 1,
                "expected_metadata_cases_total": 1,
                "expected_metadata_fields_total": 1,
                "expected_metadata_hit_rate": 1,
                "expected_metadata_recall": 1,
            },
        },
        **_thresholds(),
    )

    assert failed == []
