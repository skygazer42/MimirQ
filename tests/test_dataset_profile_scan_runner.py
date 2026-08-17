
import asyncio
import datetime as dt
import importlib
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import dataset_profile_scan_runner as runner

if not hasattr(dt, "UTC"):
    dt.UTC = dt.timezone.utc


class _ResultQuery:
    def __init__(
        self,
        *,
        first_value: object | None = None,
        all_value: object | None = None,
        on_first: Callable[[], None] | None = None,
        on_all: Callable[[], None] | None = None,
    ) -> None:
        self._first_value = first_value
        self._all_value = all_value
        self._on_first = on_first
        self._on_all = on_all

    def filter(self, *_args: object, **_kwargs: object) -> "_ResultQuery":
        return self

    def order_by(self, *_args: object, **_kwargs: object) -> "_ResultQuery":
        return self

    def limit(self, _limit: int) -> "_ResultQuery":
        return self

    def first(self) -> object | None:
        if self._on_first is not None:
            self._on_first()
        return self._first_value

    def all(self) -> object | None:
        if self._on_all is not None:
            self._on_all()
        return self._all_value


class _DocsQuery:
    def __init__(self, docs: list[object]) -> None:
        self._docs = docs
        self._limit: int | None = None

    def order_by(self, *_args: object, **_kwargs: object) -> "_DocsQuery":
        return self

    def limit(self, limit: int) -> "_DocsQuery":
        self._limit = limit
        return self

    def all(self) -> list[object]:
        if self._limit is None:
            return list(self._docs)
        return list(self._docs[: self._limit])


class _SequencedDB:
    def __init__(self, *, run: object, query_plan: list[tuple[str, _ResultQuery]]) -> None:
        self.run = run
        self._query_plan = list(query_plan)
        self.commits = 0
        self.commit_states: list[dict[str, object]] = []
        self.query_labels: list[str] = []
        self.unexpected_queries = 0
        self.rollbacks = 0

    def query(self, *_args: object, **_kwargs: object) -> _ResultQuery:
        if not self._query_plan:
            self.unexpected_queries += 1
            raise AssertionError("Unexpected query")
        label, query = self._query_plan.pop(0)
        self.query_labels.append(label)
        return query

    def commit(self) -> None:
        self.commits += 1
        self.commit_states.append(
            {
                "status": self.run.status,
                "progress": self.run.progress,
                "summary": self.run.summary,
            }
        )

    def rollback(self) -> None:
        self.rollbacks += 1

    def assert_finished(self) -> None:
        assert self._query_plan == []


class _Summary:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return dict(self._payload)


def test_ensure_local_path_downloads_generic_object_storage_uri(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    monkeypatch.setattr(runner.settings, "OBJECT_STORAGE_ENABLED", True, raising=False)
    document = SimpleNamespace(
        id=document_id,
        file_type="pdf",
        file_path="s3://bucket/documents/t/d/source.pdf",
        doc_metadata={"source_storage_backend": "object_storage", "source_storage_provider": "s3"},
    )
    downloaded: list[Path] = []

    class _Store:
        def download_object_to_path(self, *, object_name: str, destination: Path, max_bytes: int) -> Path:
            assert object_name
            assert max_bytes > 0
            downloaded.append(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"pdf-data")
            return destination

    monkeypatch.setattr(
        runner,
        "resolve_document_object_reference",
        lambda *_args, **_kwargs: (_Store(), SimpleNamespace(bucket="bucket", object_name="documents/t/d/source.pdf")),
        raising=True,
    )

    local_path, temp_path = runner._ensure_local_path(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document=document,
        temp_root=tmp_path,
    )

    assert local_path == temp_path
    assert temp_path is not None and temp_path.exists()
    assert downloaded == [temp_path]


def test_run_dataset_profile_deep_scan_backfills_enabled_fields_in_current_phase_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    scan_run_id = uuid4()
    document_id = uuid4()
    now = dt.datetime(2026, 8, 16, 12, 0, tzinfo=dt.UTC)
    events: list[str] = []
    temp_file = tmp_path / "downloaded.pdf"

    doc = SimpleNamespace(
        id=document_id,
        file_type="pdf",
        file_path="s3://bucket/deep-scan.pdf",
        doc_metadata={
            "governance_enrichment": {"language": "fr"},
            "pipeline_effective": {"chunk_size": "256", "chunk_overlap": "32"},
        },
        created_at=now,
        total_characters=40,
        chunk_count=2,
    )
    run = SimpleNamespace(
        id=scan_run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        config={
            "backfill_pdf_quality": True,
            "backfill_text_quality": True,
            "backfill_chunk_stats": True,
            "backfill_chunk_token_stats": True,
            "backfill_chunk_coverage": True,
            "backfill_chunk_quality_gate": True,
            "compute_file_hash": True,
        },
        status="queued",
        progress=None,
        started_at=None,
        updated_at=None,
        finished_at=None,
        error_message="stale",
        summary=None,
    )
    db = _SequencedDB(
        run=run,
        query_plan=[
            ("run", _ResultQuery(first_value=run)),
            (
                "parsed_text",
                _ResultQuery(
                    first_value=("Primary parsed text",),
                    on_first=lambda: events.append("load_parsed_text"),
                ),
            ),
            (
                "chunk_lengths",
                _ResultQuery(
                    all_value=[(10,), (20,)],
                    on_all=lambda: events.append("load_chunk_lengths"),
                ),
            ),
            (
                "chunk_texts",
                _ResultQuery(
                    all_value=[("chunk one",), ("chunk two",)],
                    on_all=lambda: events.append("load_chunk_texts"),
                ),
            ),
            (
                "chunk_ranges",
                _ResultQuery(
                    all_value=[(0, 10, 10), (10, None, 10)],
                    on_all=lambda: events.append("load_chunk_ranges"),
                ),
            ),
        ],
    )

    class _TextQuality:
        def to_dict(self) -> dict[str, object]:
            return {"score": 0.91}

    def _ensure_local_path(**_kwargs: object) -> tuple[Path, Path]:
        events.append("ensure_local_path")
        temp_file.write_bytes(b"pdf-bytes")
        return temp_file, temp_file

    def _score_pdf_quality(*_args: object, **_kwargs: object) -> dict[str, float | int]:
        events.append("score_pdf_quality")
        return {"page_count": 5, "scan_ratio": 0.1}

    def _score_parsed_text_quality(*_args: object, **_kwargs: object) -> _TextQuality:
        events.append("score_parsed_text_quality")
        return _TextQuality()

    def _score_document_parse_quality(*_args: object, **_kwargs: object) -> dict[str, float]:
        events.append("score_document_parse_quality")
        return {"score": 0.88}

    def _safe_hash_file(*_args: object, **_kwargs: object) -> str:
        events.append("safe_hash_file")
        return "abc123"

    stats_utils = importlib.import_module("app.services.chunking_stats_utils")
    coverage_utils = importlib.import_module("app.services.chunk_coverage_utils")
    quality_gate_module = importlib.import_module("app.services.chunk_quality_gate")

    monkeypatch.setattr(runner, "_now_utc", lambda: now)
    monotonic_values = iter([0.0, 1.0])
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(runner, "_ensure_local_path", _ensure_local_path)
    monkeypatch.setattr(runner, "score_pdf_quality", _score_pdf_quality)
    monkeypatch.setattr(runner, "score_parsed_text_quality", _score_parsed_text_quality)
    monkeypatch.setattr(runner, "score_document_parse_quality", _score_document_parse_quality)
    monkeypatch.setattr(runner, "_safe_hash_file", _safe_hash_file)
    monkeypatch.setattr(
        runner,
        "build_dataset_documents_query",
        lambda *_args, **_kwargs: (object(), _DocsQuery([doc])),
    )
    monkeypatch.setattr(
        runner,
        "compute_dataset_profile_summary",
        lambda *_args, **_kwargs: _Summary({"summary_version": 1}),
    )
    monkeypatch.setattr(
        stats_utils,
        "compute_chunking_stats_from_lengths",
        lambda *_args, **_kwargs: (
            events.append("compute_chunking_stats_from_lengths")
            or {"histogram": [{"bucket": 1}], "count": 2, "short_count": 0, "duplicate_count": 0}
        ),
    )
    monkeypatch.setattr(
        stats_utils,
        "compute_chunking_stats_from_texts_tokens",
        lambda *_args, **_kwargs: (
            events.append("compute_chunking_stats_from_texts_tokens")
            or {"histogram": [{"bucket": 2}], "count": 2, "short_count": 0, "duplicate_count": 0}
        ),
    )
    monkeypatch.setattr(
        coverage_utils,
        "compute_chunk_coverage_metrics_from_ranges",
        lambda *_args, **_kwargs: (
            events.append("compute_chunk_coverage_metrics_from_ranges")
            or {"covered_chars": 20, "coverage_ratio": 0.5, "overlap_waste_ratio": 0.0, "gap_count": 0}
        ),
    )
    monkeypatch.setattr(
        quality_gate_module,
        "compute_chunk_quality_gate",
        lambda *_args, **_kwargs: (
            events.append("compute_chunk_quality_gate") or ({"grade": "B"}, ["review overlap"], ["increase chunk size"])
        ),
    )

    result = runner.run_dataset_profile_deep_scan(
        db,
        tenant_id=tenant_id,
        account_id="acct",
        dataset_id=dataset_id,
        scan_run_id=scan_run_id,
    )

    assert result == {
        "ok": True,
        "documents": 1,
        "updated_docs": 1,
        "pdf_backfilled": 1,
        "text_backfilled": 1,
        "chunk_stats_backfilled": 1,
        "chunk_token_stats_backfilled": 1,
        "chunk_coverage_backfilled": 1,
        "chunk_quality_gate_backfilled": 1,
        "hash_backfilled": 1,
        "errors": 0,
    }
    assert events == [
        "ensure_local_path",
        "score_pdf_quality",
        "load_parsed_text",
        "score_parsed_text_quality",
        "score_document_parse_quality",
        "load_chunk_lengths",
        "compute_chunking_stats_from_lengths",
        "load_chunk_texts",
        "compute_chunking_stats_from_texts_tokens",
        "load_chunk_ranges",
        "compute_chunk_coverage_metrics_from_ranges",
        "compute_chunk_quality_gate",
        "ensure_local_path",
        "safe_hash_file",
    ]
    assert doc.doc_metadata == {
        "governance_enrichment": {"language": "fr"},
        "pipeline_effective": {"chunk_size": "256", "chunk_overlap": "32"},
        "pdf_quality": {"page_count": 5, "scan_ratio": 0.1},
        "page_count": 5,
        "parsed_text_quality": {"score": 0.91},
        "language": "fr",
        "parse_quality": {"score": 0.88},
        "chunking_stats": {
            "histogram": [{"bucket": 1}],
            "count": 2,
            "short_count": 0,
            "duplicate_count": 0,
        },
        "chunking_stats_tokens": {
            "histogram": [{"bucket": 2}],
            "count": 2,
            "short_count": 0,
            "duplicate_count": 0,
        },
        "chunk_coverage": {
            "covered_chars": 20,
            "coverage_ratio": 0.5,
            "overlap_waste_ratio": 0.0,
            "gap_count": 0,
            "ranges_used": 2,
        },
        "chunk_quality_gate": {"grade": "B"},
        "chunk_quality_recommendations": ["review overlap"],
        "chunk_quality_patches": ["increase chunk size"],
        "file_sha256": "abc123",
    }
    assert run.status == "completed"
    assert run.progress == 100
    assert run.error_message is None
    assert run.summary == {"summary_version": 1}
    assert db.commits == 5
    assert db.commit_states[0] == {"status": "running", "progress": 0, "summary": None}
    assert db.commit_states[1] == {"status": "running", "progress": 100, "summary": None}
    assert db.commit_states[-2] == {"status": "completed", "progress": 100, "summary": None}
    assert db.commit_states[-1] == {
        "status": "completed",
        "progress": 100,
        "summary": {"summary_version": 1},
    }
    db.assert_finished()


def test_run_dataset_profile_deep_scan_continues_after_document_failure_without_partial_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    scan_run_id = uuid4()
    failed_doc = SimpleNamespace(
        id=uuid4(),
        file_type="pdf",
        file_path="s3://bucket/missing.pdf",
        doc_metadata={},
        created_at=dt.datetime(2026, 8, 16, 12, 0, tzinfo=dt.UTC),
        total_characters=10,
        chunk_count=1,
    )
    succeeding_doc = SimpleNamespace(
        id=uuid4(),
        file_type="txt",
        file_path="local.txt",
        doc_metadata={},
        created_at=dt.datetime(2026, 8, 16, 12, 1, tzinfo=dt.UTC),
        total_characters=10,
        chunk_count=1,
    )
    run = SimpleNamespace(
        id=scan_run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        config={"backfill_text_quality": False, "backfill_chunk_stats": False},
        status="queued",
        progress=None,
        started_at=None,
        updated_at=None,
        finished_at=None,
        error_message="stale",
        summary=None,
    )
    db = _SequencedDB(run=run, query_plan=[("run", _ResultQuery(first_value=run))])

    monkeypatch.setattr(
        runner,
        "build_dataset_documents_query",
        lambda *_args, **_kwargs: (object(), _DocsQuery([failed_doc, succeeding_doc])),
    )
    monkeypatch.setattr(runner, "_now_utc", lambda: dt.datetime(2026, 8, 16, 12, 2, tzinfo=dt.UTC))
    monotonic_values = iter([0.0, 1.0, 2.0])
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(
        runner,
        "_ensure_local_path",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("document_file_not_found")),
    )
    monkeypatch.setattr(
        runner,
        "compute_dataset_profile_summary",
        lambda *_args, **_kwargs: _Summary({"documents_profiled": 2}),
    )

    result = runner.run_dataset_profile_deep_scan(
        db,
        tenant_id=tenant_id,
        account_id="acct",
        dataset_id=dataset_id,
        scan_run_id=scan_run_id,
    )

    assert result == {
        "ok": True,
        "documents": 2,
        "updated_docs": 1,
        "pdf_backfilled": 0,
        "text_backfilled": 0,
        "chunk_stats_backfilled": 0,
        "chunk_token_stats_backfilled": 0,
        "chunk_coverage_backfilled": 0,
        "chunk_quality_gate_backfilled": 0,
        "hash_backfilled": 0,
        "errors": 1,
    }
    assert failed_doc.doc_metadata == {}
    assert succeeding_doc.doc_metadata == {"language": "unknown"}
    assert run.status == "completed"
    assert run.progress == 100
    assert run.error_message is None
    assert run.summary == {"documents_profiled": 2}
    db.assert_finished()


def test_run_dataset_profile_deep_scan_commits_updated_docs_in_batches_of_twenty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    scan_run_id = uuid4()
    now = dt.datetime(2026, 8, 16, 12, 0, tzinfo=dt.UTC)
    docs = [
        SimpleNamespace(
            id=uuid4(),
            file_type="txt",
            file_path=f"/tmp/doc-{index}.txt",
            doc_metadata={},
            created_at=now,
            total_characters=20,
            chunk_count=1,
        )
        for index in range(21)
    ]
    run = SimpleNamespace(
        id=scan_run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        config={"backfill_pdf_quality": False, "backfill_text_quality": False, "backfill_chunk_stats": False},
        status="queued",
        progress=None,
        started_at=None,
        updated_at=None,
        finished_at=None,
        error_message=None,
        summary=None,
    )
    db = _SequencedDB(run=run, query_plan=[("run", _ResultQuery(first_value=run))])

    monkeypatch.setattr(
        runner,
        "build_dataset_documents_query",
        lambda *_args, **_kwargs: (object(), _DocsQuery(docs)),
    )
    monkeypatch.setattr(runner, "_now_utc", lambda: now)
    monkeypatch.setattr(runner.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(
        runner,
        "compute_dataset_profile_summary",
        lambda *_args, **_kwargs: _Summary({"documents_profiled": 21}),
    )

    result = runner.run_dataset_profile_deep_scan(
        db,
        tenant_id=tenant_id,
        account_id="acct",
        dataset_id=dataset_id,
        scan_run_id=scan_run_id,
    )

    assert result["updated_docs"] == 21
    assert result["documents"] == 21
    assert result["errors"] == 0
    assert db.commits == 5
    assert db.commit_states == [
        {"status": "running", "progress": 0, "summary": None},
        {"status": "running", "progress": 0, "summary": None},
        {"status": "running", "progress": 0, "summary": None},
        {"status": "completed", "progress": 100, "summary": None},
        {"status": "completed", "progress": 100, "summary": {"documents_profiled": 21}},
    ]
    assert all(doc.doc_metadata == {"language": "unknown"} for doc in docs)
    db.assert_finished()


def test_run_dataset_profile_deep_scan_completes_zero_document_run_in_commit_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    scan_run_id = uuid4()
    now = dt.datetime(2026, 8, 17, 9, 0, tzinfo=dt.UTC)
    run = SimpleNamespace(
        id=scan_run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        config={},
        status="queued",
        progress=None,
        started_at=None,
        updated_at=None,
        finished_at=None,
        error_message="stale",
        summary=None,
    )
    db = _SequencedDB(run=run, query_plan=[("run", _ResultQuery(first_value=run))])

    monkeypatch.setattr(runner, "_now_utc", lambda: now)
    monkeypatch.setattr(
        runner,
        "build_dataset_documents_query",
        lambda *_args, **_kwargs: (object(), _DocsQuery([])),
    )
    monkeypatch.setattr(
        runner,
        "compute_dataset_profile_summary",
        lambda *_args, **_kwargs: _Summary({"documents_profiled": 0}),
    )

    result = runner.run_dataset_profile_deep_scan(
        db,
        tenant_id=tenant_id,
        account_id="acct",
        dataset_id=dataset_id,
        scan_run_id=scan_run_id,
    )

    assert result == {"ok": True, "documents": 0}
    assert run.status == "completed"
    assert run.progress == 100
    assert run.error_message is None
    assert run.summary == {"documents_profiled": 0}
    assert run.started_at == now
    assert run.finished_at == now
    assert db.commit_states == [
        {"status": "running", "progress": 0, "summary": None},
        {"status": "completed", "progress": 100, "summary": None},
        {"status": "completed", "progress": 100, "summary": {"documents_profiled": 0}},
    ]
    assert db.rollbacks == 0
    db.assert_finished()


def test_run_dataset_profile_deep_scan_discards_metadata_after_late_document_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    scan_run_id = uuid4()
    now = dt.datetime(2026, 8, 17, 9, 5, tzinfo=dt.UTC)
    original_metadata = {
        "pdf_quality": {"page_count": 7},
        "governance_enrichment": {"language": "de"},
    }
    document = SimpleNamespace(
        id=uuid4(),
        file_type="pdf",
        file_path="/tmp/document.pdf",
        doc_metadata=original_metadata,
        created_at=now,
        total_characters=100,
        chunk_count=2,
    )
    run = SimpleNamespace(
        id=scan_run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        config={
            "backfill_pdf_quality": False,
            "backfill_text_quality": False,
            "backfill_chunk_stats": False,
            "backfill_chunk_token_stats": False,
            "backfill_chunk_coverage": False,
            "backfill_chunk_quality_gate": False,
            "compute_file_hash": True,
        },
        status="queued",
        progress=None,
        started_at=None,
        updated_at=None,
        finished_at=None,
        error_message=None,
        summary=None,
    )
    committed_metadata: list[dict[str, object]] = []
    late_phase_metadata: dict[str, object] = {}

    class _MetadataTrackingDB(_SequencedDB):
        def commit(self) -> None:
            committed_metadata.append(dict(document.doc_metadata))
            super().commit()

    db = _MetadataTrackingDB(run=run, query_plan=[("run", _ResultQuery(first_value=run))])

    def _fail_after_metadata_backfills(meta: dict[str, object], **_kwargs: object) -> bool:
        late_phase_metadata.update(meta)
        raise RuntimeError("late document phase failed")

    monkeypatch.setattr(runner, "_now_utc", lambda: now)
    monkeypatch.setattr(runner.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(runner, "score_document_parse_quality", lambda **_kwargs: {"score": 0.72})
    monkeypatch.setattr(runner, "_maybe_backfill_file_hash", _fail_after_metadata_backfills)
    monkeypatch.setattr(
        runner,
        "build_dataset_documents_query",
        lambda *_args, **_kwargs: (object(), _DocsQuery([document])),
    )
    monkeypatch.setattr(
        runner,
        "compute_dataset_profile_summary",
        lambda *_args, **_kwargs: _Summary({"documents_profiled": 1}),
    )

    result = runner.run_dataset_profile_deep_scan(
        db,
        tenant_id=tenant_id,
        account_id="acct",
        dataset_id=dataset_id,
        scan_run_id=scan_run_id,
    )

    assert late_phase_metadata == {
        **original_metadata,
        "page_count": 7,
        "language": "de",
        "parse_quality": {"score": 0.72},
    }
    assert document.doc_metadata is original_metadata
    assert document.doc_metadata == {
        "pdf_quality": {"page_count": 7},
        "governance_enrichment": {"language": "de"},
    }
    assert committed_metadata == [original_metadata] * 4
    assert result == {
        "ok": True,
        "documents": 1,
        "updated_docs": 0,
        "pdf_backfilled": 0,
        "text_backfilled": 0,
        "chunk_stats_backfilled": 0,
        "chunk_token_stats_backfilled": 0,
        "chunk_coverage_backfilled": 0,
        "chunk_quality_gate_backfilled": 0,
        "hash_backfilled": 0,
        "errors": 1,
    }
    assert db.rollbacks == 0
    db.assert_finished()


@pytest.mark.parametrize(
    "summary_error",
    [RuntimeError("summary failed"), asyncio.CancelledError("summary cancelled")],
    ids=["failure", "cancellation"],
)
def test_run_dataset_profile_deep_scan_propagates_summary_commit_failure_after_completion_commit(
    monkeypatch: pytest.MonkeyPatch,
    summary_error: BaseException,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    scan_run_id = uuid4()
    now = dt.datetime(2026, 8, 17, 9, 10, tzinfo=dt.UTC)
    document = SimpleNamespace(
        id=uuid4(),
        file_type="txt",
        file_path="/tmp/document.txt",
        doc_metadata={"language": "en", "parse_quality": {"score": 1.0}},
        created_at=now,
        total_characters=10,
        chunk_count=1,
    )
    run = SimpleNamespace(
        id=scan_run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        config={
            "backfill_pdf_quality": False,
            "backfill_text_quality": False,
            "backfill_chunk_stats": False,
            "backfill_chunk_token_stats": False,
            "backfill_chunk_coverage": False,
            "backfill_chunk_quality_gate": False,
            "compute_file_hash": False,
        },
        status="queued",
        progress=None,
        started_at=None,
        updated_at=None,
        finished_at=None,
        error_message=None,
        summary=None,
    )

    class _SummaryCommitInterruptingDB(_SequencedDB):
        failed_commit_state: dict[str, object] | None = None

        def commit(self) -> None:
            if self.commits == 3:
                self.failed_commit_state = {
                    "status": self.run.status,
                    "progress": self.run.progress,
                    "summary": self.run.summary,
                }
                raise summary_error
            super().commit()

    db = _SummaryCommitInterruptingDB(run=run, query_plan=[("run", _ResultQuery(first_value=run))])

    monkeypatch.setattr(runner, "_now_utc", lambda: now)
    monkeypatch.setattr(runner.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(
        runner,
        "build_dataset_documents_query",
        lambda *_args, **_kwargs: (object(), _DocsQuery([document])),
    )
    monkeypatch.setattr(
        runner,
        "compute_dataset_profile_summary",
        lambda *_args, **_kwargs: _Summary({"documents_profiled": 1}),
    )

    with pytest.raises(type(summary_error), match=str(summary_error)):
        runner.run_dataset_profile_deep_scan(
            db,
            tenant_id=tenant_id,
            account_id="acct",
            dataset_id=dataset_id,
            scan_run_id=scan_run_id,
        )

    assert run.status == "completed"
    assert run.progress == 100
    assert run.summary == {"documents_profiled": 1}
    assert db.commit_states == [
        {"status": "running", "progress": 0, "summary": None},
        {"status": "running", "progress": 0, "summary": None},
        {"status": "completed", "progress": 100, "summary": None},
    ]
    assert db.failed_commit_state == {
        "status": "completed",
        "progress": 100,
        "summary": {"documents_profiled": 1},
    }
    assert db.rollbacks == 0
    db.assert_finished()


def test_run_dataset_profile_deep_scan_skips_all_disabled_option_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    scan_run_id = uuid4()
    now = dt.datetime(2026, 8, 17, 9, 15, tzinfo=dt.UTC)
    metadata = {"language": "en", "parse_quality": {"score": 1.0}}
    document = SimpleNamespace(
        id=uuid4(),
        file_type="pdf",
        file_path="/tmp/document.pdf",
        doc_metadata=metadata,
        created_at=now,
        total_characters=100,
        chunk_count=2,
    )
    run = SimpleNamespace(
        id=scan_run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        config={
            "backfill_pdf_quality": False,
            "backfill_text_quality": False,
            "backfill_chunk_stats": False,
            "backfill_chunk_token_stats": False,
            "backfill_chunk_coverage": False,
            "backfill_chunk_quality_gate": False,
            "compute_file_hash": False,
        },
        status="queued",
        progress=None,
        started_at=None,
        updated_at=None,
        finished_at=None,
        error_message=None,
        summary=None,
    )
    db = _SequencedDB(run=run, query_plan=[("run", _ResultQuery(first_value=run))])
    unexpected_calls: list[str] = []

    def _unexpected_call(*_args: object, **_kwargs: object) -> None:
        unexpected_calls.append("expensive helper")
        pytest.fail("disabled scan option invoked an expensive helper")

    stats_utils = importlib.import_module("app.services.chunking_stats_utils")
    coverage_utils = importlib.import_module("app.services.chunk_coverage_utils")
    quality_gate_module = importlib.import_module("app.services.chunk_quality_gate")

    monkeypatch.setattr(runner, "_now_utc", lambda: now)
    monkeypatch.setattr(runner.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(runner, "_ensure_local_path", _unexpected_call)
    monkeypatch.setattr(runner, "_load_text_for_quality", _unexpected_call)
    monkeypatch.setattr(runner, "score_pdf_quality", _unexpected_call)
    monkeypatch.setattr(runner, "score_parsed_text_quality", _unexpected_call)
    monkeypatch.setattr(runner, "score_document_parse_quality", _unexpected_call)
    monkeypatch.setattr(runner, "_safe_hash_file", _unexpected_call)
    monkeypatch.setattr(stats_utils, "compute_chunking_stats_from_lengths", _unexpected_call)
    monkeypatch.setattr(stats_utils, "compute_chunking_stats_from_texts_tokens", _unexpected_call)
    monkeypatch.setattr(coverage_utils, "compute_chunk_coverage_metrics_from_ranges", _unexpected_call)
    monkeypatch.setattr(quality_gate_module, "compute_chunk_quality_gate", _unexpected_call)
    monkeypatch.setattr(
        runner,
        "build_dataset_documents_query",
        lambda *_args, **_kwargs: (object(), _DocsQuery([document])),
    )
    monkeypatch.setattr(
        runner,
        "compute_dataset_profile_summary",
        lambda *_args, **_kwargs: _Summary({"documents_profiled": 1}),
    )

    result = runner.run_dataset_profile_deep_scan(
        db,
        tenant_id=tenant_id,
        account_id="acct",
        dataset_id=dataset_id,
        scan_run_id=scan_run_id,
    )

    assert result == {
        "ok": True,
        "documents": 1,
        "updated_docs": 0,
        "pdf_backfilled": 0,
        "text_backfilled": 0,
        "chunk_stats_backfilled": 0,
        "chunk_token_stats_backfilled": 0,
        "chunk_coverage_backfilled": 0,
        "chunk_quality_gate_backfilled": 0,
        "hash_backfilled": 0,
        "errors": 0,
    }
    assert document.doc_metadata is metadata
    assert unexpected_calls == []
    assert db.query_labels == ["run"]
    assert db.unexpected_queries == 0
    db.assert_finished()
