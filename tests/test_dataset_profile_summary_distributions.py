from __future__ import annotations

import uuid


def test_dataset_profile_summary_aggregates_language_parse_quality_and_pages() -> None:
    from app.services.dataset_profile_service import aggregate_profile_from_rows

    dataset_id = uuid.uuid4()

    rows = [
        (
            uuid.uuid4(),
            "a.pdf",
            "pdf",
            100,
            "completed",
            0,
            1000,
            None,
            {
                "parse_quality": {"score": 0.05},
                "page_count": 2,
                "governance_enrichment": {"language": "zh"},
            },
        ),
        (
            uuid.uuid4(),
            "b.txt",
            "txt",
            100,
            "completed",
            0,
            1000,
            None,
            {
                "parse_quality": {"score": 0.95},
                "page_count": 10,
                "governance_enrichment": {"language": "en"},
            },
        ),
        (
            uuid.uuid4(),
            "c.txt",
            "txt",
            100,
            "completed",
            0,
            1000,
            None,
            {
                "parse_quality": {"score": 0.55},
                "page_count": 0,
            },
        ),
    ]

    summary = aggregate_profile_from_rows(dataset_id=dataset_id, rows=rows)

    by_label = {b.label: int(b.count or 0) for b in (summary.parse_quality_histogram or [])}
    assert by_label.get("0.0-0.1") == 1
    assert by_label.get("0.5-0.6") == 1
    assert by_label.get("0.9-1.0") == 1

    # Stable keys for UI.
    assert summary.language_mix.get("zh") == 1
    assert summary.language_mix.get("en") == 1
    assert summary.language_mix.get("mixed") == 0
    assert summary.language_mix.get("unknown") == 1

    pages = {b.label: int(b.count or 0) for b in (summary.page_number_histogram or [])}
    assert pages.get("1-2") == 1
    assert pages.get("6-10") == 1

