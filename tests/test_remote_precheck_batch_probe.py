from __future__ import annotations

from scripts.remote_precheck_batch_probe import evaluate_precheck_summary


def test_remote_precheck_batch_probe_accepts_short_text_summary_and_samples() -> None:
    summary_body = {
        "total_files": 1,
        "by_file_type": {"md": 1},
        "findings": [
            {"key": "short_text", "count": 1},
        ],
    }
    samples_body = {
        "representative": [
            {
                "name": "sample.md",
                "text_characters": 66,
                "findings": ["short_text"],
            }
        ]
    }

    failures = evaluate_precheck_summary(summary_body, samples_body)

    assert failures == []


def test_remote_precheck_batch_probe_flags_missing_summary_fields() -> None:
    summary_body = {
        "total_files": 0,
        "by_file_type": {},
        "findings": [],
    }
    samples_body = {
        "representative": [],
    }

    failures = evaluate_precheck_summary(summary_body, samples_body)

    assert any("total_files" in item for item in failures)
    assert any("by_file_type.md" in item for item in failures)
    assert any("short_text" in item for item in failures)
    assert any("representative sample" in item for item in failures)
