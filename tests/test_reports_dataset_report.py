from __future__ import annotations

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
    from app.api.schemas.report import ComplianceSummary, DatasetReportOut

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
    assert "chunk_quality_metrics" in body
    assert "kg_stats" in body
    assert "latest_regression_run" in body
    assert body["folder_tree"]["total_documents"] == 3


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

    res = client.get(f"/api/v1/reports/datasets/{dataset_id}/export-html")
    assert res.status_code == 200, res.text
    assert "text/html" in res.headers.get("content-type", "")
    assert "<!doctype html" in res.text.lower()
