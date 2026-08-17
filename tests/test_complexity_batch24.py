from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import dataset_analysis_service, dataset_profile_service
from app.services.db_catalog_schema_doc_service import (
    extract_schema_from_markdown,
    render_virtual_schema_markdown,
)


class _IterableQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def with_entities(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def execution_options(self, **_kwargs):
        return self

    def enable_eagerloads(self, *_args, **_kwargs):
        return self

    def yield_per(self, *_args, **_kwargs):
        return self

    def __iter__(self):
        return iter(self._rows)


class _PreviewQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._rows)


class _PreviewDB:
    def __init__(self, preview_rows):
        self._preview_rows = list(preview_rows)

    def query(self, *_args, **_kwargs):
        return _PreviewQuery(self._preview_rows)


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._rows)


class _FakeAnalysisDB:
    def __init__(self, *, conversations=None, messages=None, feedback_rows=None):
        self._rows = {
            dataset_analysis_service.Conversation: list(conversations or []),
            dataset_analysis_service.Message: list(messages or []),
            dataset_analysis_service.MessageFeedback: list(feedback_rows or []),
        }

    def query(self, model):
        return _FakeQuery(self._rows.get(model, []))


def test_virtual_schema_markdown_round_trips_columns_and_omits_non_safe_profile_values() -> None:
    markdown = render_virtual_schema_markdown(
        dataset_id="dataset-1",
        generated_at_iso="2026-08-16T08:00:00+00:00",
        tables=[
            {
                "engine": "postgres",
                "db_name": "crm",
                "schema_name": "public",
                "table_name": "customers",
                "table_type": "table",
                "comment": "Customer records",
                "columns": [
                    {"ordinal": 2, "name": "email", "data_type": "text", "nullable": False, "comment": "login"},
                    {"ordinal": 1, "name": "id", "data_type": "uuid", "nullable": False, "comment": "pk"},
                ],
                "profile": {
                    "row_count_estimate": 42,
                    "sample_rows": [{"email": "secret@example.com"}],
                },
            }
        ],
    )

    assert "row_count_estimate" in markdown
    assert "sample_rows" not in markdown
    assert "secret@example.com" not in markdown
    assert extract_schema_from_markdown(markdown) == {
        "crm.public.customers": {
            "columns": {
                "id": {"data_type": "uuid", "nullable": False},
                "email": {"data_type": "text", "nullable": False},
            }
        }
    }


def test_aggregate_profile_from_rows_keeps_findings_duplicate_counts_and_language_buckets() -> None:
    dataset_id = uuid4()
    shared_sha = "a" * 64
    rows = [
        (
            uuid4(),
            "scan.pdf",
            "pdf",
            120,
            "failed",
            2,
            80,
            "preprocess_failed: bad encoding",
            {
                "source_path": "Invoices/2026/scan.pdf",
                "language": "zh-CN",
                "parsed_text_quality": {"density": 0.05},
                "parse_quality": {"score": 0.2},
                "seal_summary": {"detected": True, "primary_score": 0.1},
                "image_count": 3,
                "chunk_coverage": {"coverage_ratio": 0.5, "overlap_waste_ratio": 0.25},
                "chunk_quality_gate": {"grade": "fail", "reason_items": [{"code": "many_duplicates"}]},
                "governance_pii_hits": {"email": 2},
                "governance_secrets_hits": {"token": 1},
                "near_dedup": {"dropped": 1},
                "file_sha256": shared_sha,
            },
        ),
        (
            uuid4(),
            "notes.txt",
            "txt",
            40,
            "completed",
            1,
            40,
            None,
            {
                "source_path": "root/notes.txt",
                "language": "en",
                "file_sha256": shared_sha,
            },
        ),
    ]

    summary = dataset_profile_service.aggregate_profile_from_rows(
        dataset_id=dataset_id,
        rows=rows,
        density_threshold=0.12,
        image_threshold=2,
    )
    finding_counts = {item.key: item.count for item in summary.findings}

    assert finding_counts["parse_failed"] == 1
    assert finding_counts["preprocess_failed"] == 1
    assert finding_counts["pdf_unknown"] == 1
    assert finding_counts["low_density"] == 1
    assert finding_counts["parse_low_quality"] == 1
    assert finding_counts["seal_low_confidence"] == 1
    assert finding_counts["image_heavy"] == 1
    assert finding_counts["chunk_coverage_low"] == 1
    assert finding_counts["chunk_quality_fail"] == 1
    assert finding_counts["pii"] == 1
    assert finding_counts["secrets"] == 1
    assert finding_counts["near_dedup"] == 1
    assert finding_counts["exact_dup"] == 2
    assert summary.language_mix == {"zh": 1, "en": 1, "mixed": 0, "unknown": 0}
    assert summary.pii_hits_total == {"email": 2}
    assert summary.secrets_hits_total == {"token": 1}


def test_list_bucket_documents_matches_directory_case_insensitively_and_redacts_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_id = uuid4()
    doc_id = uuid4()
    row = (
        doc_id,
        dataset_id,
        "scan.pdf",
        "pdf",
        120,
        "completed",
        2,
        80,
        None,
        None,
        None,
        {"source_path": "Invoices/2026/scan.pdf"},
    )
    db = _PreviewDB([(doc_id, "Reach me at demo@example.com with token sk-test-1234567890")])

    monkeypatch.setattr(
        dataset_profile_service,
        "compute_dataset_profile_summary",
        lambda *_a, **_k: SimpleNamespace(by_directory={"Invoices": 1}),
        raising=True,
    )
    monkeypatch.setattr(
        dataset_profile_service,
        "build_dataset_documents_query",
        lambda *_a, **_k: (None, _IterableQuery([row])),
        raising=True,
    )

    result = dataset_profile_service.list_bucket_documents(
        db,
        tenant_id=uuid4(),
        account_id="reader-1",
        dataset_id=dataset_id,
        dimension="directory",
        bucket="invoices",
        include_preview=True,
        preview_max_chars=200,
    )

    assert result.total == 1
    assert len(result.items) == 1
    assert result.items[0].filename == "scan.pdf"
    assert result.items[0].preview is not None
    assert "demo@example.com" not in result.items[0].preview


def test_load_dataset_scope_rows_filters_by_time_window_and_feedback_polarity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    conversation_id = uuid4()
    db = _FakeAnalysisDB(
        conversations=[SimpleNamespace(id=conversation_id, tenant_id=tenant_id, dataset_id=dataset_id)],
    )

    monkeypatch.setattr(
        dataset_analysis_service,
        "list_rag_traces",
        lambda **_k: SimpleNamespace(items=[SimpleNamespace(trace_id="trace-1")]),
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_service,
        "build_dataset_analysis_sources",
        lambda **_k: {"rows": [{"source": "trace-1"}]},
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_service,
        "build_poc_interaction_rows",
        lambda _rows: [
            {"created_at": "2026-08-15T23:59:59+00:00", "feedback_polarity": "positive", "id": "old"},
            {"created_at": "2026-08-16T12:00:00+00:00", "feedback_polarity": "positive", "id": "keep"},
            {"created_at": "2026-08-17T00:00:00+00:00", "feedback_polarity": "positive", "id": "future"},
            {"created_at": "2026-08-16T13:00:00+00:00", "feedback_polarity": "negative", "id": "wrong-polarity"},
        ],
        raising=True,
    )

    rows = dataset_analysis_service._load_dataset_scope_rows(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        from_ts="2026-08-16T00:00:00+00:00",
        to_ts="2026-08-16T23:59:59+00:00",
        feedback_polarity="positive",
    )

    assert [row["id"] for row in rows] == ["keep"]
