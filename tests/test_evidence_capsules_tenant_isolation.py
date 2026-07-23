import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import HTTPException

from app.rag.core.hashing import stable_json_hash


def _build_capsule() -> dict:
    citation = {
        "document_id": "doc-1",
        "chunk_id": "chunk-1",
        "evidence_anchor_hash": "anchor-1",
    }
    citation["citation_hash"] = stable_json_hash(citation, length=16)
    payload = {
        "schema": "mimirq.evidence_capsule.v1",
        "generated_at": "2026-07-23T00:00:00+00:00",
        "query_for_retrieval": "tenant isolated capsule",
        "request_context": {},
        "retrieval_summary": {
            "retrieval_mode": "",
            "retrieval_elapsed_sec": None,
            "retrieval_config_hash": "",
            "citations_count": 1,
            "top_relevance_score": None,
            "abstain_triggered": None,
            "abstain_reason": "",
        },
        "must_recall": {
            "status": "",
            "passed": None,
            "enabled": None,
            "missing_source_keys": [],
            "required_anchor_fields": [],
            "anchor_missing_counts": {},
            "fail_reasons": [],
        },
        "retrieval_contract": {
            "mode": "",
            "policy": {},
            "hard_fallback_used": None,
            "secondary_pass_used": None,
        },
        "quality": {
            "parse_risk_level": "",
            "parse_risk_score": None,
            "parse_quality_alert": None,
            "parse_quality_gate_blocked": None,
        },
        "citations": [citation],
        "citation_hashes": [citation["citation_hash"]],
        "retrieval_trace": {},
        "query_debug": None,
    }
    payload["capsule_hash"] = stable_json_hash(payload, length=24)
    return payload


def _load_evidence_capsules_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    auth_module = ModuleType("app.api.dependencies.auth")
    auth_module.get_current_account_id = lambda: None
    tenant_module = ModuleType("app.api.dependencies.tenant")
    tenant_module.get_tenant_id = lambda: None
    database_module = ModuleType("app.core.database")
    database_module.get_db = lambda: None
    capsule_builder_module = ModuleType("app.rag.core.evidence_capsule_builder")
    capsule_builder_module.validate_evidence_capsule = lambda capsule, strict=None, verify_signature=None: (True, "ok")
    dataset_service_module = ModuleType("app.services.dataset_service")

    class _DatasetService:
        @staticmethod
        def ensure_member(db, tenant_id, account_id):  # noqa: ANN001
            return object()

    dataset_service_module.DatasetService = _DatasetService

    monkeypatch.setitem(sys.modules, "app.api.dependencies.auth", auth_module)
    monkeypatch.setitem(sys.modules, "app.api.dependencies.tenant", tenant_module)
    monkeypatch.setitem(sys.modules, "app.core.database", database_module)
    monkeypatch.setitem(sys.modules, "app.rag.core.evidence_capsule_builder", capsule_builder_module)
    monkeypatch.setitem(sys.modules, "app.services.dataset_service", dataset_service_module)

    module_path = Path(__file__).resolve().parents[1] / "app/api/v1/evidence_capsules.py"
    spec = importlib.util.spec_from_file_location("tests.evidence_capsules_module", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_capsules_are_bucketed_by_tenant_and_bound_in_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    capsule_id = "shared-capsule-id"
    module = _load_evidence_capsules_module(monkeypatch)

    monkeypatch.setattr(module.settings, "EVIDENCE_CAPSULE_STORE_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(module.DatasetService, "ensure_member", staticmethod(lambda db, tenant_id, account_id: object()))

    capsule_a = _build_capsule()
    response_a = module.persist_evidence_capsule(
        module.EvidenceCapsulePersistRequest(capsule=capsule_a, capsule_id=capsule_id),
        tenant_id=tenant_a,
        account_id="user-a",
        db=object(),
    )
    capsule_b = _build_capsule()
    response_b = module.persist_evidence_capsule(
        module.EvidenceCapsulePersistRequest(capsule=capsule_b, capsule_id=capsule_id),
        tenant_id=tenant_b,
        account_id="user-b",
        db=object(),
    )

    assert response_a.capsule_id == capsule_id
    assert response_b.capsule_id == capsule_id
    assert response_a.path != response_b.path

    payload_a = json.loads((tmp_path / str(tenant_a) / f"{capsule_id}.json").read_text(encoding="utf-8"))
    payload_b = json.loads((tmp_path / str(tenant_b) / f"{capsule_id}.json").read_text(encoding="utf-8"))
    assert payload_a["tenant_id"] == str(tenant_a)
    assert payload_b["tenant_id"] == str(tenant_b)
    assert payload_a["capsule_id"] == capsule_id
    assert payload_b["capsule_id"] == capsule_id
    assert payload_a["capsule"] == capsule_a
    assert payload_b["capsule"] == capsule_b
    stored_capsule = dict(payload_a["capsule"])
    stored_hash = stored_capsule.pop("capsule_hash")
    assert stable_json_hash(stored_capsule, length=24) == stored_hash

    got_a = module.get_evidence_capsule(capsule_id, tenant_id=tenant_a, account_id="user-a", db=object())
    got_b = module.get_evidence_capsule(capsule_id, tenant_id=tenant_b, account_id="user-b", db=object())
    assert got_a.capsule == capsule_a
    assert got_b.capsule == capsule_b

    with pytest.raises(HTTPException, match="capsule_not_found"):
        module.get_evidence_capsule(capsule_id, tenant_id=uuid.uuid4(), account_id="user-c", db=object())

    mismatched = _build_capsule()
    mismatched["tenant_id"] = str(tenant_b)
    with pytest.raises(HTTPException, match="capsule_tenant_id_mismatch"):
        module.persist_evidence_capsule(
            module.EvidenceCapsulePersistRequest(capsule=mismatched, capsule_id="mismatch-capsule"),
            tenant_id=tenant_a,
            account_id="user-a",
            db=object(),
        )


def test_legacy_global_capsule_file_is_not_used_as_cross_tenant_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    capsule_id = "legacy-capsule-id"
    module = _load_evidence_capsules_module(monkeypatch)
    legacy_capsule = _build_capsule()
    legacy_capsule["tenant_id"] = str(uuid.uuid4())
    legacy_path = tmp_path / f"{capsule_id}.json"
    legacy_path.write_text(json.dumps(legacy_capsule), encoding="utf-8")

    monkeypatch.setattr(module.settings, "EVIDENCE_CAPSULE_STORE_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(module.DatasetService, "ensure_member", staticmethod(lambda db, tenant_id, account_id: object()))

    with pytest.raises(HTTPException, match="capsule_not_found"):
        module.get_evidence_capsule(capsule_id, tenant_id=tenant_id, account_id="user-a", db=object())
