
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1 import router as v1_router
from app.core.database import get_db


class _DummyDB:
    pass


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


def _override_get_current_account_id() -> str:
    return "test-account"


def test_dataset_report_endpoint_exists(monkeypatch):  # noqa: ANN001
    """Contract test: reports endpoint exists and returns key sections."""
    dataset_id = uuid.uuid4()

    import app.api.v1.reports as reports_module
    from app.api.schemas.dataset_profile import DatasetProfileSummary
    from app.api.schemas.document_folders import DocumentFolderNode, DocumentFolderTreeResponse
    from app.api.schemas.report import ComplianceSummary, DatasetReportOut, DatasetRetrievalAuditOut

    dummy_profile = DatasetProfileSummary(
        dataset_id=dataset_id,
        generated_at="2026-01-01T00:00:00Z",
        total_documents=3,
        by_status={"completed": 2, "failed": 1},
    )
    dummy_folders = DocumentFolderTreeResponse(
        dataset_id=dataset_id,
        total_documents=3,
        total_with_source_path=2,
        root=DocumentFolderNode(name="", path="", depth=0, documents=3, children=[]),
    )
    dummy_report = DatasetReportOut(
        dataset_id=dataset_id,
        dataset_name="Test Dataset",
        pipeline_hash=None,
        generated_at="2026-01-01T00:00:00Z",
        profile=dummy_profile,
        compliance=ComplianceSummary(quarantined_documents=0, failed_documents=1),
        pipeline_versions=[],
        connectors=[],
        dataset_metadata={},
        folder_tree=dummy_folders,
        retrieval_audit=DatasetRetrievalAuditOut(
            status="failed",
            plugin_refs=["plugin:demo@1.0.0:chunk"],
            plugin_package_hashes=["abc123"],
            failure_categories={"scope": 1},
            recommended_next_action="Fix expected metadata scope.",
        ),
    )
    monkeypatch.setattr(
        reports_module.ReportService,
        "build_dataset_report",
        lambda *_a, **_k: dummy_report,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(v1_router, prefix="/api/v1")
    client = TestClient(app)

    res = client.get(f"/api/v1/reports/datasets/{dataset_id}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert "dataset_id" in body
    assert "generated_at" in body
    assert "profile" in body
    assert "compliance" in body
    assert "connectors" in body
    assert "folder_tree" in body
    assert "governance_metrics" in body
    assert "governance_audit" in body
    assert "chunk_quality_metrics" in body
    assert "kg_stats" in body
    assert "latest_regression_run" in body
    assert "must_recall_summary" in body
    assert "retrieval_audit" in body
    assert body["retrieval_audit"]["status"] == "failed"
    assert body["retrieval_audit"]["plugin_refs"] == ["plugin:demo@1.0.0:chunk"]
    assert body["retrieval_audit"]["plugin_package_hashes"] == ["abc123"]
    assert body["retrieval_audit"]["failure_categories"] == {"scope": 1}
    assert body["folder_tree"]["total_documents"] == 3


def test_dataset_retrieval_audit_summary_categorizes_regression_failures() -> None:
    from app.api.schemas.report import DatasetRegressionRunSummaryOut
    from app.services.report_service import _build_retrieval_audit_summary

    latest = DatasetRegressionRunSummaryOut(
        run_id=uuid.UUID("00000000-0000-0000-0000-000000000111"),
        status="completed",
        metrics=["retrieval_hit_at_1"],
        params={"plugin_refs": ["plugin:demo@1.0.0:chunk"]},
        summary={
            "hit_at_1": 0.5,
            "hit_at_3": 1.0,
            "retrieval_recall": 1.0,
            "retrieval_effective_context_rate": 0.7,
            "retrieval_noise_rate": 0.25,
            "expected_metadata_hit_rate": 0.8,
            "expected_metadata_recall": 0.9,
            "kg_noise_rate": 0.2,
            "plugin_package_hash": "hash-secret-free",
            "raw_context": "SHOULD_NOT_LEAK_RAW_CHUNK_TEXT",
        },
    )

    audit = _build_retrieval_audit_summary(latest_regression_run=latest)

    assert audit is not None
    assert audit.status == "failed"
    assert audit.plugin_refs == ["plugin:demo@1.0.0:chunk"]
    assert audit.plugin_package_hashes == ["hash-secret-free"]
    assert audit.failure_categories == {
        "chunking": 1,
        "kg_noise": 1,
        "ranking": 1,
        "scope": 1,
    }
    assert audit.gates
    assert audit.gates[0].name == "latest_regression_run"
    assert "raw_context" not in audit.gates[0].metrics
    assert audit.recommended_next_action == "Fix metadata scope, chunking, ranking, and KG noise before enabling production retrieval."


def test_dataset_retrieval_audit_summary_uses_dataset_metadata_snapshot_without_regression_run() -> None:
    from app.services.report_service import _build_retrieval_audit_summary

    audit = _build_retrieval_audit_summary(
        latest_regression_run=None,
        dataset_metadata={
            "retrieval_audit": {
                "status": "failed",
                "plugin_refs": ["plugin:changzhou-gov@0.1.0:chunk", "plugin:changzhou-gov@0.1.0:chunk"],
                "plugin_package_hashes": ["sha256:abc123"],
                "failure_categories": {"scope": 1, "kg_noise": 1, "raw_context": 99},
                "recommended_next_action": "Fix persisted readiness evidence.",
                "gates": [
                    {
                        "name": "mimirq_direct",
                        "status": "failed",
                        "source": "changzhou_dify_readiness:mimirq_direct",
                        "generated_at": "2026-06-09T01:02:03Z",
                        "metrics": {
                            "hit_at_1": 0.75,
                            "expected_metadata_hit_rate": 0.5,
                            "kg_noise_rate": 0.2,
                            "raw_context": "SHOULD_NOT_LEAK_RAW_CHUNK_TEXT",
                            "api_key": "SHOULD_NOT_LEAK_SECRET",
                        },
                        "failed_conditions": ["hit_at_1_below_threshold"],
                    }
                ],
                "raw_query": "SHOULD_NOT_LEAK_QUERY",
            }
        },
    )

    assert audit is not None
    assert audit.status == "failed"
    assert audit.plugin_refs == ["plugin:changzhou-gov@0.1.0:chunk"]
    assert audit.plugin_package_hashes == ["sha256:abc123"]
    assert audit.failure_categories == {"scope": 1, "kg_noise": 1}
    assert audit.gates[0].name == "mimirq_direct"
    assert audit.gates[0].metrics == {
        "hit_at_1": 0.75,
        "expected_metadata_hit_rate": 0.5,
        "kg_noise_rate": 0.2,
    }
    assert audit.recommended_next_action == "Fix metadata scope and KG noise before enabling production retrieval."


def test_dataset_retrieval_audit_summary_categorizes_adapter_binding_failure() -> None:
    from app.services.report_service import _build_retrieval_audit_summary

    audit = _build_retrieval_audit_summary(
        latest_regression_run=None,
        dataset_metadata={
            "retrieval_audit": {
                "status": "failed",
                "gates": [
                    {
                        "name": "mimirq_direct",
                        "status": "passed",
                        "source": "external_readiness:mimirq_direct",
                        "metrics": {
                            "cases": 12,
                            "hit_at_1": 1.0,
                        },
                    },
                    {
                        "name": "external_probe",
                        "status": "failed",
                        "source": "external_readiness:external_probe",
                        "metrics": {
                            "dify_hit_nonempty": 0,
                            "probe_errors": 0,
                        },
                        "failed_conditions": ["endpoint_host_is_loopback"],
                    }
                ],
            }
        },
    )

    assert audit is not None
    assert audit.status == "failed"
    assert audit.failure_categories == {"adapter": 1}
    assert audit.recommended_next_action == "Fix adapter binding before enabling production retrieval."


def test_dataset_retrieval_audit_summary_failed_run_without_categories_is_not_marked_passed() -> None:
    from app.api.schemas.report import DatasetRegressionRunSummaryOut
    from app.services.report_service import _build_retrieval_audit_summary

    latest = DatasetRegressionRunSummaryOut(
        run_id=uuid.UUID("00000000-0000-0000-0000-000000000333"),
        status="failed",
        metrics=[],
        params={},
        summary={},
        error_message="No regression cases found",
    )

    audit = _build_retrieval_audit_summary(latest_regression_run=latest)

    assert audit is not None
    assert audit.status == "failed"
    assert audit.failure_categories == {}
    assert audit.recommended_next_action == "Inspect failed retrieval gates before enabling production retrieval."


def test_dataset_retrieval_audit_summary_merges_regression_and_dataset_metadata_snapshot() -> None:
    from app.api.schemas.report import DatasetRegressionRunSummaryOut
    from app.services.report_service import _build_retrieval_audit_summary

    latest = DatasetRegressionRunSummaryOut(
        run_id=uuid.UUID("00000000-0000-0000-0000-000000000222"),
        status="completed",
        metrics=["retrieval_hit_at_1"],
        params={"plugin_refs": ["plugin:demo@1.0.0:chunk"]},
        summary={
            "hit_at_1": 1.0,
            "hit_at_3": 1.0,
            "retrieval_recall": 0.5,
            "plugin_package_hash": "hash-regression",
        },
    )

    audit = _build_retrieval_audit_summary(
        latest_regression_run=latest,
        dataset_metadata={
            "retrieval_audit": {
                "status": "failed",
                "plugin_refs": ["plugin:external@2.0.0:chunk"],
                "plugin_package_hashes": ["hash-external"],
                "failure_categories": {"kg_noise": 1},
                "gates": [
                    {
                        "name": "kg_compare",
                        "status": "failed",
                        "metrics": {"kg_noise_rate": 0.2},
                        "failed_conditions": ["kg_noise_rate_above_threshold"],
                        "source": "external_readiness:kg_compare",
                    }
                ],
            }
        },
    )

    assert audit is not None
    assert audit.status == "failed"
    assert audit.plugin_refs == ["plugin:external@2.0.0:chunk", "plugin:demo@1.0.0:chunk"]
    assert audit.plugin_package_hashes == ["hash-external", "hash-regression"]
    assert [gate.name for gate in audit.gates] == ["kg_compare", "latest_regression_run"]
    assert audit.failure_categories == {"kg_noise": 1, "absence": 1}
    assert audit.recommended_next_action == "Fix content absence and KG noise before enabling production retrieval."


def test_dataset_retrieval_audit_summary_surfaces_kg_enablement_recommendation() -> None:
    from app.services.report_service import _build_retrieval_audit_summary

    audit = _build_retrieval_audit_summary(
        latest_regression_run=None,
        dataset_metadata={
            "retrieval_audit": {
                "status": "passed",
                "gates": [
                    {
                        "name": "kg_compare",
                        "status": "passed",
                        "metrics": {
                            "candidate_gate_passed": True,
                            "compared_metrics": 14,
                            "kg_noise_rate": 0.05,
                        },
                        "failed_conditions": [],
                        "source": "external_readiness:kg_compare",
                    }
                ],
            }
        },
    )

    assert audit is not None
    assert audit.kg_recommendation == "full_kg_assist"


def test_dataset_retrieval_audit_summary_keeps_kg_disabled_when_compare_regresses() -> None:
    from app.services.report_service import _build_retrieval_audit_summary

    audit = _build_retrieval_audit_summary(
        latest_regression_run=None,
        dataset_metadata={
            "retrieval_audit": {
                "status": "failed",
                "gates": [
                    {
                        "name": "kg_compare",
                        "status": "failed",
                        "metrics": {
                            "candidate_gate_passed": False,
                            "compared_metrics": 14,
                            "kg_noise_rate": 0.2,
                        },
                        "failed_conditions": ["metric_regressed:hit_at_1"],
                        "source": "external_readiness:kg_compare",
                    }
                ],
            }
        },
    )

    assert audit is not None
    assert audit.kg_recommendation == "none"


def test_dataset_report_metadata_replaces_raw_retrieval_audit_with_safe_snapshot() -> None:
    from app.services.report_service import _build_retrieval_audit_summary, _safe_dataset_report_metadata

    raw_metadata = {
        "owner": "platform",
        "retrieval_audit": {
            "status": "failed",
            "plugin_refs": ["plugin:demo@1.0.0:chunk"],
            "failure_categories": {"scope": 1},
            "gates": [
                {
                    "name": "mimirq_direct",
                    "status": "failed",
                    "metrics": {
                        "expected_metadata_hit_rate": 0.5,
                        "raw_context": "SHOULD_NOT_LEAK_RAW_CHUNK_TEXT",
                    },
                    "failed_conditions": ["expected_metadata_hit_rate"],
                }
            ],
            "raw_query": "SHOULD_NOT_LEAK_QUERY",
        },
    }
    audit = _build_retrieval_audit_summary(latest_regression_run=None, dataset_metadata=raw_metadata)

    safe_metadata = _safe_dataset_report_metadata(raw_metadata, retrieval_audit=audit)

    assert safe_metadata["owner"] == "platform"
    assert safe_metadata["retrieval_audit"]["plugin_refs"] == ["plugin:demo@1.0.0:chunk"]
    assert safe_metadata["retrieval_audit"]["gates"][0]["metrics"] == {"expected_metadata_hit_rate": 0.5}
    assert "raw_query" not in safe_metadata["retrieval_audit"]
    assert "raw_context" not in str(safe_metadata["retrieval_audit"])


def test_dataset_report_export_html(monkeypatch):  # noqa: ANN001
    dataset_id = uuid.uuid4()

    import app.api.v1.reports as reports_module
    from app.api.schemas.dataset_profile import DatasetProfileSummary
    from app.api.schemas.report import ComplianceSummary, DatasetReportOut

    dummy_profile = DatasetProfileSummary(
        dataset_id=dataset_id,
        generated_at="2026-01-01T00:00:00Z",
        total_documents=1,
        by_status={"completed": 1},
    )
    dummy_report = DatasetReportOut(
        dataset_id=dataset_id,
        dataset_name="Test Dataset",
        pipeline_hash=None,
        generated_at="2026-01-01T00:00:00Z",
        profile=dummy_profile,
        compliance=ComplianceSummary(quarantined_documents=0, failed_documents=0),
        pipeline_versions=[],
        connectors=[],
        dataset_metadata={},
    )
    monkeypatch.setattr(
        reports_module.ReportService,
        "build_dataset_report",
        lambda *_a, **_k: dummy_report,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(v1_router, prefix="/api/v1")
    client = TestClient(app)

    res = client.get(f"/api/v1/reports/datasets/{dataset_id}/export-html?redact=false")
    assert res.status_code == 200, res.text
    assert "text/html" in res.headers.get("content-type", "")
    assert "<!doctype html" in res.text.lower()
    assert "Test_Dataset.report.html" in (res.headers.get("content-disposition", "") or "")

    redacted = client.get(f"/api/v1/reports/datasets/{dataset_id}/export-html?redact=true")
    assert redacted.status_code == 200, redacted.text
    assert "Test_Dataset" not in (redacted.headers.get("content-disposition", "") or "")
    assert str(dataset_id) not in (redacted.headers.get("content-disposition", "") or "")


def test_dataset_rag_audit_export_html(monkeypatch):  # noqa: ANN001
    dataset_id = uuid.uuid4()

    import app.api.v1.reports as reports_module
    from app.api.schemas.dataset_profile import DatasetProfileSummary
    from app.api.schemas.report import ComplianceSummary, DatasetReportOut

    dummy_profile = DatasetProfileSummary(
        dataset_id=dataset_id,
        generated_at="2026-01-01T00:00:00Z",
        total_documents=1,
        by_status={"completed": 1},
    )
    dummy_report = DatasetReportOut(
        dataset_id=dataset_id,
        dataset_name="Test Dataset",
        pipeline_hash=None,
        generated_at="2026-01-01T00:00:00Z",
        profile=dummy_profile,
        compliance=ComplianceSummary(quarantined_documents=0, failed_documents=0),
        pipeline_versions=[],
        connectors=[],
        dataset_metadata={},
    )
    monkeypatch.setattr(
        reports_module.ReportService,
        "build_dataset_report",
        lambda *_a, **_k: dummy_report,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(v1_router, prefix="/api/v1")
    client = TestClient(app)

    res = client.get(f"/api/v1/reports/datasets/{dataset_id}/rag-audit/export-html?redact=false")
    assert res.status_code == 200, res.text
    assert "text/html" in res.headers.get("content-type", "")
    assert "<!doctype html" in res.text.lower()
    assert "Test_Dataset.rag_audit.html" in (res.headers.get("content-disposition", "") or "")

    redacted = client.get(f"/api/v1/reports/datasets/{dataset_id}/rag-audit/export-html?redact=true")
    assert redacted.status_code == 200, redacted.text
    assert "Test_Dataset" not in (redacted.headers.get("content-disposition", "") or "")
    assert str(dataset_id) not in (redacted.headers.get("content-disposition", "") or "")
