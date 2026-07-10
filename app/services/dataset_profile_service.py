"""
Dataset profile service.

Provides:
- Real-time dataset profiling summary (fast aggregation over document metadata)
- Whitelisted finding drill-down queries (actionable document lists)

Deep scan/backfill is implemented separately (see dataset_profile_scan.py).
"""


import re
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.schemas.dataset_profile import (
    DatasetProfileDocumentListResponse,
    DatasetProfileDocumentOut,
    DatasetProfileFindingListResponse,
    DatasetProfileFindingSummary,
    DatasetProfileParsingProvenanceStats,
    DatasetProfilePdfScanStats,
    DatasetProfilePercentiles,
    DatasetProfileScanRunSummary,
    DatasetProfileSummary,
    DatasetProfileTargetCheck,
)
from app.models.dataset import Dataset
from app.models.dataset_profile_scan import DatasetProfileScanRun as DBDatasetProfileScanRun
from app.models.document import Document as DBDocument
from app.models.document import DocumentParsedContent, DocumentPermission
from app.models.group_permissions import DocumentGroupPermission
from app.models.tenant_group import TenantGroupMember
from app.rag.core.logging import get_logger
from app.rag.preprocessing.pii_anonymizer import anonymize_pii
from app.rag.preprocessing.secrets import redact_secrets
from app.services.dataset_profile_utils import (
    AVG_CHUNK_CHARS_BINS,
    AVG_CHUNK_TOKENS_BINS,
    CHUNK_COUNT_BINS,
    CHUNK_LENGTH_BINS,
    CHUNK_TOKEN_BINS,
    COVERAGE_PCT_BINS,
    FILE_SIZE_BINS,
    OVERLAP_WASTE_PCT_BINS,
    PAGE_COUNT_BINS,
    TEXT_LENGTH_BINS,
    build_recall_risk_hints,
    histogram,
    percentile_from_sorted,
    safe_bool,
    safe_float,
    safe_int,
)
from app.services.dataset_service import DatasetService

logger = get_logger(__name__)

# Best-effort in-process cache for profile summaries (read-heavy dashboards).
# Note: must include account_id due to document-level ACL (security trimming).
_PROFILE_CACHE_TTL_SEC = 3.0
_profile_cache: dict[tuple, tuple[float, DatasetProfileSummary]] = {}
_PARSE_QUALITY_LOW_THRESHOLD = 0.35
_SEAL_CONFIDENCE_LOW_THRESHOLD = 0.6


FINDING_KEY_REASONS: dict[str, dict[str, Any]] = {
    "parse_failed": {
        "label": "解析失败",
        "severity": "error",
        "description": "需要人工检查文件/解析器配置，或调整解析后备策略。",
    },
    "preprocess_failed": {
        "label": "预处理失败",
        "severity": "error",
        "description": "文件级预处理（编码/规范化/HTML 清洗）失败。建议检查文件权限/编码/预处理 steps 配置。",
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
    "seal_low_confidence": {
        "label": "印章识别置信度偏低",
        "severity": "warning",
        "description": "检测到签章类文档但主印章置信度较低，建议人工复核或切换更强 OCR / layout parser。",
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
    "chunk_coverage_low": {
        "label": "Chunk 覆盖率偏低",
        "severity": "warning",
        "description": "chunk offsets 覆盖率偏低（coverage < 98%），可能存在解析/offsets/拼接链路问题，影响溯源与高亮。",
    },
    "chunk_quality_fail": {
        "label": "Chunk 质量门槛失败",
        "severity": "warning",
        "description": "chunk 质量 gate 判定为 fail（例如过多短块/重复/覆盖不足），建议先在 chunk-preview 调参验证。",
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


def normalize_language_bucket(value: object) -> str:
    """
    Normalize language to stable buckets used by eval slicing + dataset profiling.

    Notes:
    - This intentionally stays coarse: zh/en/mixed/unknown.
    - Keep in sync with retrieval/eval slice taxonomy.
    """

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


def directory_bucket_from_source_path(value: object) -> str:
    """
    Map metadata.source_path -> a stable top-level directory bucket.

    We intentionally only keep the first path segment to prevent exploding buckets
    and to align with eval slice taxonomy.
    """

    raw = str(value or "").replace("\\", "/").strip()
    if not raw or raw in {".", "/"}:
        return "root"
    raw = raw.lstrip("/")
    head = raw.split("/", 1)[0].strip()
    return head or "root"


def quality_bucket_from_governance_quality(value: object) -> str:
    """
    Coarse "quality bucket" derived from metadata.governance_quality.

    This is used for drilldowns and to align dataset profile distributions with
    eval slicing buckets.
    """

    q = value if isinstance(value, dict) else {}
    if not q:
        return "unknown"
    try:
        density = float(q.get("density")) if q.get("density") is not None else None
    except Exception:
        density = None
    try:
        heading_ratio = float(q.get("heading_ratio")) if q.get("heading_ratio") is not None else None
    except Exception:
        heading_ratio = None
    try:
        content_chars = int(q.get("content_chars")) if q.get("content_chars") is not None else None
    except Exception:
        content_chars = None

    if content_chars is not None and content_chars < 200:
        return "tiny"
    if heading_ratio is not None and heading_ratio >= 0.75:
        return "outline_heavy"
    if density is None:
        return "unknown"
    if density < 0.08:
        return "low_density"
    if density < 0.15:
        return "mid_density"
    return "high_density"


def extract_language_bucket(meta: dict[str, Any]) -> str:
    """Extract a stable language bucket from document metadata."""

    if isinstance(meta.get("language"), str):
        return normalize_language_bucket(meta.get("language"))
    enr = meta.get("governance_enrichment")
    if isinstance(enr, dict) and isinstance(enr.get("language"), str):
        return normalize_language_bucket(enr.get("language"))
    return "unknown"


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
) -> tuple[Dataset, Any]:
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
    doc_group_perm_subq = (
        select(DocumentGroupPermission.document_id)
        .join(
            TenantGroupMember,
            and_(
                TenantGroupMember.tenant_id == DocumentGroupPermission.tenant_id,
                TenantGroupMember.group_id == DocumentGroupPermission.group_id,
            ),
        )
        .where(
            DocumentGroupPermission.tenant_id == tenant_id,
            TenantGroupMember.user_id == account_id,
        )
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
            and_(
                DBDocument.access_mode == "partial_members",
                or_(
                    DBDocument.id.in_(doc_perm_subq),
                    DBDocument.id.in_(doc_group_perm_subq),
                ),
            ),
        )
    )
    return dataset, query


def aggregate_profile_from_rows(
    *,
    dataset_id: UUID,
    rows: Iterable[tuple],
    dataset_metadata: dict[str, Any] | None = None,
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
    lengths: list[int] = []
    file_sizes: list[int] = []
    chunk_counts: list[int] = []
    avg_chunk_chars: list[int] = []
    avg_chunk_tokens: list[int] = []
    chunk_length_bins: list[int] = [0 for _ in range(len(CHUNK_LENGTH_BINS))]
    chunk_length_total: int = 0
    chunk_token_bins: list[int] = [0 for _ in range(len(CHUNK_TOKEN_BINS))]
    chunk_token_total: int = 0

    coverage_pcts: list[int] = []
    overlap_waste_pcts: list[int] = []

    pdf_scanned = 0
    pdf_not_scanned = 0
    pdf_unknown = 0

    page_counts: list[int] = []
    language_counts: Counter[str] = Counter()
    directory_counts: Counter[str] = Counter()
    quality_bucket_counts: Counter[str] = Counter()
    parse_quality_bins: list[int] = [0 for _ in range(10)]

    # Parsing provenance/routing (best-effort; derived from metadata.parse_provenance).
    provenance_docs = 0
    provenance_by_backend: Counter[str] = Counter()
    provenance_fallback_docs = 0
    provenance_elapsed_ms: list[int] = []

    pii_totals: dict[str, int] = defaultdict(int)
    secrets_totals: dict[str, int] = defaultdict(int)

    # Findings counters.
    finding_counts: dict[str, int] = dict.fromkeys(FINDING_KEY_REASONS.keys(), 0)
    sha_counts: Counter[str] = Counter()
    duplicate_like_docs = 0

    chunk_length_label_to_idx: dict[str, int] = {spec.label: i for i, spec in enumerate(CHUNK_LENGTH_BINS)}
    chunk_token_label_to_idx: dict[str, int] = {spec.label: i for i, spec in enumerate(CHUNK_TOKEN_BINS)}

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

        # Stable slice distributions (align with eval).
        directory_counts[directory_bucket_from_source_path(meta_dict.get("source_path"))] += 1
        quality_bucket_counts[quality_bucket_from_governance_quality(meta_dict.get("governance_quality"))] += 1

        # Parse provenance/routing stats (best-effort).
        prov = meta_dict.get("parse_provenance")
        if isinstance(prov, dict) and prov:
            provenance_docs += 1
            backend = str(prov.get("resolved_backend") or "").strip() or "unknown"
            provenance_by_backend[backend] += 1

            elapsed = safe_int(prov.get("elapsed_ms"), default=0)
            if elapsed > 0:
                provenance_elapsed_ms.append(int(elapsed))

            # Fallback detection: multiple attempts with initial failure.
            attempts = prov.get("attempts")
            if isinstance(attempts, list) and len(attempts) >= 2:
                first = attempts[0] if attempts else None
                if isinstance(first, dict) and first.get("ok") is False:
                    provenance_fallback_docs += 1

        # Per-chunk length distribution (requires ingest-time chunking_stats or deep scan backfill).
        chunking_stats = meta_dict.get("chunking_stats")
        if isinstance(chunking_stats, dict):
            hist = chunking_stats.get("histogram")
            if isinstance(hist, list) and hist:
                for b in hist:
                    if not isinstance(b, dict):
                        continue
                    label = str(b.get("label") or "").strip()
                    if not label:
                        continue
                    idx = chunk_length_label_to_idx.get(label)
                    if idx is None:
                        continue
                    cnt = safe_int(b.get("count"), default=0)
                    if cnt > 0:
                        chunk_length_bins[idx] += int(cnt)
                        chunk_length_total += int(cnt)

        # Token-based chunk stats (best-effort; requires ingest-time token stats).
        chunking_stats_tokens = meta_dict.get("chunking_stats_tokens")
        if isinstance(chunking_stats_tokens, dict):
            try:
                avg_tok = safe_int(chunking_stats_tokens.get("avg"), default=0)
                if avg_tok <= 0:
                    tot = safe_int(chunking_stats_tokens.get("total"), default=0)
                    cnt = safe_int(chunking_stats_tokens.get("count"), default=0)
                    if tot > 0 and cnt > 0:
                        avg_tok = int(max(1, tot // max(1, cnt)))
                if avg_tok > 0:
                    avg_chunk_tokens.append(int(avg_tok))
            except Exception as exc:
                logger.debug("Ignoring malformed chunking token stats: %s", exc)

            hist = chunking_stats_tokens.get("histogram")
            if isinstance(hist, list) and hist:
                for b in hist:
                    if not isinstance(b, dict):
                        continue
                    label = str(b.get("label") or "").strip()
                    if not label:
                        continue
                    idx = chunk_token_label_to_idx.get(label)
                    if idx is None:
                        continue
                    cnt = safe_int(b.get("count"), default=0)
                    if cnt > 0:
                        chunk_token_bins[idx] += int(cnt)
                        chunk_token_total += int(cnt)

        # Coverage / overlap waste (best-effort; derived from ingest-time chunk offsets).
        cov = meta_dict.get("chunk_coverage")
        if isinstance(cov, dict):
            ratio = safe_float(cov.get("coverage_ratio"), default=-1.0)
            if ratio >= 0.0:
                clamped = min(1.0, max(0.0, float(ratio)))
                pct = int(round(clamped * 100.0))
                coverage_pcts.append(pct)
                if clamped < 0.98:
                    finding_counts["chunk_coverage_low"] += 1

            waste = safe_float(cov.get("overlap_waste_ratio"), default=-1.0)
            if waste >= 0.0:
                clamped = min(1.0, max(0.0, float(waste)))
                pct = int(round(clamped * 100.0))
                overlap_waste_pcts.append(pct)

        # Chunk quality gate (best-effort).
        gate = meta_dict.get("chunk_quality_gate")
        if isinstance(gate, dict):
            grade = str(gate.get("grade") or "").strip().lower()
            if grade == "fail":
                finding_counts["chunk_quality_fail"] += 1
            reason_items = gate.get("reason_items")
            if isinstance(reason_items, list):
                has_duplicate_reason = False
                for it in reason_items:
                    if not isinstance(it, dict):
                        continue
                    code = str(it.get("code") or "").strip().lower()
                    if code in {"many_duplicates", "too_many_duplicates"}:
                        has_duplicate_reason = True
                        break
                if has_duplicate_reason:
                    duplicate_like_docs += 1

        # Language mix (best-effort).
        language_counts[extract_language_bucket(meta_dict)] += 1

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
            # Preprocess failures are a common early-stage failure mode; surface separately.
            err = str(_err or "")
            if err.strip().lower().startswith("preprocess_failed"):
                finding_counts["preprocess_failed"] += 1

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

        seal_summary = meta_dict.get("seal_summary")
        if isinstance(seal_summary, dict):
            seal_score = safe_float(seal_summary.get("primary_score"), default=1.0)
            if safe_bool(seal_summary.get("detected"), default=False) and seal_score < float(_SEAL_CONFIDENCE_LOW_THRESHOLD):
                finding_counts["seal_low_confidence"] += 1

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

    avg_chunk_tokens.sort()
    avg_chunk_tokens_percentiles = DatasetProfilePercentiles(
        p25=percentile_from_sorted(avg_chunk_tokens, 25),
        p50=percentile_from_sorted(avg_chunk_tokens, 50),
        p75=percentile_from_sorted(avg_chunk_tokens, 75),
        p90=percentile_from_sorted(avg_chunk_tokens, 90),
        p99=percentile_from_sorted(avg_chunk_tokens, 99),
    )

    provenance_elapsed_ms.sort()
    provenance_elapsed_percentiles = DatasetProfilePercentiles(
        p25=percentile_from_sorted(provenance_elapsed_ms, 25),
        p50=percentile_from_sorted(provenance_elapsed_ms, 50),
        p75=percentile_from_sorted(provenance_elapsed_ms, 75),
        p90=percentile_from_sorted(provenance_elapsed_ms, 90),
        p99=percentile_from_sorted(provenance_elapsed_ms, 99),
    )

    def _pct_from_chunk_length_hist(p: int) -> int:
        total = int(chunk_length_total or 0)
        if total <= 0:
            return 0
        pp = max(0, min(100, int(p)))
        target = int((pp / 100.0) * (total - 1))
        target = max(0, min(total - 1, target))
        seen = 0
        for idx, spec in enumerate(CHUNK_LENGTH_BINS):
            cnt = int(chunk_length_bins[idx] or 0)
            if cnt <= 0:
                continue
            if (seen + cnt) > target:
                lo = int(spec.min) if spec.min is not None else 0
                if spec.max is None:
                    # Open-ended bin; best-effort lower bound.
                    return lo
                hi = int(spec.max)
                if hi <= lo:
                    return lo
                # Linear interpolation within the bin.
                offset = target - seen
                frac = float(offset) / float(cnt) if cnt > 0 else 0.0
                return int(round(lo + (hi - lo) * frac))
            seen += cnt
        # Fallback to last bin lower bound.
        last = CHUNK_LENGTH_BINS[-1] if CHUNK_LENGTH_BINS else None
        if last is None:
            return 0
        return int(last.min or 0)

    chunk_length_percentiles = DatasetProfilePercentiles(
        p25=_pct_from_chunk_length_hist(25),
        p50=_pct_from_chunk_length_hist(50),
        p75=_pct_from_chunk_length_hist(75),
        p90=_pct_from_chunk_length_hist(90),
        p99=_pct_from_chunk_length_hist(99),
    )

    def _pct_from_chunk_token_hist(p: int) -> int:
        total = int(chunk_token_total or 0)
        if total <= 0:
            return 0
        pp = max(0, min(100, int(p)))
        target = int((pp / 100.0) * (total - 1))
        target = max(0, min(total - 1, target))
        seen = 0
        for idx, spec in enumerate(CHUNK_TOKEN_BINS):
            cnt = int(chunk_token_bins[idx] or 0)
            if cnt <= 0:
                continue
            if (seen + cnt) > target:
                lo = int(spec.min) if spec.min is not None else 0
                if spec.max is None:
                    return lo
                hi = int(spec.max)
                if hi <= lo:
                    return lo
                offset = target - seen
                frac = float(offset) / float(cnt) if cnt > 0 else 0.0
                return int(round(lo + (hi - lo) * frac))
            seen += cnt
        last = CHUNK_TOKEN_BINS[-1] if CHUNK_TOKEN_BINS else None
        if last is None:
            return 0
        return int(last.min or 0)

    chunk_token_percentiles = DatasetProfilePercentiles(
        p25=_pct_from_chunk_token_hist(25),
        p50=_pct_from_chunk_token_hist(50),
        p75=_pct_from_chunk_token_hist(75),
        p90=_pct_from_chunk_token_hist(90),
        p99=_pct_from_chunk_token_hist(99),
    )

    coverage_pcts.sort()
    chunk_coverage_percentiles = DatasetProfilePercentiles(
        p25=percentile_from_sorted(coverage_pcts, 25),
        p50=percentile_from_sorted(coverage_pcts, 50),
        p75=percentile_from_sorted(coverage_pcts, 75),
        p90=percentile_from_sorted(coverage_pcts, 90),
        p99=percentile_from_sorted(coverage_pcts, 99),
    )

    overlap_waste_pcts.sort()
    chunk_overlap_waste_percentiles = DatasetProfilePercentiles(
        p25=percentile_from_sorted(overlap_waste_pcts, 25),
        p50=percentile_from_sorted(overlap_waste_pcts, 50),
        p75=percentile_from_sorted(overlap_waste_pcts, 75),
        p90=percentile_from_sorted(overlap_waste_pcts, 90),
        p99=percentile_from_sorted(overlap_waste_pcts, 99),
    )

    # Histograms.
    length_hist = histogram(lengths, TEXT_LENGTH_BINS)
    size_hist = histogram(file_sizes, FILE_SIZE_BINS)
    page_hist = histogram(page_counts, PAGE_COUNT_BINS) if page_counts else []
    chunk_count_hist = histogram(chunk_counts, CHUNK_COUNT_BINS) if chunk_counts else []
    avg_chunk_chars_hist = histogram(avg_chunk_chars, AVG_CHUNK_CHARS_BINS) if avg_chunk_chars else []
    avg_chunk_tokens_hist = histogram(avg_chunk_tokens, AVG_CHUNK_TOKENS_BINS) if avg_chunk_tokens else []
    chunk_length_hist: list[dict[str, Any]] = []
    if int(chunk_length_total or 0) > 0:
        for spec, cnt in zip(CHUNK_LENGTH_BINS, chunk_length_bins, strict=False):
            chunk_length_hist.append({"label": spec.label, "min": spec.min, "max": spec.max, "count": int(cnt)})

    chunk_token_hist: list[dict[str, Any]] = []
    if int(chunk_token_total or 0) > 0:
        for spec, cnt in zip(CHUNK_TOKEN_BINS, chunk_token_bins, strict=False):
            chunk_token_hist.append({"label": spec.label, "min": spec.min, "max": spec.max, "count": int(cnt)})

    coverage_hist = histogram(coverage_pcts, COVERAGE_PCT_BINS) if coverage_pcts else []
    overlap_waste_hist = histogram(overlap_waste_pcts, OVERLAP_WASTE_PCT_BINS) if overlap_waste_pcts else []

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

    chunk_token_bins_by_label: dict[str, int] = {}
    for spec, cnt in zip(CHUNK_TOKEN_BINS, chunk_token_bins, strict=False):
        chunk_token_bins_by_label[str(spec.label)] = int(cnt or 0)

    recall_risk_hints_out = build_recall_risk_hints(
        total_documents=int(sum(by_status.values())),
        chunk_token_bins_by_label=chunk_token_bins_by_label,
        chunk_token_total=int(chunk_token_total or 0),
        duplicate_like_docs=int(duplicate_like_docs),
        low_density_docs=int(finding_counts.get("low_density", 0) or 0),
        parse_low_quality_docs=int(finding_counts.get("parse_low_quality", 0) or 0),
    )

    # Findings list in stable order.
    findings_out: list[DatasetProfileFindingSummary] = []
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

    # Chunk target checks (best-effort; objective signals + suggestions).
    # v2: allow per-dataset overrides via datasets.metadata["chunk_targets_v2"].
    cfg = dataset_metadata if isinstance(dataset_metadata, dict) else {}
    raw_targets = cfg.get("chunk_targets_v2")
    targets = raw_targets if isinstance(raw_targets, dict) else {}

    def _clamp_int(v: object, *, default: int, lo: int, hi: int) -> int:
        try:
            if v is None or isinstance(v, bool):
                return int(default)
            n = int(v)
        except Exception:
            n = int(default)
        return int(max(lo, min(hi, n)))

    tok_target_min = _clamp_int(targets.get("token_p50_min"), default=200, lo=0, hi=4000)
    tok_target_max = _clamp_int(targets.get("token_p50_max"), default=400, lo=0, hi=4000)
    if tok_target_max and tok_target_min and tok_target_min > tok_target_max:
        tok_target_min, tok_target_max = tok_target_max, tok_target_min

    short_warn = _clamp_int(targets.get("short_pct_warn"), default=20, lo=0, hi=100)
    short_fail = _clamp_int(targets.get("short_pct_fail"), default=35, lo=0, hi=100)
    if short_warn > short_fail:
        short_warn, short_fail = short_fail, short_warn

    long_warn = _clamp_int(targets.get("long_pct_warn"), default=10, lo=0, hi=100)
    long_fail = _clamp_int(targets.get("long_pct_fail"), default=20, lo=0, hi=100)
    if long_warn > long_fail:
        long_warn, long_fail = long_fail, long_warn

    waste_warn = _clamp_int(targets.get("overlap_waste_p50_warn"), default=35, lo=0, hi=100)
    waste_fail = _clamp_int(targets.get("overlap_waste_p50_fail"), default=60, lo=0, hi=100)
    if waste_warn > waste_fail:
        waste_warn, waste_fail = waste_fail, waste_warn

    cov_warn = _clamp_int(targets.get("coverage_p50_warn"), default=98, lo=0, hi=100)
    cov_fail = _clamp_int(targets.get("coverage_p50_fail"), default=90, lo=0, hi=100)
    # Coverage is "higher is better": fail threshold should be <= warn threshold.
    if cov_fail > cov_warn:
        cov_fail = cov_warn

    chunk_targets_out: list[DatasetProfileTargetCheck] = []
    try:
        # Token distribution objectives (requires chunking_stats_tokens histogram).
        if int(chunk_token_total or 0) <= 0:
            chunk_targets_out.append(
                DatasetProfileTargetCheck(
                    key="chunk_tokens_missing",
                    label="Chunk tokens 统计缺失",
                    status="warn",
                    observed={"chunk_token_total": int(chunk_token_total or 0)},
                    target={},
                    message="缺少 chunking_stats_tokens，无法进行 token 分布目标检查。",
                    suggestions=["开启 token stats（入库/深度扫描 backfill_chunk_token_stats）后再评估。"],
                )
            )
        else:
            # P50 chunk token length target range (tunable default).
            tok_p50 = int(getattr(chunk_token_percentiles, "p50", 0) or 0)
            if tok_p50 <= 0:
                status = "warn"
            elif tok_p50 < 100 or tok_p50 > 800:
                status = "fail"
            elif tok_p50 < tok_target_min or tok_p50 > tok_target_max:
                status = "warn"
            else:
                status = "pass"

            suggestions: list[str] = []
            if tok_p50 > 0 and tok_p50 < tok_target_min:
                suggestions.append("提高 chunk_size 或使用结构感知 chunk_strategy（markdown_header/outline）以减少碎片化。")
            if tok_p50 > tok_target_max:
                suggestions.append("降低 chunk_size 或提高切分粒度，避免 chunk 过长影响召回与延迟/成本。")

            chunk_targets_out.append(
                DatasetProfileTargetCheck(
                    key="chunk_token_p50_range",
                    label="Chunk token P50 目标范围",
                    status=status,  # type: ignore[arg-type]
                    observed={"p50": tok_p50},
                    target={"p50_min": tok_target_min, "p50_max": tok_target_max},
                    message=f"P50={tok_p50}（目标 {tok_target_min}-{tok_target_max}）",
                    suggestions=suggestions,
                )
            )

            # Short/long chunk ratio checks from histogram bins.
            short_cnt = 0
            for label in ("0-50", "50-100"):
                idx = chunk_token_label_to_idx.get(label)
                if idx is not None:
                    short_cnt += int(chunk_token_bins[idx] or 0)
            long_cnt = 0
            idx_long = chunk_token_label_to_idx.get("800+")
            if idx_long is not None:
                long_cnt = int(chunk_token_bins[idx_long] or 0)
            total_cnt = int(chunk_token_total or 0)
            short_pct = int(round((short_cnt / total_cnt) * 100.0)) if total_cnt > 0 else 0
            long_pct = int(round((long_cnt / total_cnt) * 100.0)) if total_cnt > 0 else 0

            def _pct_status(pct: int, *, warn: int, fail: int) -> str:
                if pct >= int(fail):
                    return "fail"
                if pct >= int(warn):
                    return "warn"
                return "pass"

            short_status = _pct_status(short_pct, warn=short_warn, fail=short_fail)
            long_status = _pct_status(long_pct, warn=long_warn, fail=long_fail)

            chunk_targets_out.append(
                DatasetProfileTargetCheck(
                    key="chunk_token_short_ratio",
                    label="短 Chunk 比例（<=100 tokens）",
                    status=short_status,  # type: ignore[arg-type]
                    observed={"short_chunks": short_cnt, "total_chunks": total_cnt, "short_pct": short_pct},
                    target={"short_pct_warn": short_warn, "short_pct_fail": short_fail},
                    message=f"{short_pct}%（目标 < {short_warn}%）",
                    suggestions=[
                        "若短 chunk 过多：提高 chunk_size/降低切分强度，或使用结构切分避免碎片化。",
                    ]
                    if short_status != "pass"
                    else [],
                )
            )

            chunk_targets_out.append(
                DatasetProfileTargetCheck(
                    key="chunk_token_long_ratio",
                    label="长 Chunk 比例（>=800 tokens）",
                    status=long_status,  # type: ignore[arg-type]
                    observed={"long_chunks": long_cnt, "total_chunks": total_cnt, "long_pct": long_pct},
                    target={"long_pct_warn": long_warn, "long_pct_fail": long_fail},
                    message=f"{long_pct}%（目标 < {long_warn}%）",
                    suggestions=[
                        "若长 chunk 过多：降低 chunk_size 或使用结构切分（markdown_header/outline）提升覆盖与召回稳定性。",
                    ]
                    if long_status != "pass"
                    else [],
                )
            )

        # Coverage objective (requires chunk_coverage metrics).
        if not coverage_pcts:
            chunk_targets_out.append(
                DatasetProfileTargetCheck(
                    key="chunk_coverage_missing",
                    label="Coverage 统计缺失",
                    status="warn",
                    observed={},
                    target={},
                    message="缺少 chunk_coverage / coverage 数据，无法评估 offsets 覆盖率。",
                    suggestions=["开启 backfill_chunk_coverage 或在入库时持久化 chunk offsets。"],
                )
            )
        else:
            cov_p50 = int(getattr(chunk_coverage_percentiles, "p50", 0) or 0)
            cov_status = "pass"
            if cov_p50 <= 0:
                cov_status = "warn"
            elif cov_p50 < int(cov_fail):
                cov_status = "fail"
            elif cov_p50 < int(cov_warn):
                cov_status = "warn"
            chunk_targets_out.append(
                DatasetProfileTargetCheck(
                    key="chunk_coverage_p50",
                    label="Coverage P50（%）",
                    status=cov_status,  # type: ignore[arg-type]
                    observed={"p50": cov_p50},
                    target={"p50_warn": cov_warn, "p50_fail": cov_fail},
                    message=f"P50={cov_p50}%（目标 >= {cov_warn}%）",
                    suggestions=[
                        "若 coverage 偏低：检查 parser_backend 输出与 offsets rebasing（page_index/start_char）是否一致。",
                    ]
                    if cov_status != "pass"
                    else [],
                )
            )

        # Overlap waste objective (requires chunk_coverage metrics).
        if not overlap_waste_pcts:
            chunk_targets_out.append(
                DatasetProfileTargetCheck(
                    key="chunk_overlap_waste_missing",
                    label="Overlap waste 统计缺失",
                    status="warn",
                    observed={},
                    target={},
                    message="缺少 chunk_coverage / overlap_waste 数据，无法评估 overlap 成本。",
                    suggestions=["开启 backfill_chunk_coverage 或在入库时持久化 chunk offsets。"],
                )
            )
        else:
            waste_p50 = int(getattr(chunk_overlap_waste_percentiles, "p50", 0) or 0)
            waste_status = "pass"
            if waste_p50 >= int(waste_fail):
                waste_status = "fail"
            elif waste_p50 >= int(waste_warn):
                waste_status = "warn"
            chunk_targets_out.append(
                DatasetProfileTargetCheck(
                    key="chunk_overlap_waste_p50",
                    label="Overlap waste P50（%）",
                    status=waste_status,  # type: ignore[arg-type]
                    observed={"p50": waste_p50},
                    target={"p50_warn": waste_warn, "p50_fail": waste_fail},
                    message=f"P50={waste_p50}%（目标 < {waste_warn}%）",
                    suggestions=["降低 chunk_overlap 可减少重复 embedding 计算与成本。"] if waste_status != "pass" else [],
                )
            )
    except Exception:
        chunk_targets_out = []

    now = datetime.now(UTC)
    return DatasetProfileSummary(
        dataset_id=dataset_id,
        generated_at=now,
        total_documents=int(sum(by_status.values())),
        total_size_bytes=int(total_size),
        by_status={k: int(v) for k, v in by_status.items()},
        by_file_type={k: int(v) for k, v in by_type.items()},
        by_directory={k: int(v) for k, v in directory_counts.items()},
        by_quality_bucket={k: int(v) for k, v in quality_bucket_counts.items()},
        file_size_histogram=size_hist,
        length_percentiles=percentiles,
        length_histogram=length_hist,
        chunk_count_percentiles=chunk_count_percentiles,
        chunk_count_histogram=chunk_count_hist,
        avg_chunk_chars_percentiles=avg_chunk_chars_percentiles,
        avg_chunk_chars_histogram=avg_chunk_chars_hist,
        chunk_length_percentiles=chunk_length_percentiles,
        chunk_length_histogram=chunk_length_hist,
        chunk_token_percentiles=chunk_token_percentiles,
        chunk_token_histogram=chunk_token_hist,
        avg_chunk_tokens_percentiles=avg_chunk_tokens_percentiles,
        avg_chunk_tokens_histogram=avg_chunk_tokens_hist,
        chunk_coverage_percentiles=chunk_coverage_percentiles,
        chunk_coverage_histogram=coverage_hist,
        chunk_overlap_waste_percentiles=chunk_overlap_waste_percentiles,
        chunk_overlap_waste_histogram=overlap_waste_hist,
        page_number_histogram=page_hist,
        parse_quality_histogram=pq_hist,
        language_mix=language_mix,
        pdf_scan=DatasetProfilePdfScanStats(scanned=pdf_scanned, not_scanned=pdf_not_scanned, unknown=pdf_unknown),
        parsing_provenance=DatasetProfileParsingProvenanceStats(
            docs_with_provenance=int(provenance_docs),
            by_resolved_backend={k: int(v) for k, v in provenance_by_backend.items()},
            fallback_docs=int(provenance_fallback_docs),
            elapsed_ms_percentiles=provenance_elapsed_percentiles,
        ),
        pii_hits_total={k: int(v) for k, v in pii_totals.items()},
        secrets_hits_total={k: int(v) for k, v in secrets_totals.items()},
        findings=findings_out,
        recall_risk_hints=recall_risk_hints_out,
        chunk_targets=chunk_targets_out,
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
    dataset, query = build_dataset_documents_query(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
    dataset_meta = dict(getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}

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
        dataset_metadata=dataset_meta,
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

    if key == "preprocess_failed":
        # error_message starts with "preprocess_failed: ..."
        err_expr = func.lower(func.coalesce(DBDocument.error_message, ""))
        return query.filter(DBDocument.status == "failed", err_expr.like("preprocess_failed%"))

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

    if key == "seal_low_confidence":
        return query.filter(
            func.coalesce(DBDocument.doc_metadata["seal_summary"]["detected"].as_boolean(), False) == True,  # noqa: E712
            func.coalesce(DBDocument.doc_metadata["seal_summary"]["primary_score"].as_float(), 1.0) < float(_SEAL_CONFIDENCE_LOW_THRESHOLD),
        )

    if key == "pii":
        # governance_pii_hits exists and not empty
        return query.filter(DBDocument.doc_metadata["governance_pii_hits"].is_not(None))

    if key == "secrets":
        return query.filter(DBDocument.doc_metadata["governance_secrets_hits"].is_not(None))

    if key == "image_heavy":
        return query.filter(func.coalesce(DBDocument.doc_metadata["image_count"].as_integer(), 0) >= int(image_threshold))

    if key == "chunk_coverage_low":
        return query.filter(
            func.coalesce(DBDocument.doc_metadata["chunk_coverage"]["coverage_ratio"].as_float(), 1.0) < 0.98,
        )

    if key == "chunk_quality_fail":
        return query.filter(
            func.coalesce(DBDocument.doc_metadata["chunk_quality_gate"]["grade"].as_string(), "") == "fail",
        )

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


_WS_RE = re.compile(r"\s+")


def _collapse_ws(text: object) -> str:
    return _WS_RE.sub(" ", str(text or "").strip())


def _safe_preview(text: str, *, max_chars: int) -> tuple[str | None, bool]:
    """
    Produce a short, PII-safe preview snippet from markdown.

    NOTE: This is best-effort and intentionally conservative:
    - always anonymize common PII (email/phone/id/ip)
    - always redact common tokens/secrets
    """

    max_chars = max(80, min(int(max_chars or 0), 2000))
    raw = str(text or "").strip()
    if not raw:
        return None, False

    # Keep bounded input for redaction work.
    window = raw[: max(4000, max_chars * 10)]
    pii = anonymize_pii(window, enabled=True, mode="mask", mask="[REDACTED]")
    sec = redact_secrets(pii.text, enabled=True, mode="mask", mask="[SECRET]")
    safe = _collapse_ws(sec.text)
    if not safe:
        return None, False
    truncated = len(safe) > max_chars
    return safe[:max_chars].rstrip(), bool(truncated)


def list_bucket_documents(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    dimension: str,
    bucket: str,
    skip: int = 0,
    limit: int = 50,
    include_preview: bool = True,
    preview_max_chars: int = 360,
) -> DatasetProfileDocumentListResponse:
    """
    List documents for a specific dataset profile bucket.

    Bucket dimensions intentionally align with eval slicing:
    - file_type
    - language (zh/en/mixed/unknown)
    - directory (top-level from metadata.source_path)
    - quality_bucket (derived from metadata.governance_quality)
    """

    dim = str(dimension or "").strip().lower()
    if dim not in {"file_type", "language", "directory", "quality_bucket"}:
        raise ValueError("Unknown dimension")

    # Reuse the summary cache to get an accurate total without an extra full scan.
    summary = compute_dataset_profile_summary(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)

    raw_bucket = str(bucket or "").strip()
    if not raw_bucket:
        raw_bucket = "unknown"

    if dim == "file_type":
        bucket_key = raw_bucket.strip().lower() or "unknown"
        total = int((summary.by_file_type or {}).get(bucket_key, 0) or 0)
    elif dim == "language":
        bucket_key = normalize_language_bucket(raw_bucket)
        total = int((summary.language_mix or {}).get(bucket_key, 0) or 0)
    elif dim == "directory":
        # directory buckets preserve case; match case-insensitively for UX.
        bucket_key = raw_bucket
        total = 0
        for k, v in (summary.by_directory or {}).items():
            if str(k).casefold() == bucket_key.casefold():
                total = int(v or 0)
                break
    else:  # quality_bucket
        bucket_key = raw_bucket.strip().lower() or "unknown"
        total = int((summary.by_quality_bucket or {}).get(bucket_key, 0) or 0)

    # Fast exit.
    if total <= 0:
        return DatasetProfileDocumentListResponse(total=0, items=[])

    _dataset, base = build_dataset_documents_query(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
    q = (
        base.with_entities(
            DBDocument.id,
            DBDocument.dataset_id,
            DBDocument.filename,
            DBDocument.file_type,
            DBDocument.file_size,
            DBDocument.status,
            DBDocument.chunk_count,
            DBDocument.total_characters,
            DBDocument.created_at,
            DBDocument.updated_at,
            DBDocument.error_message,
            DBDocument.doc_metadata,
        )
        .order_by(DBDocument.updated_at.desc(), DBDocument.id.asc())
        .execution_options(stream_results=True)
        .enable_eagerloads(False)
        .yield_per(1000)
    )

    skip_n = max(0, int(skip or 0))
    lim = max(1, min(int(limit or 0), 200))

    matched = 0
    picked: list[tuple] = []
    for row in q:
        (
            _doc_id,
            _ds_id,
            filename,
            file_type,
            _file_size,
            _status,
            _chunk_count,
            _total_chars,
            _created_at,
            _updated_at,
            _err,
            meta,
        ) = row
        meta_dict = meta if isinstance(meta, dict) else {}

        if dim == "file_type":
            val = _normalize_file_type(file_type, filename).lower()
            ok = val == bucket_key
        elif dim == "language":
            val = extract_language_bucket(meta_dict)
            ok = val == bucket_key
        elif dim == "directory":
            val = directory_bucket_from_source_path(meta_dict.get("source_path"))
            ok = val.casefold() == bucket_key.casefold()
        else:  # quality_bucket
            val = quality_bucket_from_governance_quality(meta_dict.get("governance_quality")).lower()
            ok = val == bucket_key

        if not ok:
            continue

        if matched < skip_n:
            matched += 1
            continue

        if len(picked) >= lim:
            break

        picked.append(row)
        matched += 1

    previews: dict[UUID, tuple[str | None, bool]] = {}
    if include_preview and picked:
        ids = [r[0] for r in picked if r and r[0]]
        if ids:
            rows = (
                db.query(DocumentParsedContent.document_id, DocumentParsedContent.markdown_content)
                .filter(DocumentParsedContent.tenant_id == tenant_id, DocumentParsedContent.document_id.in_(ids))
                .all()
            )
            by_id: dict[UUID, str] = {}
            for doc_id, md in rows:
                if doc_id and isinstance(md, str) and md.strip():
                    by_id[doc_id] = md
            for doc_id in ids:
                md = by_id.get(doc_id) or ""
                previews[doc_id] = _safe_preview(md, max_chars=int(preview_max_chars or 0))

    out_items: list[DatasetProfileDocumentOut] = []
    for (
        doc_id,
        ds_id,
        filename,
        file_type,
        file_size,
        status,
        chunk_count,
        total_chars,
        created_at,
        updated_at,
        err,
        meta,
    ) in picked:
        meta_dict = meta if isinstance(meta, dict) else {}
        preview, trunc = previews.get(doc_id, (None, False))
        out_items.append(
            DatasetProfileDocumentOut(
                id=doc_id,
                dataset_id=ds_id,
                filename=str(filename or ""),
                file_type=str(file_type or ""),
                file_size=int(file_size or 0),
                status=str(status or ""),
                chunk_count=int(chunk_count or 0),
                total_characters=int(total_chars or 0),
                created_at=created_at,
                updated_at=updated_at,
                error_message=str(err) if err else None,
                metadata=dict(meta_dict),
                preview=preview,
                preview_truncated=bool(trunc),
            )
        )

    return DatasetProfileDocumentListResponse(total=total, items=out_items)
