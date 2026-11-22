from datetime import UTC, datetime, timedelta
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import JSON, MetaData, create_engine
from sqlalchemy.orm import Session

from app.infrastructure.hashing import stable_hash
from app.models.audit_log import AuditLog
from app.models.evaluation.results import RagasRegressionItem, RagasRegressionRun
from app.services.evaluation.run_bundle import export_regression_run_bundle
from app.services.observability import audit_retention as retention


@pytest.fixture
def audit_db():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    table = AuditLog.__table__.to_metadata(metadata)
    table.c.details.type = JSON()
    metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _add_audit_row(db: Session, tenant_id, *, days_old: int, action: str = "document.read"):
    row = AuditLog(
        id=uuid4(),
        tenant_id=tenant_id,
        action=action,
        details={},
        created_at=datetime.now(UTC) - timedelta(days=days_old),
    )
    db.add(row)
    db.commit()
    return row.id


@pytest.mark.parametrize("filtered", [False, True])
def test_audit_purge_consumes_real_sqlalchemy_rows_with_tenant_and_limit(audit_db, filtered):
    tenant_id = uuid4()
    other_tenant = uuid4()
    first = _add_audit_row(audit_db, tenant_id, days_old=100)
    second = _add_audit_row(audit_db, tenant_id, days_old=99)
    recent = _add_audit_row(audit_db, tenant_id, days_old=1)
    foreign = _add_audit_row(audit_db, other_tenant, days_old=100)
    cutoff = datetime.now(UTC) - timedelta(days=90)

    if filtered:
        kwargs = {"tenant_id": tenant_id, "max_delete": 1, "until": cutoff, "action": "document.read"}
        assert retention.plan_filtered_audit_log_purge(audit_db, **kwargs) == 1
        assert retention.purge_filtered_audit_log_rows(audit_db, **kwargs) == 1
    else:
        kwargs = {"tenant_id": tenant_id, "max_delete": 1, "cutoff": cutoff}
        assert retention.plan_audit_log_purge(audit_db, **kwargs) == 1
        assert retention.purge_audit_log_rows(audit_db, **kwargs) == 1

    assert {row_id for (row_id,) in audit_db.query(AuditLog.id).all()} == {second, recent, foreign}
    assert audit_db.get(AuditLog, first) is None


@pytest.mark.parametrize("filtered", [False, True])
def test_audit_purge_plan_does_not_report_database_failure_as_empty(audit_db, monkeypatch, filtered):
    def broken_query(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(audit_db, "query", broken_query)
    with pytest.raises(RuntimeError, match="database unavailable"):
        if filtered:
            retention.plan_filtered_audit_log_purge(audit_db, tenant_id=uuid4(), max_delete=1)
        else:
            retention.plan_audit_log_purge(audit_db, tenant_id=uuid4(), cutoff=datetime.now(UTC), max_delete=1)


@pytest.mark.parametrize("commit", [False, True])
def test_audit_delete_rolls_back_and_exposes_transaction_failure(audit_db, monkeypatch, commit):
    tenant_id = uuid4()
    row_id = _add_audit_row(audit_db, tenant_id, days_old=100)

    def fail_transaction():
        raise RuntimeError("transaction failed")

    monkeypatch.setattr(audit_db, "commit" if commit else "flush", fail_transaction)
    with pytest.raises(RuntimeError, match="transaction failed"):
        retention.delete_audit_log_rows(audit_db, tenant_id=tenant_id, ids=[row_id], commit=commit)

    monkeypatch.undo()
    assert audit_db.get(AuditLog, row_id) is not None


def test_audit_delete_keeps_other_tenant_rows(audit_db):
    tenant_id = uuid4()
    row_id = _add_audit_row(audit_db, uuid4(), days_old=100)
    assert retention.delete_audit_log_rows(audit_db, tenant_id=tenant_id, ids=[row_id]) == 0
    assert audit_db.get(AuditLog, row_id) is not None


def _regression_records():
    now = datetime(2026, 10, 26, tzinfo=UTC)
    run = RagasRegressionRun(
        id=uuid4(),
        tenant_id=uuid4(),
        dataset_id=None,
        status="completed",
        metrics=["faithfulness"],
        params={"top_k": 5},
        summary={"faithfulness": 0.8},
        created_at=now,
    )
    item = RagasRegressionItem(
        case_id=uuid4(),
        question="Question",
        response="Answer",
        scores={"faithfulness": 0.8},
        meta={},
        citations=[],
        retrieved_contexts=["private context"],
        created_at=now,
    )
    return run, item, now


def test_regression_bundle_serializes_typed_uuid_datetime_and_redacts_text():
    run, item, now = _regression_records()
    bundle = export_regression_run_bundle(run, [item], now=now)
    assert bundle["generated_at"] == "2026-10-26T00:00:00Z"
    assert bundle["run"]["id_hash"] == stable_hash(str(run.id), length=16)
    assert bundle["items"][0]["case_id_hash"] == stable_hash(str(item.case_id), length=16)
    assert "id" not in bundle["run"]
    assert "dataset_id" not in bundle["run"]
    assert "question" not in bundle["items"][0]
    assert "retrieved_contexts" not in bundle["items"][0]
    unredacted = export_regression_run_bundle(
        run, [item], redact_ids=False, include_text=True, include_contexts=True, now=now
    )
    assert unredacted["run"]["id"] == str(run.id)
    assert unredacted["items"][0]["retrieved_contexts"] == ["private context"]


def test_regression_bundle_does_not_hide_invalid_model_timestamp():
    run, item, now = _regression_records()
    run.created_at = SimpleNamespace()
    with pytest.raises(AttributeError):
        export_regression_run_bundle(run, [item], now=now)


def test_regression_bundle_does_not_default_invalid_typed_limits():
    run, item, now = _regression_records()
    with pytest.raises(TypeError):
        export_regression_run_bundle(run, [item], max_items="invalid", now=now)


def test_regression_bundle_retains_context_privacy_requirement():
    run, item, now = _regression_records()
    with pytest.raises(ValueError, match="requires include_text"):
        export_regression_run_bundle(run, [item], include_contexts=True, now=now)


_NUMERIC_BOUNDARY_HELPERS = [
    ("app.services.chunking.quality_gate", "_as_int", 0),
    ("app.services.chunking.quality_gate", "_as_float", 0.0),
    ("app.rag.ingestion.parsing.utils.scalars", "coerce_int", None),
    ("app.rag.ingestion.parsing.utils.scalars", "coerce_float", None),
    ("app.rag.ingestion.parsing.quality.reading_order", "_coerce_int", None),
    ("app.rag.ingestion.parsing.quality.reading_order", "_coerce_float", None),
    ("app.services.datasets.profile_statistics", "safe_int", 0),
    ("app.services.datasets.profile_statistics", "safe_float", 0.0),
    ("app.services.reports.html", "_fmt_int", "0"),
    ("app.services.reports.html", "_fmt_bytes", "0 B"),
]


@pytest.mark.parametrize(("module_name", "helper_name", "fallback"), _NUMERIC_BOUNDARY_HELPERS)
def test_numeric_boundaries_keep_invalid_external_value_fallbacks(module_name, helper_name, fallback):
    helper = getattr(import_module(module_name), helper_name)
    for invalid in ("not-a-number", object(), None):
        assert helper(invalid) == fallback


@pytest.mark.parametrize(("module_name", "helper_name", "_fallback"), _NUMERIC_BOUNDARY_HELPERS)
def test_numeric_boundaries_expose_unexpected_conversion_errors(module_name, helper_name, _fallback):
    class BrokenNumeric:
        def __int__(self):
            raise RuntimeError("broken numeric implementation")

        def __float__(self):
            raise RuntimeError("broken numeric implementation")

    helper = getattr(import_module(module_name), helper_name)
    with pytest.raises(RuntimeError, match="broken numeric implementation"):
        helper(BrokenNumeric())


def test_metadata_bbox_keeps_malformed_coordinates_and_exposes_implementation_error():
    from app.rag.ingestion.parsing.enrich.table_image_algorithms import _bbox

    assert _bbox({"left": "invalid", "top": 0, "right": 1, "bottom": 2}) is None
    assert _bbox({"left": "1", "top": 0, "right": 3, "bottom": 4}) == (1.0, 0.0, 3.0, 4.0)

    class BrokenCoordinate:
        def __float__(self):
            raise RuntimeError("coordinate implementation failed")

    with pytest.raises(RuntimeError, match="coordinate implementation failed"):
        _bbox({"left": BrokenCoordinate(), "top": 0, "right": 1, "bottom": 2})


def _failing_milvus_count():
    from app.storage.vector.milvus import MilvusVectorStore

    class FailedCollection:
        @property
        def num_entities(self):
            raise RuntimeError("Milvus RPC unavailable")

    store = SimpleNamespace(_require_store=lambda: SimpleNamespace(col=FailedCollection()))
    return MilvusVectorStore.get_collection_count(store)


def test_milvus_collection_count_exposes_rpc_failure():
    with pytest.raises(RuntimeError, match="Milvus RPC unavailable"):
        _failing_milvus_count()


def test_vector_health_reports_failed_milvus_count_as_disconnected():
    from app.infrastructure.observability.health import check_vector

    vector, milvus, ok = check_vector(
        SimpleNamespace(VECTOR_BACKEND="milvus", DATA_REGION=""),
        mode="health",
        milvus_get_collection_count=_failing_milvus_count,
    )
    assert ok is False
    assert vector["status"] == "disconnected"
    assert milvus["status"] == "disconnected"
    assert "Milvus RPC unavailable" in milvus["error"]
