"""
Dataset profile service.

Provides:
- Real-time dataset profiling summary (fast aggregation over document metadata)
- Whitelisted finding drill-down queries (actionable document lists)

Deep scan/backfill is implemented separately (see dataset_profile_scan.py).
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, List, Tuple
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
from app.models.dataset_profile_scan import DatasetProfileScanRun as DBDatasetProfileScanRun
from app.models.document import Document as DBDocument
from app.models.document import DocumentPermission
from app.services.dataset_profile_utils import (
    AVG_CHUNK_CHARS_BINS,
    CHUNK_COUNT_BINS,
    FILE_SIZE_BINS,
    PAGE_COUNT_BINS,
    TEXT_LENGTH_BINS,
    histogram,
    percentile_from_sorted,
    safe_bool,
    safe_float,
    safe_int,
)
from app.services.dataset_service import DatasetService

# Best-effort in-process cache for profile summaries (read-heavy dashboards).
# Note: must include account_id due to document-level ACL (security trimming).
_PROFILE_CACHE_TTL_SEC = 3.0
_profile_cache: dict[tuple, tuple[float, DatasetProfileSummary]] = {}
_PARSE_QUALITY_LOW_THRESHOLD = 0.35


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
    "parse_low_quality": {
        "label": "解析质量偏低",
        "severity": "warning",
        "description": "解析质量评分较低（综合 pdf_quality / parsed_text_quality）。建议人工复核或调整解析后端/OCR 路由。",
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
    "exact_dup": {
        "label": "完全重复文件（需 hash）",
        "severity": "info",
        "description": "基于 file_sha256 的完全重复候选。可在“深度扫描”中开启 compute_file_hash 补齐。",
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


def aggregate_profile_from_rows(
    *,
    dataset_id: UUID,
    rows: Iterable[tuple],
    latest_scan_run: DatasetProfileScanRunSummary | None = None,
    density_threshold: float = 0.12,
    image_threshold: int = 8,
) -> DatasetProfileSummary:
    """
    Pure aggregation helper for dataset profile summary.

    `rows` must yield tuples matching the `with_entities(...)` shape used by
    `compute_dataset_profile_summary`.
    """
    by_status: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    total_size = 0
    lengths: List[int] = []
    file_sizes: List[int] = []
    chunk_counts: List[int] = []
    avg_chunk_chars: List[int] = []

    pdf_scanned = 0
    pdf_not_scanned = 0
    pdf_unknown = 0

    page_counts: List[int] = []
    language_counts: Counter[str] = Counter()
    parse_quality_bins: list[int] = [0 for _ in range(10)]

    pii_totals: dict[str, int] = defaultdict(int)
    secrets_totals: dict[str, int] = defaultdict(int)

    # Findings counters.
    finding_counts: dict[str, int] = {k: 0 for k in FINDING_KEY_REASONS.keys()}
    sha_counts: Counter[str] = Counter()

    def _normalize_language_bucket(value: object) -> str:
        s = str(value or "").strip()
        if not s:
            return "unknown"
        lowered = s.lower()
        if lowered in {"mixed", "multilingual", "multi"}:
            return "mixed"
        if any(sep in lowered for sep in (",", ";", "|", "+", "/")):
            return "mixed"
        if lowered.startswith("zh"):
            return "zh"
        if lowered.startswith("en"):
            return "en"
        return "unknown"

    def _extract_language(meta: dict[str, Any]) -> str:
        # Prefer top-level metadata; fallback to governance enrichment.
        if isinstance(meta.get("language"), str):
            return _normalize_language_bucket(meta.get("language"))
        enr = meta.get("governance_enrichment")
        if isinstance(enr, dict) and isinstance(enr.get("language"), str):
            return _normalize_language_bucket(enr.get("language"))
        return "unknown"

    for row in rows:
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

        # Chunking proxies (cheap): chunk_count distribution and avg chars per chunk.
        chunk_count_val = safe_int(_chunk_count, default=0)
        if chunk_count_val > 0:
            chunk_counts.append(int(chunk_count_val))
            if length_val > 0:
                avg_chunk_chars.append(int(max(1, length_val // max(1, int(chunk_count_val)))))

        meta_dict = meta if isinstance(meta, dict) else {}

        # Language mix (best-effort).
        language_counts[_extract_language(meta_dict)] += 1

        # Page count histogram (best-effort; keep it cheap: only use persisted metadata).
        page_count = safe_int(meta_dict.get("page_count"), default=0)
        if page_count <= 0:
            pdf_quality = meta_dict.get("pdf_quality")
            if isinstance(pdf_quality, dict):
                page_count = safe_int(pdf_quality.get("page_count"), default=0)
        if page_count > 0:
            page_counts.append(int(page_count))

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

        pq = meta_dict.get("parse_quality")
        if isinstance(pq, dict) and pq.get("score") is not None:
            score = safe_float(pq.get("score"), default=1.0)
            # Bucket into 10 bins: [0.0-0.1), ... [0.9-1.0]
            clamped = min(1.0, max(0.0, float(score)))
            idx = int(clamped * 10.0)
            idx = 9 if idx >= 10 else idx
            parse_quality_bins[idx] += 1
            if score < float(_PARSE_QUALITY_LOW_THRESHOLD):
                finding_counts["parse_low_quality"] += 1

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

        sha = str(meta_dict.get("file_sha256") or "").strip().lower()
        if sha:
            sha_counts[sha] += 1

    # Exact duplicates (requires file_sha256 to be present).
    if sha_counts:
        dup_total = 0
        for _sha, cnt in sha_counts.items():
            if int(cnt) > 1:
                dup_total += int(cnt)
        finding_counts["exact_dup"] = int(dup_total)

    # Percentiles.
    lengths.sort()
    percentiles = DatasetProfilePercentiles(
        p25=percentile_from_sorted(lengths, 25),
        p50=percentile_from_sorted(lengths, 50),
        p75=percentile_from_sorted(lengths, 75),
        p90=percentile_from_sorted(lengths, 90),
        p99=percentile_from_sorted(lengths, 99),
    )

    chunk_counts.sort()
    chunk_count_percentiles = DatasetProfilePercentiles(
        p25=percentile_from_sorted(chunk_counts, 25),
        p50=percentile_from_sorted(chunk_counts, 50),
        p75=percentile_from_sorted(chunk_counts, 75),
        p90=percentile_from_sorted(chunk_counts, 90),
        p99=percentile_from_sorted(chunk_counts, 99),
    )

    avg_chunk_chars.sort()
    avg_chunk_chars_percentiles = DatasetProfilePercentiles(
        p25=percentile_from_sorted(avg_chunk_chars, 25),
        p50=percentile_from_sorted(avg_chunk_chars, 50),
        p75=percentile_from_sorted(avg_chunk_chars, 75),
        p90=percentile_from_sorted(avg_chunk_chars, 90),
        p99=percentile_from_sorted(avg_chunk_chars, 99),
    )

    # Histograms.
    length_hist = histogram(lengths, TEXT_LENGTH_BINS)
    size_hist = histogram(file_sizes, FILE_SIZE_BINS)
    page_hist = histogram(page_counts, PAGE_COUNT_BINS) if page_counts else []
    chunk_count_hist = histogram(chunk_counts, CHUNK_COUNT_BINS) if chunk_counts else []
    avg_chunk_chars_hist = histogram(avg_chunk_chars, AVG_CHUNK_CHARS_BINS) if avg_chunk_chars else []

    # Parse quality histogram (0.0-1.0, 10 bins).
    pq_hist: list[dict[str, Any]] = []
    for i, cnt in enumerate(parse_quality_bins):
        lo = i / 10.0
        hi = (i + 1) / 10.0
        pq_hist.append({"label": f"{lo:.1f}-{hi:.1f}", "count": int(cnt)})

    # Stable keys for UI.
    language_mix = {
        "zh": int(language_counts.get("zh", 0) or 0),
        "en": int(language_counts.get("en", 0) or 0),
        "mixed": int(language_counts.get("mixed", 0) or 0),
        "unknown": int(language_counts.get("unknown", 0) or 0),
    }

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
        chunk_count_percentiles=chunk_count_percentiles,
        chunk_count_histogram=chunk_count_hist,
        avg_chunk_chars_percentiles=avg_chunk_chars_percentiles,
        avg_chunk_chars_histogram=avg_chunk_chars_hist,
        page_number_histogram=page_hist,
        parse_quality_histogram=pq_hist,
        language_mix=language_mix,
        pdf_scan=DatasetProfilePdfScanStats(scanned=pdf_scanned, not_scanned=pdf_not_scanned, unknown=pdf_unknown),
        pii_hits_total={k: int(v) for k, v in pii_totals.items()},
        secrets_hits_total={k: int(v) for k, v in secrets_totals.items()},
        findings=findings_out,
        latest_scan_run=latest_scan_run,
    )


def compute_dataset_profile_summary(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    pipeline_hash: str | None = None,
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

    # Optional pipeline version filter: use active_pipeline_hash when present (fallback to pipeline_hash).
    pipeline_hash_norm = str(pipeline_hash or "").strip() or None
    if pipeline_hash_norm:
        active_expr = func.coalesce(
            DBDocument.doc_metadata["active_pipeline_hash"].as_string(),
            DBDocument.doc_metadata["pipeline_hash"].as_string(),
        )
        query = query.filter(active_expr == pipeline_hash_norm)

    # Best-effort short TTL cache: key includes ACL-scoped max(updated_at) so it invalidates on changes.
    cache_key = None
    try:
        latest_doc_ts = (
            query.with_entities(func.max(DBDocument.updated_at))
            .execution_options(stream_results=True)
            .enable_eagerloads(False)
            .scalar()
        )
        latest_doc_key = latest_doc_ts.isoformat() if hasattr(latest_doc_ts, "isoformat") else str(latest_doc_ts or "")
        cache_key = (
            str(tenant_id),
            str(account_id),
            str(dataset_id),
            str(pipeline_hash_norm or ""),
            float(density_threshold),
            int(image_threshold),
            latest_doc_key,
        )
        cached = _profile_cache.get(cache_key)
        if cached is not None:
            ts, payload = cached
            if (time.monotonic() - float(ts)) < _PROFILE_CACHE_TTL_SEC:
                return payload
    except Exception:
        cache_key = None

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
        .yield_per(1000)
    )

    summary = aggregate_profile_from_rows(
        dataset_id=dataset_id,
        rows=rows,
        latest_scan_run=latest_run,
        density_threshold=float(density_threshold),
        image_threshold=int(image_threshold),
    )

    if cache_key is not None:
        # Keep cache size bounded (best-effort).
        if len(_profile_cache) > 256:
            _profile_cache.clear()
        _profile_cache[cache_key] = (time.monotonic(), summary)

    return summary


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

    if key == "parse_low_quality":
        return query.filter(
            func.coalesce(DBDocument.doc_metadata["parse_quality"]["score"].as_float(), 1.0) < float(_PARSE_QUALITY_LOW_THRESHOLD),
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

    if key == "exact_dup":
        # Subquery: file_sha256 with count>1 within the dataset scope.
        sha_expr = DBDocument.doc_metadata["file_sha256"].as_string()
        dup_subq = (
            query.with_entities(sha_expr.label("sha"), func.count(DBDocument.id).label("cnt"))
            .filter(sha_expr.is_not(None))
            .group_by(sha_expr)
            .having(func.count(DBDocument.id) > 1)
            .subquery()
        )
        return query.filter(sha_expr.in_(select(dup_subq.c.sha)))

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
