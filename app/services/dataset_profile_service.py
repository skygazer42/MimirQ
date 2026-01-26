"""
Dataset profile service.

Provides:
- Real-time dataset profiling summary (fast aggregation over document metadata)
- Whitelisted finding drill-down queries (actionable document lists)

Deep scan/backfill is implemented separately (see dataset_profile_scan.py).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.schemas.dataset_profile import (
    DatasetProfileDocumentOut,
    DatasetProfileFindingListResponse,
    DatasetProfileFindingSummary,
    DatasetProfilePdfScanStats,
    DatasetProfilePercentiles,
    DatasetProfileScanRunSummary,
    DatasetProfileSummary,
)
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentPermission
from app.models.dataset_profile_scan import DatasetProfileScanRun as DBDatasetProfileScanRun
from app.services.dataset_service import DatasetService
from app.services.dataset_profile_utils import FILE_SIZE_BINS, TEXT_LENGTH_BINS, histogram, percentile_from_sorted, safe_bool, safe_float, safe_int


FINDING_KEY_REASONS: dict[str, dict[str, Any]] = {
    "parse_failed": {
        "label": "解析失败",
        "severity": "error",
        "description": "需要人工检查文件/解析器配置，或调整解析后备策略。",
    },
    "pdf_scanned": {
        "label": "疑似扫描 PDF",
        "severity": "warning",
        "description": "通常需要 OCR / 更强的 PDF 解析后端。",
    },
    "pdf_unknown": {
        "label": "PDF 类型未知",
        "severity": "info",
        "description": "缺少 pdf_quality 指标，可运行“深度扫描”补齐。",
    },
    "low_density": {
        "label": "低密度/疑似乱码",
        "severity": "warning",
        "description": "解析结果信息密度偏低，可能影响检索质量。",
    },
    "pii": {
        "label": "PII 命中",
        "severity": "warning",
        "description": "命中手机号/邮箱/身份证等（来自治理阶段统计）。建议复核与脱敏策略。",
    },
    "secrets": {
        "label": "密钥/Token 命中",
        "severity": "warning",
        "description": "命中疑似密钥/Token（来自治理阶段统计）。建议脱敏或隔离。",
    },
    "image_heavy": {
        "label": "图片较多",
        "severity": "info",
        "description": "图片密集文档可能更适合走多模态处理或提取 OCR。",
    },
    "near_dedup": {
        "label": "近重复内容被丢弃",
        "severity": "info",
        "description": "near_dedup 在入库时丢弃了跨文档近重复 chunk（可用于质量排查）。",
    },
}


def _normalize_file_type(file_type: object, filename: object) -> str:
    explicit = str(file_type or "").strip().lower()
    if explicit:
        return explicit
    name = str(filename or "").strip()
    if "." in name:
        ext = name.rsplit(".", 1)[-1].strip().lower()
        if ext:
            return ext
    return "unknown"


def _extract_pii_hits(meta: dict) -> dict[str, int]:
    raw = meta.get("governance_pii_hits")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in raw.items():
        key = str(k or "").strip()
        if not key:
            continue
        n = safe_int(v, default=0)
        if n > 0:
            out[key] = int(n)
    return out


def _extract_secrets_hits(meta: dict) -> dict[str, int]:
    raw = meta.get("governance_secrets_hits")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in raw.items():
        key = str(k or "").strip()
        if not key:
            continue
        n = safe_int(v, default=0)
        if n > 0:
            out[key] = int(n)
    return out


def _extract_pdf_quality(meta: dict) -> dict:
    raw = meta.get("pdf_quality")
    return raw if isinstance(raw, dict) else {}


def _extract_text_quality(meta: dict) -> dict:
    raw = meta.get("parsed_text_quality")
    return raw if isinstance(raw, dict) else {}


def _is_low_density(meta: dict, *, density_threshold: float) -> bool:
    q = _extract_text_quality(meta)
    density = safe_float(q.get("density"), default=1.0)
    # Only flag if we have a real metric.
    if "density" not in q:
        return False
    return density < float(density_threshold)


def _is_image_heavy(meta: dict, *, image_threshold: int) -> bool:
    return safe_int(meta.get("image_count"), default=0) >= int(image_threshold)


def _has_near_dedup(meta: dict) -> bool:
    raw = meta.get("near_dedup")
    if not isinstance(raw, dict):
        return False
    return safe_int(raw.get("dropped"), default=0) > 0


def build_dataset_documents_query(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
) -> Tuple[Dataset, Any]:
    """
    Return (dataset, query) for documents within a dataset that the account can read.

    This mirrors the permission semantics in `app/api/v1/documents.py`:
    - Dataset read permission is enforced first
    - Then document-level ACL ("security trimming") is applied
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    query = db.query(DBDocument).filter(
        DBDocument.tenant_id == tenant_id,
        DBDocument.dataset_id == dataset_id,
    )

    # Document-level ACL filter ("security trimming").
    doc_perm_subq = select(DocumentPermission.document_id).where(
        DocumentPermission.tenant_id == tenant_id,
        DocumentPermission.account_id == account_id,
    )
    owner_dataset_ids_subq = select(Dataset.id).where(
        Dataset.tenant_id == tenant_id,
        Dataset.owner_id == account_id,
    )
    query = query.filter(
        or_(
            # Dataset owner sees all docs in their dataset (admin/management use-case).
            DBDocument.dataset_id.in_(owner_dataset_ids_subq),
            # Default/inherit/all-team: readable.
            DBDocument.access_mode.is_(None),
            DBDocument.access_mode.in_(["inherit", "all_team_members"]),
            # Doc owner override.
            DBDocument.owner_id == account_id,
            # Allowlist.
            and_(DBDocument.access_mode == "partial_members", DBDocument.id.in_(doc_perm_subq)),
        )
    )
    return dataset, query


def compute_dataset_profile_summary(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    density_threshold: float = 0.12,
    image_threshold: int = 8,
) -> DatasetProfileSummary:
    """
    Compute a best-effort dataset profile summary.

    Notes:
    - This is designed to be reasonably fast; it only uses persisted document stats/metadata.
    - Heavy re-parsing / hashing is done in deep scan jobs.
    """
    _dataset, query = build_dataset_documents_query(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)

    # Stream results to keep memory bounded for large corpora.
    rows = (
        query.with_entities(
            DBDocument.id,
            DBDocument.filename,
            DBDocument.file_type,
            DBDocument.file_size,
            DBDocument.status,
            DBDocument.chunk_count,
            DBDocument.total_characters,
            DBDocument.error_message,
            DBDocument.doc_metadata,
        )
        .execution_options(stream_results=True)
        .enable_eagerloads(False)
    )

    by_status: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    total_size = 0
    lengths: List[int] = []
    file_sizes: List[int] = []

    pdf_scanned = 0
    pdf_not_scanned = 0
    pdf_unknown = 0

    pii_totals: dict[str, int] = defaultdict(int)
    secrets_totals: dict[str, int] = defaultdict(int)

    # Findings counters.
    finding_counts: dict[str, int] = {k: 0 for k in FINDING_KEY_REASONS.keys()}

    for row in rows.yield_per(1000):
        _doc_id, filename, file_type, file_size, status, _chunk_count, total_chars, _err, meta = row
        ft = _normalize_file_type(file_type, filename)
        st = str(status or "").strip().lower() or "unknown"
        by_status[st] += 1
        by_type[ft] += 1

        size_val = safe_int(file_size, default=0)
        if size_val > 0:
            total_size += size_val
            file_sizes.append(size_val)

        length_val = safe_int(total_chars, default=0)
        if length_val > 0:
            lengths.append(length_val)

        meta_dict = meta if isinstance(meta, dict) else {}

        # PDF scan breakdown.
        if ft == "pdf":
            quality = _extract_pdf_quality(meta_dict)
            if not quality:
                pdf_unknown += 1
                finding_counts["pdf_unknown"] += 1
            else:
                if safe_bool(quality.get("is_scanned"), default=False):
                    pdf_scanned += 1
                    finding_counts["pdf_scanned"] += 1
                else:
                    pdf_not_scanned += 1

        # Failed docs.
        if st == "failed":
            finding_counts["parse_failed"] += 1

        # Low density flag.
        if _is_low_density(meta_dict, density_threshold=float(density_threshold)):
            finding_counts["low_density"] += 1

        # Image-heavy flag.
        if _is_image_heavy(meta_dict, image_threshold=int(image_threshold)):
            finding_counts["image_heavy"] += 1

        # PII / secrets hits.
        pii = _extract_pii_hits(meta_dict)
        if pii:
            finding_counts["pii"] += 1
            for k, v in pii.items():
                pii_totals[k] += int(v)

        secrets = _extract_secrets_hits(meta_dict)
        if secrets:
            finding_counts["secrets"] += 1
            for k, v in secrets.items():
                secrets_totals[k] += int(v)

        if _has_near_dedup(meta_dict):
            finding_counts["near_dedup"] += 1

    # Percentiles.
    lengths.sort()
    percentiles = DatasetProfilePercentiles(
        p25=percentile_from_sorted(lengths, 25),
        p50=percentile_from_sorted(lengths, 50),
        p75=percentile_from_sorted(lengths, 75),
        p90=percentile_from_sorted(lengths, 90),
        p99=percentile_from_sorted(lengths, 99),
    )

    # Histograms.
    length_hist = histogram(lengths, TEXT_LENGTH_BINS)
    size_hist = histogram(file_sizes, FILE_SIZE_BINS)

    # Findings list in stable order.
    findings_out: List[DatasetProfileFindingSummary] = []
    for key in FINDING_KEY_REASONS.keys():
        info = FINDING_KEY_REASONS[key]
        findings_out.append(
            DatasetProfileFindingSummary(
                key=key,
                label=str(info.get("label") or key),
                severity=str(info.get("severity") or "info"),  # type: ignore[arg-type]
                count=int(finding_counts.get(key, 0) or 0),
                description=info.get("description"),
            )
        )

    # Best-effort latest deep scan run.
    latest_run: DatasetProfileScanRunSummary | None = None
    try:
        row = (
            db.query(DBDatasetProfileScanRun)
            .filter(DBDatasetProfileScanRun.tenant_id == tenant_id, DBDatasetProfileScanRun.dataset_id == dataset_id)
            .order_by(DBDatasetProfileScanRun.created_at.desc())
            .first()
        )
        if row is not None:
            latest_run = DatasetProfileScanRunSummary(
                id=row.id,
                kind=str(getattr(row, "kind", "") or "deep"),
                status=str(getattr(row, "status", "") or "pending"),
                progress=int(getattr(row, "progress", 0) or 0),
                requested_by=getattr(row, "requested_by", None),
                created_at=getattr(row, "created_at", None),
                started_at=getattr(row, "started_at", None),
                finished_at=getattr(row, "finished_at", None),
                error_message=getattr(row, "error_message", None),
            )
    except Exception:
        latest_run = None

    now = datetime.now(timezone.utc)
    return DatasetProfileSummary(
        dataset_id=dataset_id,
        generated_at=now,
        total_documents=int(sum(by_status.values())),
        total_size_bytes=int(total_size),
        by_status={k: int(v) for k, v in by_status.items()},
        by_file_type={k: int(v) for k, v in by_type.items()},
        file_size_histogram=size_hist,
        length_percentiles=percentiles,
        length_histogram=length_hist,
        pdf_scan=DatasetProfilePdfScanStats(scanned=pdf_scanned, not_scanned=pdf_not_scanned, unknown=pdf_unknown),
        pii_hits_total={k: int(v) for k, v in pii_totals.items()},
        secrets_hits_total={k: int(v) for k, v in secrets_totals.items()},
        findings=findings_out,
        latest_scan_run=latest_run,
    )


def apply_finding_filter(
    query,
    *,
    finding_key: str,
    density_threshold: float = 0.12,
    image_threshold: int = 8,
):
    """
    Apply a whitelisted finding filter on a dataset-scoped document query.

    NOTE: For JSONB fields, we only use predicates that work on PostgreSQL.
    For sqlite/local dev, callers can fall back to Python-side filtering (not ideal).
    """
    key = str(finding_key or "").strip().lower()
    if key not in FINDING_KEY_REASONS:
        raise ValueError("Unknown finding_key")

    if key == "parse_failed":
        return query.filter(DBDocument.status == "failed")

    if key == "pdf_scanned":
        # metadata->pdf_quality->is_scanned == true
        return query.filter(
            DBDocument.file_type == "pdf",
            func.coalesce(DBDocument.doc_metadata["pdf_quality"]["is_scanned"].as_boolean(), False) == True,  # noqa: E712
        )

    if key == "pdf_unknown":
        # metadata->pdf_quality missing
        return query.filter(
            DBDocument.file_type == "pdf",
            DBDocument.doc_metadata["pdf_quality"].is_(None),
        )

    if key == "low_density":
        # parsed_text_quality.density < threshold
        return query.filter(
            func.coalesce(DBDocument.doc_metadata["parsed_text_quality"]["density"].as_float(), 1.0) < float(density_threshold),
        )

    if key == "pii":
        # governance_pii_hits exists and not empty
        return query.filter(DBDocument.doc_metadata["governance_pii_hits"].is_not(None))

    if key == "secrets":
        return query.filter(DBDocument.doc_metadata["governance_secrets_hits"].is_not(None))

    if key == "image_heavy":
        return query.filter(func.coalesce(DBDocument.doc_metadata["image_count"].as_integer(), 0) >= int(image_threshold))

    if key == "near_dedup":
        return query.filter(func.coalesce(DBDocument.doc_metadata["near_dedup"]["dropped"].as_integer(), 0) > 0)

    return query


def list_finding_documents(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    finding_key: str,
    skip: int = 0,
    limit: int = 50,
    density_threshold: float = 0.12,
    image_threshold: int = 8,
) -> DatasetProfileFindingListResponse:
    _dataset, base = build_dataset_documents_query(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
    q = apply_finding_filter(
        base,
        finding_key=finding_key,
        density_threshold=float(density_threshold),
        image_threshold=int(image_threshold),
    )
    total = int(q.with_entities(func.count(DBDocument.id)).scalar() or 0)
    items = (
        q.order_by(DBDocument.updated_at.desc(), DBDocument.id.asc())
        .offset(max(0, int(skip)))
        .limit(max(1, min(int(limit), 200)))
        .all()
    )
    out_items: list[DatasetProfileDocumentOut] = []
    for doc in items:
        out_items.append(
            DatasetProfileDocumentOut(
                id=doc.id,
                dataset_id=doc.dataset_id,
                filename=str(doc.filename or ""),
                file_type=str(doc.file_type or ""),
                file_size=int(doc.file_size or 0),
                status=str(doc.status or ""),
                chunk_count=int(doc.chunk_count or 0),
                total_characters=int(doc.total_characters or 0),
                created_at=getattr(doc, "created_at", None),
                updated_at=getattr(doc, "updated_at", None),
                error_message=getattr(doc, "error_message", None),
                metadata=dict(doc.doc_metadata or {}),
            )
        )
    return DatasetProfileFindingListResponse(total=total, items=out_items)

