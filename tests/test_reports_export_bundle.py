
import io
import json
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


def _zip_text_entries(payload: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return {
            name: zf.read(name).decode("utf-8")
            for name in zf.namelist()
        }


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

    res = client.get(f"/api/v1/reports/datasets/{dataset_id}/export-bundle?redact=false")
    assert res.status_code == 200, res.text
    assert "application/zip" in (res.headers.get("content-type", "") or "")

    z = zipfile.ZipFile(io.BytesIO(res.content))
    names = set(z.namelist())
    assert "manifest.json" in names
    assert "report.json" in names
    assert "report.html" in names
    assert "rag_audit.html" in names
    manifest = json.loads(z.read("manifest.json").decode("utf-8"))
    assert manifest["dataset_id"] == str(dataset_id)
    assert manifest["dataset_name"] == "Test Dataset"


def test_dataset_report_export_bundle_redacts_filename_and_manifest(monkeypatch):  # noqa: ANN001
    dataset_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    scan_run_id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    regression_run_id = uuid.UUID("99999999-8888-7777-6666-555555555555")
    pipeline_hash = "abcdef0123456789" * 4

    import app.api.v1.reports as reports_module
    from app.api.schemas.dataset_profile import DatasetProfileScanRunSummary, DatasetProfileSummary
    from app.api.schemas.report import ComplianceSummary, DatasetRegressionRunSummaryOut, DatasetReportOut

    dummy_profile = DatasetProfileSummary(
        dataset_id=dataset_id,
        generated_at="2026-01-01T00:00:00Z",
        total_documents=1,
        by_status={"completed": 1},
        by_directory={"finance/contracts": 1},
        latest_scan_run=DatasetProfileScanRunSummary(
            id=scan_run_id,
            status="failed",
            requested_by="alice@corp.example",
            error_message="failed reading /srv/finance/Q3-plan.docx",
        ),
    )
    dummy_report = DatasetReportOut(
        dataset_id=dataset_id,
        dataset_name="Sensitive Dataset",
        pipeline_hash=pipeline_hash,
        generated_at="2026-01-01T00:00:00Z",
        profile=dummy_profile,
        compliance=ComplianceSummary(quarantined_documents=0, failed_documents=0),
        pipeline_versions=[],
        connectors=[],
        dataset_metadata={},
        latest_regression_run=DatasetRegressionRunSummaryOut(
            run_id=regression_run_id,
            status="failed",
            error_message="private chunk text leaked here",
        ),
    )
    monkeypatch.setattr(reports_module.ReportService, "build_dataset_report", lambda *_a, **_k: dummy_report, raising=True)
    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(v1_router, prefix="/api/v1")
    client = TestClient(app)

    res = client.get(
        f"/api/v1/reports/datasets/{dataset_id}/export-bundle",
        params={"redact": "true", "pipeline_hash": pipeline_hash},
    )
    assert res.status_code == 200, res.text
    content_disposition = res.headers.get("content-disposition", "")
    assert "Sensitive_Dataset" not in content_disposition
    assert str(dataset_id) not in content_disposition
    assert pipeline_hash[:8] not in content_disposition

    text_entries = _zip_text_entries(res.content)
    manifest = json.loads(text_entries["manifest.json"])
    serialized_manifest = json.dumps(manifest, ensure_ascii=False)
    assert manifest["redact"] is True
    assert manifest["dataset"] == {"redacted": True}
    assert "dataset_id" not in manifest
    assert "dataset_name" not in manifest
    assert "pipeline_hash" not in manifest
    assert str(dataset_id) not in serialized_manifest
    assert "Sensitive Dataset" not in serialized_manifest
    assert not any(name.startswith("regression_") for name in text_entries)
    sensitive_tokens = {
        "finance/contracts",
        "alice@corp.example",
        "/srv/finance/Q3-plan.docx",
        "private chunk text leaked here",
        str(scan_run_id),
        str(regression_run_id),
        pipeline_hash,
    }
    for text_content in text_entries.values():
        assert str(dataset_id) not in text_content
        assert "Sensitive Dataset" not in text_content
        assert "Sensitive_Dataset" not in text_content
        assert all(token not in text_content for token in sensitive_tokens)
