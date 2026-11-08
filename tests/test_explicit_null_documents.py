import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException


class FalsyMapping(dict):
    def __bool__(self):
        return False


class FalsyDateTime(datetime):
    def __bool__(self):
        return False


@pytest.mark.parametrize("provided", [False, True])
@pytest.mark.parametrize("denied", [False, True])
def test_dataset_selection_preserves_both_asset_authorization_checks(monkeypatch, provided, denied) -> None:
    from app.services import document_asset_access as service

    class Dataset(SimpleNamespace):
        def __bool__(self):
            return False

    tenant, dataset_id = uuid4(), uuid4()
    dataset = Dataset(id=dataset_id, tenant_id=tenant)
    document = SimpleNamespace(dataset_id=dataset_id)
    looked_up, checks = [], []

    def lookup(db, actual_tenant, actual_dataset):
        assert not provided, "a supplied dataset must not be replaced"
        looked_up.append((actual_tenant, actual_dataset))
        return dataset

    def dataset_acl(db, actual_dataset, account_id):
        assert actual_dataset is dataset
        checks.append("dataset")
        if denied:
            raise HTTPException(status_code=403, detail="denied")

    def document_acl(db, **kwargs):
        assert kwargs["dataset"] is dataset
        checks.append("document")

    monkeypatch.setattr(service.dataset_service, "get_dataset", lookup)
    monkeypatch.setattr(service.dataset_service, "assert_dataset_readable", dataset_acl)
    monkeypatch.setattr(service, "assert_document_acl_readable", document_acl)
    kwargs = dict(tenant_id=tenant, account_id="account", document=document, dataset=dataset if provided else None)
    if denied:
        with pytest.raises(HTTPException) as error:
            service.assert_document_asset_readable(object(), **kwargs)
        assert error.value.status_code == 403
        assert checks == ["dataset"]
    else:
        service.assert_document_asset_readable(object(), **kwargs)
        assert checks == ["dataset", "document"]
    assert len(looked_up) == (0 if provided else 1)


def test_provenance_upsert_preserves_falsy_metadata_and_snapshot(monkeypatch) -> None:
    from app.services import pipeline_provenance_service as service

    monkeypatch.setattr(service, "_now_iso", lambda: "2026-11-07T00:00:00+00:00")
    metadata = FalsyMapping(preserved=0, enabled=False)
    snapshot = FalsyMapping(attempts=0, enabled=False)
    result = service.upsert_pipeline_provenance_version(metadata, pipeline_hash="pipeline", snapshot=snapshot)
    assert result["preserved"] == 0
    assert result["enabled"] is False
    assert result["pipeline_provenance_versions"]["pipeline"]["attempts"] == 0
    assert result["pipeline_provenance_versions"]["pipeline"]["enabled"] is False
    assert "pipeline_provenance_versions" not in metadata
    assert "pipeline_hash" not in snapshot


def test_provenance_snapshot_preserves_zero_false_and_privacy_projection() -> None:
    from app.services.pipeline_provenance_service import build_pipeline_version_snapshot

    result = build_pipeline_version_snapshot(
        meta=FalsyMapping(
            pipeline_hash="pipeline",
            parser_backend="basic",
            pipeline_effective={"chunk_size": 0, "chunk_overlap": 0, "governance_enabled": False},
            preprocess={"size_before": 0, "changed": False, "internal_path": "/private/file"},
        ),
        created_at="2026-11-07T00:00:00+00:00",
        build_sha="build",
        embedding_space_hash="space",
    )
    assert result["pipeline_hash"] == "pipeline"
    assert result["parser_backend"] == "basic"
    assert result["transforms"]["chunk"]["chunk_size"] == 0
    assert result["transforms"]["governance"]["enabled"] is False
    assert result["transforms"]["preprocess"]["result"] == {"size_before": 0, "changed": False}


def test_parse_quality_schema_preserves_falsy_evidence_mapping() -> None:
    from app.parsing.processors.parse_quality_schema import ParseQualityGateDecision

    result = ParseQualityGateDecision(
        grade="pass", needs_review=False, flags={}, actions={}, evidence=FalsyMapping(score=0, enabled=False)
    ).to_metadata()
    assert result["evidence"] == {"score": 0, "enabled": False}


def test_parse_quality_gate_preserves_falsy_document_metadata() -> None:
    from app.parsing.processors.parse_quality_gate import apply_parse_quality_gate_metadata

    result = apply_parse_quality_gate_metadata(FalsyMapping(pipeline_hash="pipeline", parse_quality={"score": 0}))
    assert result["pipeline_hash"] == "pipeline"
    assert result["parse_quality"]["score"] == 0
    assert "parse_quality_gate" in result


@pytest.mark.parametrize("enabled", [False, True])
def test_vlm_decision_keeps_a_zero_score_in_a_falsy_mapping(enabled) -> None:
    from app.parsing.processors.vlm_correction import should_apply_vlm_correction

    result = should_apply_vlm_correction(
        enabled=enabled, pdf_quality=FalsyMapping(table_quality_score=0), min_table_score=0.5
    )
    assert result is enabled


def test_hit_frequency_uses_the_explicit_clock(monkeypatch, tmp_path) -> None:
    from app.services import document_retrieval_hit_frequency as service

    tenant, document = uuid4(), uuid4()
    path = tmp_path / "metrics.jsonl"
    path.write_text(
        json.dumps(
            {
                "event": "rag_trace",
                "tenant_id": str(tenant),
                "ts_ms": 90_000,
                "citations": [{"document_id": str(document), "chunk_id": "chunk"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(service.settings, "ENABLE_METRICS_LOG", True)
    monkeypatch.setattr(service.settings, "METRICS_LOG_PATH", str(path))
    result = service.compute_document_retrieval_hit_frequency(
        tenant_id=tenant,
        document_id=document,
        window_minutes=1,
        now=FalsyDateTime(1970, 1, 1, 0, 2, tzinfo=UTC),
    )
    assert result["traces_scanned"] == 1
    assert result["citations_matched"] == 1
    assert result["hit_rate"] == 1.0


@pytest.mark.parametrize("provided", [False, True])
def test_index_channel_uses_the_supplied_status_timestamp(monkeypatch, provided) -> None:
    from app.services import document_index_channel_service as service

    class Query:
        def filter(self, *args):
            return self

        def first(self):
            return None

    class Database:
        def query(self, model):
            return Query()

        def add(self, row):
            pass

        def flush(self):
            pass

    timestamp = FalsyDateTime(2000, 1, 1, tzinfo=UTC)
    default = datetime(2026, 11, 7, tzinfo=UTC)
    monkeypatch.setattr(service, "_utcnow", lambda: default)
    monkeypatch.setattr(service, "_supports_atomic_postgresql_upsert", lambda db: False)
    result = service.upsert_document_index_channel(
        Database(),
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        document_id=uuid4(),
        pipeline_hash="pipeline",
        channel="vector",
        required=False,
        enabled=False,
        status="pending",
        attempt_count=0,
        last_status_changed_at=timestamp if provided else None,
    )
    assert result.last_status_changed_at is (timestamp if provided else default)
    assert result.attempt_count == 0
    assert result.enabled is False
