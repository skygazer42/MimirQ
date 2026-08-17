import os
import threading
import uuid
from contextlib import nullcontext
from datetime import timezone
from types import SimpleNamespace

import pytest

from app.core.database import SessionLocal
from app.models.dataset import Dataset, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.document_index_channel import DocumentIndexChannel
from app.models.tenant import Tenant
from app.services import document_index_channel_service as svc


def _document(**overrides):
    payload = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "dataset_id": uuid.uuid4(),
        "status": "completed",
        "doc_metadata": {
            "pipeline_hash": "pipe-1",
            "active_pipeline_hash": "pipe-1",
            "active_pipeline_ready": True,
        },
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_summarize_document_index_channels_falls_back_for_legacy_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _document()
    monkeypatch.setattr(
        svc,
        "resolve_pipeline_effective",
        lambda **_kwargs: SimpleNamespace(
            chunk_vector_enabled=True,
            bm25_index_enabled=True,
            kg_enabled=False,
            event_vector_enabled=False,
            entity_vector_enabled=False,
        ),
        raising=True,
    )
    monkeypatch.setattr(svc, "list_document_index_channels", lambda *args, **kwargs: [], raising=True)

    summary = svc.summarize_document_index_channels(SimpleNamespace(), document=doc)

    assert summary.ready is True
    assert summary.pipeline_hash == "pipe-1"
    assert summary.enabled_channels == ["vector", "bm25"]
    assert summary.disabled_channels == ["kg", "event_vector", "entity_vector"]
    assert summary.statuses["vector"]["legacy"] is True
    assert summary.statuses["vector"]["status"] == "ready"


def test_reconcile_document_index_channels_backfills_enabled_and_disabled_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _document(status="pending")
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(
        svc,
        "resolve_pipeline_effective",
        lambda **_kwargs: SimpleNamespace(
            chunk_vector_enabled=True,
            bm25_index_enabled=False,
            kg_enabled=True,
            event_vector_enabled=False,
            entity_vector_enabled=True,
        ),
        raising=True,
    )
    monkeypatch.setattr(svc, "list_document_index_channels", lambda *_args, **_kwargs: [], raising=True)

    def _fake_upsert(_db, **kwargs):  # noqa: ANN001
        captured.append(dict(kwargs))
        return DocumentIndexChannel(
            tenant_id=kwargs["tenant_id"],
            dataset_id=kwargs["dataset_id"],
            document_id=kwargs["document_id"],
            pipeline_hash=kwargs["pipeline_hash"],
            channel=kwargs["channel"],
            required=kwargs["required"],
            enabled=kwargs["enabled"],
            status=kwargs["status"],
            error=kwargs.get("error"),
            attempt_count=kwargs.get("attempt_count", 0) or 0,
        )

    monkeypatch.setattr(svc, "upsert_document_index_channel", _fake_upsert, raising=True)

    rows = svc.reconcile_document_index_channels(SimpleNamespace(), document=doc, reset_enabled_to_pending=True)

    assert [row.channel for row in rows] == list(svc.DOCUMENT_INDEX_CHANNELS)
    assert captured[0]["channel"] == "vector"
    assert captured[0]["status"] == "pending"
    assert captured[1]["channel"] == "bm25"
    assert captured[1]["status"] == "disabled"
    assert captured[2]["channel"] == "kg"
    assert captured[2]["required"] is True
    assert captured[4]["channel"] == "entity_vector"
    assert captured[4]["enabled"] is True


def test_summarize_document_index_channels_reports_pending_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _document(status="processing")
    monkeypatch.setattr(
        svc,
        "resolve_pipeline_effective",
        lambda **_kwargs: SimpleNamespace(
            chunk_vector_enabled=True,
            bm25_index_enabled=True,
            kg_enabled=False,
            event_vector_enabled=False,
            entity_vector_enabled=False,
        ),
        raising=True,
    )
    rows = [
        SimpleNamespace(
            channel="vector",
            required=True,
            enabled=True,
            status="ready",
            error=None,
            attempt_count=1,
            last_attempted_at=None,
            last_succeeded_at=None,
            last_failed_at=None,
            last_status_changed_at=None,
        ),
        SimpleNamespace(
            channel="bm25",
            required=True,
            enabled=True,
            status="error",
            error="bm25 failed",
            attempt_count=2,
            last_attempted_at=None,
            last_succeeded_at=None,
            last_failed_at=None,
            last_status_changed_at=None,
        ),
    ]
    monkeypatch.setattr(svc, "list_document_index_channels", lambda *args, **kwargs: rows, raising=True)

    summary = svc.summarize_document_index_channels(SimpleNamespace(), document=doc)

    assert summary.ready is False
    assert summary.error_channels == ["bm25"]
    assert summary.pending_channels == []


def test_transition_document_index_channel_tracks_attempts_and_timestamps(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _document(status="processing")
    rows: dict[str, SimpleNamespace] = {}

    class _DB:
        no_autoflush = nullcontext()

        def begin_nested(self):  # noqa: ANN201
            return nullcontext()

    monkeypatch.setattr(
        svc,
        "resolve_pipeline_effective",
        lambda **_kwargs: SimpleNamespace(
            chunk_vector_enabled=True,
            bm25_index_enabled=True,
            kg_enabled=False,
            event_vector_enabled=False,
            entity_vector_enabled=False,
        ),
        raising=True,
    )
    monkeypatch.setattr(
        svc, "list_document_index_channels", lambda *_args, **_kwargs: list(rows.values()), raising=True
    )

    def _fake_upsert(_db, **kwargs):  # noqa: ANN001
        row = rows.get(kwargs["channel"]) or SimpleNamespace(channel=kwargs["channel"])
        for key, value in kwargs.items():
            setattr(row, key, value)
        rows[kwargs["channel"]] = row
        return row

    monkeypatch.setattr(svc, "upsert_document_index_channel", _fake_upsert, raising=True)

    processing_row = svc.transition_document_index_channel(
        _DB(),
        document=doc,
        channel="vector",
        status="processing",
        increment_attempt=True,
    )
    assert processing_row is not None
    assert processing_row.status == "processing"
    assert processing_row.attempt_count == 1
    assert processing_row.last_attempted_at is not None
    ready_row = svc.transition_document_index_channel(
        _DB(),
        document=doc,
        channel="vector",
        status="ready",
    )

    assert ready_row is not None
    assert ready_row.status == "ready"
    assert ready_row.attempt_count == 1
    assert ready_row.last_succeeded_at is not None
    assert ready_row.error is None


def test_transition_document_index_channel_keeps_disabled_optional_channels_out_of_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = _document(status="completed")

    class _DB:
        no_autoflush = nullcontext()

        def begin_nested(self):  # noqa: ANN201
            return nullcontext()

    monkeypatch.setattr(
        svc,
        "resolve_pipeline_effective",
        lambda **_kwargs: SimpleNamespace(
            chunk_vector_enabled=True,
            bm25_index_enabled=True,
            kg_enabled=False,
            event_vector_enabled=False,
            entity_vector_enabled=False,
        ),
        raising=True,
    )
    monkeypatch.setattr(svc, "list_document_index_channels", lambda *_args, **_kwargs: [], raising=True)

    captured: dict[str, object] = {}

    def _fake_upsert(_db, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(svc, "upsert_document_index_channel", _fake_upsert, raising=True)

    row = svc.transition_document_index_channel(
        _DB(),
        document=doc,
        channel="event_vector",
        status="error",
        error="should not persist",
        increment_attempt=True,
    )

    assert row is not None
    assert captured["status"] == "disabled"
    assert captured["required"] is False
    assert captured["enabled"] is False
    assert captured["attempt_count"] == 0
    assert captured["error"] is None


def test_transition_document_index_channel_savepoint_failure_does_not_block_next_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = _document(status="processing")
    calls = {"count": 0}

    class _DB:
        no_autoflush = nullcontext()

        def begin_nested(self):  # noqa: ANN201
            return nullcontext()

    monkeypatch.setattr(
        svc,
        "resolve_pipeline_effective",
        lambda **_kwargs: SimpleNamespace(
            chunk_vector_enabled=True,
            bm25_index_enabled=True,
            kg_enabled=False,
            event_vector_enabled=False,
            entity_vector_enabled=False,
        ),
        raising=True,
    )
    monkeypatch.setattr(svc, "list_document_index_channels", lambda *_args, **_kwargs: [], raising=True)

    def _fake_upsert(_db, **kwargs):  # noqa: ANN001
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("db write failed")
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(svc, "upsert_document_index_channel", _fake_upsert, raising=True)

    first = svc.transition_document_index_channel(
        _DB(),
        document=doc,
        channel="vector",
        status="processing",
        increment_attempt=True,
    )
    second = svc.transition_document_index_channel(
        _DB(),
        document=doc,
        channel="bm25",
        status="processing",
        increment_attempt=True,
    )

    assert first is None
    assert second is not None
    assert second.channel == "bm25"


def test_upsert_document_index_channel_uses_atomic_postgres_execute_path() -> None:
    captured: dict[str, object] = {}
    returned = DocumentIndexChannel(
        tenant_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        pipeline_hash="pipe-1",
        channel="vector",
        required=True,
        enabled=True,
        status="processing",
        error=None,
        attempt_count=3,
    )

    class _Result:
        def scalar_one(self):  # noqa: ANN201
            return returned

    class _DB:
        def get_bind(self):  # noqa: ANN201
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, stmt):  # noqa: ANN001, ANN201
            captured["stmt"] = stmt
            return _Result()

        def flush(self) -> None:
            captured["flushed"] = True

        def commit(self) -> None:
            captured["committed"] = True

        def refresh(self, _row) -> None:  # noqa: ANN001
            captured["refreshed"] = True

    row = svc.upsert_document_index_channel(
        _DB(),  # type: ignore[arg-type]
        tenant_id=returned.tenant_id,
        dataset_id=returned.dataset_id,
        document_id=returned.document_id,
        pipeline_hash="pipe-1",
        channel="vector",
        required=True,
        enabled=True,
        status="processing",
        attempt_count_increment=2,
        last_attempted_at=svc._utcnow(),
        last_status_changed_at=svc._utcnow(),
        commit=False,
    )

    assert row is returned
    assert captured["flushed"] is True
    assert "ON CONFLICT ON CONSTRAINT uq_document_index_channels_identity" in str(captured["stmt"])


@pytest.mark.skipif(
    str(os.getenv("MIMIRQ_INTEGRATION_TESTS", "") or "").strip().lower() not in {"1", "true", "yes", "y", "on"},
    reason="Integration tests disabled",
)
def test_transition_document_index_channel_is_atomic_under_postgres_concurrency(
    pg_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    monkeypatch.setattr(
        svc,
        "resolve_pipeline_effective",
        lambda **_kwargs: SimpleNamespace(
            chunk_vector_enabled=True,
            bm25_index_enabled=False,
            kg_enabled=False,
            event_vector_enabled=False,
            entity_vector_enabled=False,
        ),
        raising=True,
    )

    tenant = Tenant(id=tenant_id, name=f"tenant-{tenant_id}", status="active", plan="basic")
    dataset = Dataset(
        id=dataset_id,
        tenant_id=tenant_id,
        name=f"dataset-{dataset_id}",
        permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
        owner_id="owner-1",
        dataset_metadata={},
    )
    document = DBDocument(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="doc.txt",
        file_type="txt",
        file_size=5,
        file_path="local://doc.txt",
        status="pending",
        doc_metadata={
            "pipeline_hash": "pipe-atomic",
            "active_pipeline_hash": "pipe-atomic",
            "active_pipeline_ready": False,
        },
    )
    pg_session.add(tenant)
    pg_session.add(dataset)
    pg_session.add(document)
    pg_session.commit()

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    rows: list[object] = []

    def _worker() -> None:
        db = SessionLocal()
        try:
            doc = db.query(DBDocument).filter(DBDocument.id == document_id).one()
            barrier.wait()
            row = svc.transition_document_index_channel(
                db,
                document=doc,
                channel="vector",
                status="processing",
                increment_attempt=True,
                commit=True,
            )
            rows.append(row)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            db.close()

    thread_a = threading.Thread(target=_worker)
    thread_b = threading.Thread(target=_worker)
    thread_a.start()
    thread_b.start()
    thread_a.join()
    thread_b.join()

    assert errors == []
    assert all(row is not None for row in rows)

    pg_session.expire_all()
    persisted = (
        pg_session.query(DocumentIndexChannel)
        .filter(
            DocumentIndexChannel.tenant_id == tenant_id,
            DocumentIndexChannel.document_id == document_id,
            DocumentIndexChannel.pipeline_hash == "pipe-atomic",
            DocumentIndexChannel.channel == "vector",
        )
        .all()
    )
    assert len(persisted) == 1
    assert persisted[0].attempt_count == 2
    assert persisted[0].status == "processing"
    assert persisted[0].last_attempted_at is not None
    assert persisted[0].last_status_changed_at is not None

    doc = pg_session.query(DBDocument).filter(DBDocument.id == document_id).one()
    ready_row = svc.transition_document_index_channel(
        pg_session,
        document=doc,
        channel="vector",
        status="ready",
        commit=True,
    )

    pg_session.expire_all()
    continued = (
        pg_session.query(DocumentIndexChannel)
        .filter(
            DocumentIndexChannel.tenant_id == tenant_id,
            DocumentIndexChannel.document_id == document_id,
            DocumentIndexChannel.pipeline_hash == "pipe-atomic",
            DocumentIndexChannel.channel == "vector",
        )
        .one()
    )
    assert ready_row is not None
    assert continued.status == "ready"
    assert continued.attempt_count == 2
    assert continued.last_succeeded_at is not None
    assert (
        continued.last_status_changed_at.tzinfo == timezone.utc or continued.last_status_changed_at.tzinfo is not None
    )
