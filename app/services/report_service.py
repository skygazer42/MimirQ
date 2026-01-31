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

from app.api.schemas.document_folders import DocumentFolderTreeResponse
from app.api.schemas.report import (
    ComplianceSummary,
    ConnectorRunSummary,
    DatasetGovernanceMetricsOut,
    DatasetReportOut,
    PipelineVersionSummary,
)
from app.models.connector import ConnectorRun as DBConnectorRun
from app.models.document import Document as DBDocument
from app.services.dataset_profile_service import build_dataset_documents_query, compute_dataset_profile_summary
from app.services.dataset_service import DatasetService
from app.services.document_folders import build_document_folder_tree


def _aggregate_governance_metrics(
    *,
    total_documents: int,
    metadatas: list[dict],
    truncated: bool,
) -> DatasetGovernanceMetricsOut:
    docs_with_governance = 0
    rules_applied_total = 0
    changed_documents_total = 0
    dropped_documents_total = 0
    drop_reasons_total: dict[str, int] = {}
    rule_packs_docs: dict[str, int] = {}

    for meta in metadatas:
        if not isinstance(meta, dict):
            continue

        # Treat presence of governance_enabled or governance_version as "has governance".
        has_gov = bool(meta.get("governance_enabled")) or bool(meta.get("governance_version"))
        if has_gov:
            docs_with_governance += 1

        try:
            rules_applied_total += int(meta.get("governance_rules_applied") or 0)
        except Exception:
            pass
        try:
            changed_documents_total += int(meta.get("governance_changed_documents") or 0)
        except Exception:
            pass
        try:
            dropped_documents_total += int(meta.get("governance_dropped_documents") or 0)
        except Exception:
            pass

        reasons = meta.get("governance_drop_reasons")
        if isinstance(reasons, dict):
            for k, v in reasons.items():
                if k is None:
                    continue
                key = str(k)
                try:
                    drop_reasons_total[key] = drop_reasons_total.get(key, 0) + int(v or 0)
                except Exception:
                    continue

        packs = meta.get("governance_rule_packs")
        if isinstance(packs, list):
            seen: set[str] = set()
            for raw in packs:
                if not isinstance(raw, str):
                    continue
                key = raw.strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                rule_packs_docs[key] = rule_packs_docs.get(key, 0) + 1

    return DatasetGovernanceMetricsOut(
        total_documents=int(total_documents or 0),
        used_documents=len([m for m in metadatas if isinstance(m, dict)]),
        truncated=bool(truncated),
        docs_with_governance=int(docs_with_governance),
        rules_applied_total=int(max(0, rules_applied_total)),
        changed_documents_total=int(max(0, changed_documents_total)),
        dropped_documents_total=int(max(0, dropped_documents_total)),
        drop_reasons_total={k: int(max(0, v)) for k, v in drop_reasons_total.items() if int(v or 0) > 0},
        rule_packs_docs={k: int(max(0, v)) for k, v in rule_packs_docs.items() if int(v or 0) > 0},
    )


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

        # Folder tree derived from document.metadata.source_path (best-effort).
        folder_tree: DocumentFolderTreeResponse | None = None
        try:
            _dataset, q = build_dataset_documents_query(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
            if pipeline_hash_norm:
                active_expr = func.coalesce(
                    DBDocument.doc_metadata["active_pipeline_hash"].as_string(),
                    DBDocument.doc_metadata["pipeline_hash"].as_string(),
                )
                q = q.filter(active_expr == pipeline_hash_norm)

            rows = q.with_entities(DBDocument.doc_metadata["source_path"].astext).all()  # type: ignore[attr-defined]
            source_paths = [r[0] for r in rows if isinstance(r, tuple) and isinstance(r[0], str) and r[0].strip()]
            total_docs = int(getattr(profile, "total_documents", 0) or 0)
            root = build_document_folder_tree(source_paths, total_documents=total_docs, max_depth=20)
            folder_tree = DocumentFolderTreeResponse(
                dataset_id=dataset_id,
                total_documents=total_docs,
                total_with_source_path=int(len(source_paths)),
                root=root,
            )
        except Exception:
            folder_tree = None

        # Governance metrics aggregated from document metadata (best-effort).
        governance_metrics: DatasetGovernanceMetricsOut | None = None
        try:
            max_docs = 2000
            _dataset, q = build_dataset_documents_query(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
            if pipeline_hash_norm:
                active_expr = func.coalesce(
                    DBDocument.doc_metadata["active_pipeline_hash"].as_string(),
                    DBDocument.doc_metadata["pipeline_hash"].as_string(),
                )
                q = q.filter(active_expr == pipeline_hash_norm)

            # Sample the most recently updated docs for responsiveness; report includes a truncation flag.
            rows = q.with_entities(DBDocument.doc_metadata).order_by(DBDocument.updated_at.desc()).limit(max_docs + 1).all()
            metas = [r[0] for r in rows if isinstance(r, tuple) and isinstance(r[0], dict)]
            truncated = len(metas) > max_docs
            if truncated:
                metas = metas[:max_docs]
            governance_metrics = _aggregate_governance_metrics(
                total_documents=int(getattr(profile, "total_documents", 0) or 0),
                metadatas=metas,
                truncated=truncated,
            )
        except Exception:
            governance_metrics = None

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
            folder_tree=folder_tree,
            governance_metrics=governance_metrics,
        )
