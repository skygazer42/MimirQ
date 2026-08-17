
import uuid
from types import SimpleNamespace

import pytest

from app.services import evidence_reference_repair_service as repair_mod


class _FakeQuery:
    def __init__(self, rows) -> None:
        self._rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, _value):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, *query_rows) -> None:
        self._query_rows = list(query_rows)
        self.query_count = 0
        self.added: list[object] = []
        self.commit_count = 0
        self.refreshed: list[object] = []
        self.rollback_count = 0

    def query(self, *_args, **_kwargs):
        self.query_count += 1
        return _FakeQuery(self._query_rows.pop(0))

    @property
    def remaining_query_rows(self) -> list[object]:
        return list(self._query_rows)

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.commit_count += 1

    def refresh(self, obj) -> None:
        self.refreshed.append(obj)

    def rollback(self) -> None:
        self.rollback_count += 1


def _run_repair(
    db: _FakeDB,
    *,
    tenant_id: uuid.UUID,
    suite_id: uuid.UUID,
    dataset_id: uuid.UUID,
    apply: bool,
    actor_id: str | None = None,
):
    return repair_mod.repair_evidence_suite_reference_sources_with_dataset(
        db,
        tenant_id=tenant_id,
        suite_id=suite_id,
        suite_dataset_id=dataset_id,
        apply=apply,
        allow_approved=False,
        include_archived_items=False,
        max_items=10,
        max_refs_per_item=5,
        max_changes=5,
        actor_id=actor_id,
    )


def _make_item(reference_source: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status="review",
        reference_sources=[reference_source],
        updated_at=SimpleNamespace(desc=lambda: None),
    )


def _force_chunk_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repair_mod,
        "classify_reference_source_drift",
        lambda **_kwargs: (False, "chunk_missing", {}, {}),
        raising=True,
    )


def test_repair_reference_sources_dry_run_preserves_reporting_for_unrepaired_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    item = SimpleNamespace(
        id=uuid.uuid4(),
        status="review",
        reference_sources=[{"document_id": str(document_id), "chunk_id": str(chunk_id)}],
        updated_at=SimpleNamespace(desc=lambda: None),
    )

    monkeypatch.setattr(
        repair_mod,
        "classify_reference_source_drift",
        lambda **_kwargs: (False, "document_dataset_mismatch", {}, {}),
        raising=True,
    )

    db = _FakeDB(
        [item],
        [(document_id, uuid.uuid4(), "pdf", {"language": "en"})],
        [(chunk_id, document_id, 7, {"pipeline_hash": "stale"}, 2, 10, 20, None)],
    )

    result = _run_repair(
        db,
        tenant_id=tenant_id,
        suite_id=suite_id,
        dataset_id=dataset_id,
        apply=False,
    )

    assert result == {
        "suite_id": str(suite_id),
        "dataset_id": str(dataset_id),
        "applied": False,
        "scanned_items": 1,
        "scanned_references": 1,
        "drifted_references": 1,
        "repaired_references": 0,
        "skipped_approved_items": 0,
        "skipped_archived_items": 0,
        "changes_truncated": False,
        "changes": [
            {
                "suite_id": str(suite_id),
                "item_id": str(item.id),
                "item_status": "review",
                "document_id": str(document_id),
                "chunk_id_before": str(chunk_id),
                "chunk_id_after": None,
                "reason": "document_dataset_mismatch",
                "repaired": False,
                "method": None,
                "meta": {},
            }
        ],
    }
    assert item.reference_sources == [{"document_id": str(document_id), "chunk_id": str(chunk_id)}]
    assert db.added == []
    assert db.commit_count == 0
    assert db.refreshed == []
    assert db.rollback_count == 0


def test_repair_reference_sources_apply_updates_item_and_audits_quote_needle_relink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    stale_chunk_id = uuid.uuid4()
    repaired_chunk_id = uuid.uuid4()
    item = SimpleNamespace(
        id=uuid.uuid4(),
        status="review",
        reference_sources=[
            {
                "document_id": str(document_id),
                "chunk_id": str(stale_chunk_id),
                "quote": "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu",
                "page_number": 1,
            }
        ],
        updated_at=SimpleNamespace(desc=lambda: None),
    )

    audit_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        repair_mod,
        "classify_reference_source_drift",
        lambda **_kwargs: (False, "chunk_missing", {}, {}),
        raising=True,
    )
    monkeypatch.setattr(
        repair_mod,
        "audit_log_event",
        lambda _db, **kwargs: audit_calls.append(kwargs),
        raising=True,
    )

    db = _FakeDB(
        [item],
        [(document_id, dataset_id, "pdf", {"active_pipeline_hash": "hash-2"})],
        [],
        [
            (
                repaired_chunk_id,
                document_id,
                3,
                {"pipeline_hash": "hash-2", "doc_pipeline_key": f"{document_id}:hash-2"},
                9,
                110,
                170,
            ),
            (
                uuid.uuid4(),
                document_id,
                5,
                {"pipeline_hash": "hash-2", "doc_pipeline_key": f"{document_id}:hash-2"},
                11,
                210,
                260,
            ),
        ],
    )
    needle_len = len(repair_mod._select_quote_needle(item.reference_sources[0]["quote"]))

    result = _run_repair(
        db,
        tenant_id=tenant_id,
        suite_id=suite_id,
        dataset_id=dataset_id,
        apply=True,
        actor_id="acct-123",
    )

    assert result == {
        "suite_id": str(suite_id),
        "dataset_id": str(dataset_id),
        "applied": True,
        "scanned_items": 1,
        "scanned_references": 1,
        "drifted_references": 1,
        "repaired_references": 1,
        "skipped_approved_items": 0,
        "skipped_archived_items": 0,
        "changes_truncated": False,
        "changes": [
            {
                "suite_id": str(suite_id),
                "item_id": str(item.id),
                "item_status": "review",
                "document_id": str(document_id),
                "chunk_id_before": str(stale_chunk_id),
                "chunk_id_after": str(repaired_chunk_id),
                "reason": "chunk_missing",
                "repaired": True,
                "method": "quote_needle",
                "meta": {"needle_len": needle_len},
            }
        ],
    }
    assert item.reference_sources == [
        {
            "document_id": str(document_id),
            "chunk_id": str(repaired_chunk_id),
            "quote": "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu",
            "page_number": 9,
            "chunk_index": 3,
            "pipeline_hash": "hash-2",
            "doc_pipeline_key": f"{document_id}:hash-2",
            "start_char": 110,
            "end_char": 170,
        }
    ]
    assert db.added == [item]
    assert db.commit_count == 2
    assert db.refreshed == [item]
    assert db.rollback_count == 0
    assert audit_calls == [
        {
            "tenant_id": tenant_id,
            "actor_id": "acct-123",
            "action": "evidence.reference_sources.repair",
            "resource_type": "evidence_item",
            "resource_id": str(item.id),
            "details": {
                "suite_id": str(suite_id),
                "dataset_id": str(dataset_id),
                "item_status": "review",
                "applied": True,
            },
        }
    ]


def test_exact_doc_pipeline_key_and_chunk_index_relink_precedes_quote_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    stale_chunk_id = uuid.uuid4()
    exact_chunk_id = uuid.uuid4()
    quote_chunk_id = uuid.uuid4()
    doc_pipeline_key = f"{document_id}:hash-2"
    quote = "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    reference_source = {
        "document_id": str(document_id),
        "chunk_id": str(stale_chunk_id),
        "doc_pipeline_key": doc_pipeline_key,
        "chunk_index": 4,
        "quote": quote,
    }
    item = _make_item(reference_source)
    exact_row = (
        exact_chunk_id,
        document_id,
        4,
        {"pipeline_hash": "hash-2", "doc_pipeline_key": doc_pipeline_key},
        6,
        40,
        90,
        None,
    )
    quote_rows = [
        (
            quote_chunk_id,
            document_id,
            1,
            {"pipeline_hash": "hash-2", "doc_pipeline_key": doc_pipeline_key},
            2,
            10,
            35,
        )
    ]

    _force_chunk_missing(monkeypatch)
    db = _FakeDB(
        [item],
        [(document_id, dataset_id, "pdf", {"active_pipeline_hash": "hash-2"})],
        [],
        [exact_row],
        quote_rows,
    )

    result = _run_repair(
        db,
        tenant_id=tenant_id,
        suite_id=suite_id,
        dataset_id=dataset_id,
        apply=False,
    )

    assert result["repaired_references"] == 1
    assert result["changes"] == [
        {
            "suite_id": str(suite_id),
            "item_id": str(item.id),
            "item_status": "review",
            "document_id": str(document_id),
            "chunk_id_before": str(stale_chunk_id),
            "chunk_id_after": str(exact_chunk_id),
            "reason": "chunk_missing",
            "repaired": True,
            "method": "doc_pipeline_key+chunk_index",
            "meta": {"needle_len": None},
        }
    ]
    assert db.query_count == 4
    assert db.remaining_query_rows == [quote_rows]


def test_relink_candidates_with_the_stale_chunk_id_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    stale_chunk_id = uuid.uuid4()
    doc_pipeline_key = f"{document_id}:hash-2"
    quote = "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    reference_source = {
        "document_id": str(document_id),
        "chunk_id": str(stale_chunk_id),
        "doc_pipeline_key": doc_pipeline_key,
        "chunk_index": 4,
        "quote": quote,
    }
    item = _make_item(reference_source)
    stale_exact_row = (
        stale_chunk_id,
        document_id,
        4,
        {"pipeline_hash": "hash-2", "doc_pipeline_key": doc_pipeline_key},
        6,
        40,
        90,
        None,
    )
    stale_quote_row = stale_exact_row[:-1]

    _force_chunk_missing(monkeypatch)
    db = _FakeDB(
        [item],
        [(document_id, dataset_id, "pdf", {"active_pipeline_hash": "hash-2"})],
        [],
        [stale_exact_row],
        [stale_quote_row],
    )

    result = _run_repair(
        db,
        tenant_id=tenant_id,
        suite_id=suite_id,
        dataset_id=dataset_id,
        apply=True,
    )

    assert result["repaired_references"] == 0
    assert result["changes"] == [
        {
            "suite_id": str(suite_id),
            "item_id": str(item.id),
            "item_status": "review",
            "document_id": str(document_id),
            "chunk_id_before": str(stale_chunk_id),
            "chunk_id_after": None,
            "reason": "chunk_missing",
            "repaired": False,
            "method": None,
            "meta": {},
        }
    ]
    assert item.reference_sources == [reference_source]
    assert db.query_count == 5
    assert db.added == []
    assert db.commit_count == 0
    assert db.refreshed == []
    assert db.rollback_count == 0


def test_ambiguous_quote_matches_choose_the_lowest_chunk_index(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    stale_chunk_id = uuid.uuid4()
    higher_chunk_id = uuid.uuid4()
    lowest_chunk_id = uuid.uuid4()
    doc_pipeline_key = f"{document_id}:hash-2"
    quote = "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    reference_source = {
        "document_id": str(document_id),
        "chunk_id": str(stale_chunk_id),
        "quote": quote,
        "page_number": 1,
    }
    item = _make_item(reference_source)

    _force_chunk_missing(monkeypatch)
    monkeypatch.setattr(repair_mod, "audit_log_event", lambda _db, **_kwargs: None, raising=True)
    db = _FakeDB(
        [item],
        [(document_id, dataset_id, "pdf", {"active_pipeline_hash": "hash-2"})],
        [],
        [
            (
                higher_chunk_id,
                document_id,
                9,
                {"pipeline_hash": "hash-2", "doc_pipeline_key": doc_pipeline_key},
                10,
                200,
                250,
            ),
            (
                lowest_chunk_id,
                document_id,
                2,
                {"pipeline_hash": "hash-2", "doc_pipeline_key": doc_pipeline_key},
                3,
                20,
                70,
            ),
        ],
    )

    result = _run_repair(
        db,
        tenant_id=tenant_id,
        suite_id=suite_id,
        dataset_id=dataset_id,
        apply=True,
    )

    assert result["repaired_references"] == 1
    assert result["changes"][0]["chunk_id_after"] == str(lowest_chunk_id)
    assert result["changes"][0]["method"] == "quote_needle"
    assert item.reference_sources == [
        {
            "document_id": str(document_id),
            "chunk_id": str(lowest_chunk_id),
            "quote": quote,
            "page_number": 3,
            "chunk_index": 2,
            "pipeline_hash": "hash-2",
            "doc_pipeline_key": doc_pipeline_key,
            "start_char": 20,
            "end_char": 70,
        }
    ]
    assert db.query_count == 4


def test_successful_dry_run_reports_repair_without_db_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    stale_chunk_id = uuid.uuid4()
    repaired_chunk_id = uuid.uuid4()
    doc_pipeline_key = f"{document_id}:hash-2"
    quote = "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    reference_source = {
        "document_id": str(document_id),
        "chunk_id": str(stale_chunk_id),
        "quote": quote,
    }
    item = _make_item(reference_source)
    audit_calls: list[dict[str, object]] = []

    _force_chunk_missing(monkeypatch)
    monkeypatch.setattr(
        repair_mod,
        "audit_log_event",
        lambda _db, **kwargs: audit_calls.append(kwargs),
        raising=True,
    )
    db = _FakeDB(
        [item],
        [(document_id, dataset_id, "pdf", {"active_pipeline_hash": "hash-2"})],
        [],
        [
            (
                repaired_chunk_id,
                document_id,
                3,
                {"pipeline_hash": "hash-2", "doc_pipeline_key": doc_pipeline_key},
                4,
                30,
                80,
            )
        ],
    )

    result = _run_repair(
        db,
        tenant_id=tenant_id,
        suite_id=suite_id,
        dataset_id=dataset_id,
        apply=False,
    )

    assert result["applied"] is False
    assert result["drifted_references"] == 1
    assert result["repaired_references"] == 1
    assert result["changes"][0]["repaired"] is True
    assert result["changes"][0]["chunk_id_after"] == str(repaired_chunk_id)
    assert item.reference_sources == [reference_source]
    assert db.added == []
    assert db.commit_count == 0
    assert db.refreshed == []
    assert db.rollback_count == 0
    assert audit_calls == []


def test_audit_failure_preserves_committed_repair_and_rolls_back_audit_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    stale_chunk_id = uuid.uuid4()
    repaired_chunk_id = uuid.uuid4()
    doc_pipeline_key = f"{document_id}:hash-2"
    reference_source = {
        "document_id": str(document_id),
        "chunk_id": str(stale_chunk_id),
        "doc_pipeline_key": doc_pipeline_key,
        "chunk_index": 5,
    }
    item = _make_item(reference_source)
    audit_calls: list[dict[str, object]] = []

    def fail_audit(_db, **kwargs) -> None:
        audit_calls.append(kwargs)
        raise RuntimeError("audit unavailable")

    _force_chunk_missing(monkeypatch)
    monkeypatch.setattr(repair_mod, "audit_log_event", fail_audit, raising=True)
    db = _FakeDB(
        [item],
        [(document_id, dataset_id, "pdf", {"active_pipeline_hash": "hash-2"})],
        [],
        [
            (
                repaired_chunk_id,
                document_id,
                5,
                {"pipeline_hash": "hash-2", "doc_pipeline_key": doc_pipeline_key},
                8,
                100,
                160,
                None,
            )
        ],
    )

    result = _run_repair(
        db,
        tenant_id=tenant_id,
        suite_id=suite_id,
        dataset_id=dataset_id,
        apply=True,
        actor_id="acct-456",
    )

    assert result["applied"] is True
    assert result["repaired_references"] == 1
    assert item.reference_sources == [
        {
            "document_id": str(document_id),
            "chunk_id": str(repaired_chunk_id),
            "doc_pipeline_key": doc_pipeline_key,
            "chunk_index": 5,
            "pipeline_hash": "hash-2",
            "page_number": 8,
            "start_char": 100,
            "end_char": 160,
        }
    ]
    assert db.added == [item]
    assert db.commit_count == 1
    assert db.refreshed == [item]
    assert db.rollback_count == 1
    assert len(audit_calls) == 1
    assert audit_calls[0]["actor_id"] == "acct-456"
