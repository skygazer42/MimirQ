from __future__ import annotations

import uuid


def test_dataset_report_schema_exposes_real_data_provenance() -> None:
    from app.api.schemas.dataset_profile import DatasetProfileSummary
    from app.api.schemas.report import ComplianceSummary, DatasetReportOut

    dataset_id = uuid.uuid4()
    report = DatasetReportOut(
        dataset_id=dataset_id,
        dataset_name="Live Dataset",
        generated_at="2026-01-01T00:00:00Z",
        profile=DatasetProfileSummary(
            dataset_id=dataset_id,
            generated_at="2026-01-01T00:00:00Z",
            total_documents=1,
            by_status={"completed": 1},
        ),
        compliance=ComplianceSummary(),
    )

    payload = report.model_dump(mode="json")
    provenance = payload.get("data_provenance")
    assert provenance is not None
    assert provenance["source"] == "database"
    assert provenance["mocked"] is False
    assert "documents" in provenance["sections"]
    assert "dataset_profile" in provenance["sections"]
