"""Report aggregation service.

Goal:
- Provide an exportable, shareable bundle for dataset quality + compliance.
- Keep it lightweight by reusing existing summaries and limiting expensive queries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.schemas.report import ComplianceSummary, ConnectorRunSummary, DatasetReportOut, PipelineVersionSummary
from app.models.connector import ConnectorRun as DBConnectorRun
from app.models.document import Document as DBDocument
from app.services.dataset_profile_service import build_dataset_documents_query, compute_dataset_profile_summary
from app.services.dataset_service import DatasetService


class ReportService:
    @staticmethod
    def build_dataset_report(
        db: Session,
        *,
        tenant_id: UUID,
        account_id: str,
        dataset_id: UUID,
        pipeline_hash: Optional[str] = None,
        connector_runs_limit: int = 20,
    ) -> DatasetReportOut:
        dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)

        pipeline_hash_norm = str(pipeline_hash or "").strip() or None

        profile = compute_dataset_profile_summary(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            pipeline_hash=pipeline_hash_norm,
        )

        by_status = {str(k): int(v or 0) for k, v in (getattr(profile, "by_status", None) or {}).items()}

        compliance = ComplianceSummary(
            pii_hits_total={str(k): int(v or 0) for k, v in (getattr(profile, "pii_hits_total", None) or {}).items()},
            secrets_hits_total={str(k): int(v or 0) for k, v in (getattr(profile, "secrets_hits_total", None) or {}).items()},
            quarantined_documents=int(by_status.get("quarantined", 0) or 0),
            failed_documents=int(by_status.get("failed", 0) or 0),
        )

        # Pipeline versions distribution (best-effort).
        pipeline_versions: list[PipelineVersionSummary] = []
        try:
            _dataset, q = build_dataset_documents_query(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
            active_expr = func.coalesce(
                DBDocument.doc_metadata["active_pipeline_hash"].as_string(),
                DBDocument.doc_metadata["pipeline_hash"].as_string(),
                "unknown",
            )
            rows = (
                q.with_entities(active_expr.label("ph"), func.count(DBDocument.id).label("cnt"))
                .group_by(active_expr)
                .order_by(func.count(DBDocument.id).desc())
                .limit(50)
                .all()
            )
            for r in rows:
                ph = str(getattr(r, "ph", None) or "unknown")
                cnt = int(getattr(r, "cnt", 0) or 0)
                pipeline_versions.append(PipelineVersionSummary(pipeline_hash=ph[:64], documents=max(0, cnt)))
        except Exception:
            pipeline_versions = []

        # Recent connector runs (best-effort).
        connectors: list[ConnectorRunSummary] = []
        try:
            lim = max(0, min(int(connector_runs_limit or 0), 100))
        except Exception:
            lim = 20
        try:
            if lim > 0:
                rows = (
                    db.query(DBConnectorRun)
                    .filter(DBConnectorRun.tenant_id == tenant_id, DBConnectorRun.dataset_id == dataset_id)
                    .order_by(DBConnectorRun.created_at.desc())
                    .limit(lim)
                    .all()
                )
                for row in rows:
                    connectors.append(
                        ConnectorRunSummary(
                            id=row.id,
                            connector_id=str(getattr(row, "connector_id", "") or ""),
                            status=str(getattr(row, "status", "") or ""),
                            created_at=getattr(row, "created_at", datetime.now(timezone.utc)),
                            finished_at=getattr(row, "finished_at", None),
                            error_message=getattr(row, "error_message", None),
                            stats=dict(getattr(row, "stats", None) or {}),
                        )
                    )
        except Exception:
            connectors = []

        return DatasetReportOut(
            dataset_id=dataset_id,
            dataset_name=str(getattr(dataset, "name", "") or "") or None,
            pipeline_hash=pipeline_hash_norm,
            generated_at=datetime.now(timezone.utc),
            profile=profile,
            compliance=compliance,
            pipeline_versions=pipeline_versions,
            connectors=connectors,
            dataset_metadata=dict(getattr(dataset, "dataset_metadata", None) or {}),
        )

