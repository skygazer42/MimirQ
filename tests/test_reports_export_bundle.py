
import io
import uuid
import zipfile

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


def test_dataset_report_export_bundle_zip(monkeypatch):  # noqa: ANN001
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
    monkeypatch.setattr(
        reports_module,
        "render_dataset_report_html",
        lambda *_a, **_k: "<!doctype html><html><body>report</body></html>",
        raising=True,
    )
    monkeypatch.setattr(
        reports_module,
        "render_rag_audit_html",
        lambda *_a, **_k: "<!doctype html><html><body>rag-audit</body></html>",
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(v1_router, prefix="/api/v1")
    client = TestClient(app)

    res = client.get(f"/api/v1/reports/datasets/{dataset_id}/export-bundle")
    assert res.status_code == 200, res.text
    assert "application/zip" in (res.headers.get("content-type", "") or "")

    z = zipfile.ZipFile(io.BytesIO(res.content))
    names = set(z.namelist())
    assert "manifest.json" in names
    assert "report.json" in names
    assert "report.html" in names
    assert "rag_audit.html" in names

