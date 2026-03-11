from __future__ import annotations

import uuid

from app.services.dataset_profile_service import aggregate_profile_from_rows


def _row(
    *,
    filename: str,
    file_type: str,
    file_size: int = 0,
    status: str = "completed",
    chunk_count: int = 0,
    total_characters: int = 0,
    error_message: str | None = None,
    metadata: dict | None = None,
):
    return (
        uuid.uuid4(),  # id
        filename,
        file_type,
        file_size,
        status,
        chunk_count,
        total_characters,
        error_message,
        metadata or {},
    )


def test_dataset_profile_recall_risk_hints_short_chunks_and_low_lexical_diversity() -> None:
    dsid = uuid.uuid4()
    rows = [
        _row(
            filename="a.md",
            file_type="md",
            chunk_count=40,
            total_characters=10_000,
            metadata={
                "chunking_stats_tokens": {
                    "histogram": [
                        {"label": "0-50", "count": 32},
                        {"label": "50-100", "count": 16},
                        {"label": "200-400", "count": 4},
                    ]
                },
                "chunk_quality_gate": {
                    "grade": "warn",
                    "reason_items": [
                        {"code": "many_duplicates", "severity": "warning", "message": "many duplicates"},
                    ],
                },
            },
        ),
        _row(
            filename="b.md",
            file_type="md",
            chunk_count=35,
            total_characters=8_000,
            metadata={
                "chunking_stats_tokens": {
                    "histogram": [
                        {"label": "0-50", "count": 28},
                        {"label": "50-100", "count": 14},
                        {"label": "200-400", "count": 3},
                    ]
                },
                "chunk_quality_gate": {
                    "grade": "warn",
                    "reason_items": [
                        {"code": "too_many_duplicates", "severity": "error", "message": "too many duplicates"},
                    ],
                },
            },
        ),
    ]

    summary = aggregate_profile_from_rows(dataset_id=dsid, rows=rows)
    hints = {h.key: h for h in (summary.recall_risk_hints or [])}

    assert "short_chunks_heavy" in hints
    assert int(hints["short_chunks_heavy"].observed.get("short_chunk_pct") or 0) >= 70

    assert "low_lexical_diversity" in hints
    assert int(hints["low_lexical_diversity"].observed.get("duplicate_docs_pct") or 0) >= 50


def test_dataset_profile_recall_risk_hints_low_text_quality_signal() -> None:
    dsid = uuid.uuid4()
    rows = [
        _row(
            filename="a.pdf",
            file_type="pdf",
            status="completed",
            total_characters=600,
            metadata={
                "parsed_text_quality": {"density": 0.04},
                "parse_quality": {"score": 0.2},
            },
        ),
        _row(
            filename="b.pdf",
            file_type="pdf",
            status="completed",
            total_characters=500,
            metadata={
                "parsed_text_quality": {"density": 0.06},
                "parse_quality": {"score": 0.25},
            },
        ),
    ]

    summary = aggregate_profile_from_rows(dataset_id=dsid, rows=rows, density_threshold=0.12)
    hints = {h.key: h for h in (summary.recall_risk_hints or [])}

    assert "low_text_quality" in hints
    assert int(hints["low_text_quality"].observed.get("affected_docs_pct") or 0) >= 50
