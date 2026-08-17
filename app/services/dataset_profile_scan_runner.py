"""
Deep dataset profile scan runner.

This performs best-effort *backfills* for missing per-document metrics so that
the dataset profile summary and drill-down pages are more complete.

It is intended to run as a background job (arq worker) but can also run inline
when TASK_QUEUE_ENABLED=false.
"""

import contextlib
import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dataset_profile_scan import DatasetProfileScanRun as DBDatasetProfileScanRun
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk, DocumentParsedContent
from app.parsing.quality.document_quality import score_document_parse_quality
from app.parsing.quality.scorer import score_pdf_quality
from app.parsing.quality.text_quality import score_parsed_text_quality
from app.rag.core.logging import get_logger
from app.services.dataset_profile_service import build_dataset_documents_query, compute_dataset_profile_summary
from app.storage.object.runtime import is_object_storage_uri, resolve_document_object_reference

logger = get_logger("services.dataset_profile_scan")


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _safe_hash_file(path: Path, *, algo: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _download_object_storage_document_to_temp(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    document: DBDocument,
    temp_dir: Path,
) -> Path:
    """
    Download a document stored in object storage to a local temp path.
    """
    raw_path = str(getattr(document, "file_path", "") or "").strip()
    store, ref = resolve_document_object_reference(
        raw_path,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document.id,
        file_type=document.file_type,
        document_metadata=dict(getattr(document, "doc_metadata", None) or {}),
    )

    suffix = f".{(document.file_type or '').lower()}" if str(getattr(document, "file_type", "") or "").strip() else ""
    temp_dir.mkdir(parents=True, exist_ok=True)
    out = temp_dir / f"{str(document.id)}{suffix}"
    store.download_object_to_path(
        object_name=ref.object_name,
        destination=out,
        max_bytes=int(getattr(settings, "MAX_FILE_SIZE", 0) or 0),
    )
    return out


def _ensure_local_path(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    document: DBDocument,
    temp_root: Path,
) -> tuple[Path, Path | None]:
    """
    Return (local_path, temp_path_if_downloaded).
    """
    raw = str(getattr(document, "file_path", "") or "").strip()
    if not raw or raw.startswith("manual://"):
        raise ValueError("document_file_not_available")

    if is_object_storage_uri(raw):
        if not bool(getattr(settings, "MINIO_ENABLED", False)) and not bool(
            getattr(settings, "OBJECT_STORAGE_ENABLED", False)
        ):
            raise ValueError("object_storage_disabled")
        temp_dir = (temp_root / str(tenant_id) / ".tmp").resolve(strict=False)
        temp_path = _download_object_storage_document_to_temp(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document=document,
            temp_dir=temp_dir,
        )
        return temp_path, temp_path

    path = Path(raw)
    if not path.exists() or not path.is_file():
        raise ValueError("document_file_not_found")
    return path, None


def _backfill_parse_quality(meta: dict[str, Any]) -> bool:
    """Best-effort: attach unified parse quality score when missing."""
    existing = meta.get("parse_quality")
    if isinstance(existing, dict) and existing.get("score") is not None:
        return False

    pdf_quality = meta.get("pdf_quality") if isinstance(meta.get("pdf_quality"), dict) else None
    text_quality = meta.get("parsed_text_quality") if isinstance(meta.get("parsed_text_quality"), dict) else None
    if pdf_quality is None and text_quality is None:
        return False

    meta["parse_quality"] = score_document_parse_quality(
        pdf_quality=pdf_quality,
        parsed_text_quality=text_quality,
    )
    return True


def _backfill_page_count(meta: dict[str, Any], parsed: dict[str, Any] | None = None) -> bool:
    """
    Best-effort: persist a stable page_count when missing.

    Notes:
    - We only copy from already-computed parse artifacts / pdf_quality metadata.
    - This keeps the real-time profile summary cheap (no chunk scans).
    """
    existing = meta.get("page_count")
    if isinstance(existing, (int, float)) and int(existing) > 0:
        return False

    src = parsed if isinstance(parsed, dict) else {}
    page_count = src.get("page_count")
    if page_count is None:
        page_count = src.get("page_max")
    if not isinstance(page_count, (int, float)) or int(page_count) <= 0:
        return False

    meta["page_count"] = int(page_count)
    return True


def _backfill_language(meta: dict[str, Any]) -> bool:
    """
    Best-effort: ensure a stable `language` key exists for profiling charts.

    We do not attempt language detection here (belongs to parsing/governance).
    """
    existing = meta.get("language")
    if isinstance(existing, str) and existing.strip():
        return False

    enr = meta.get("governance_enrichment")
    if isinstance(enr, dict):
        raw = enr.get("language")
        if isinstance(raw, str) and raw.strip():
            meta["language"] = raw.strip()
            return True

    meta["language"] = "unknown"
    return True


@dataclass(frozen=True)
class _DeepScanOptions:
    backfill_pdf_quality: bool
    backfill_text_quality: bool
    backfill_chunk_stats: bool
    backfill_chunk_token_stats: bool
    backfill_chunk_coverage: bool
    backfill_chunk_quality_gate: bool
    compute_file_hash: bool
    max_documents: int | None


@dataclass
class _DeepScanStats:
    documents: int
    updated_docs: int = 0
    pdf_backfilled: int = 0
    text_backfilled: int = 0
    chunk_stats_backfilled: int = 0
    chunk_token_stats_backfilled: int = 0
    chunk_coverage_backfilled: int = 0
    chunk_quality_gate_backfilled: int = 0
    hash_backfilled: int = 0
    errors: int = 0

    def as_result(self) -> dict[str, Any]:
        return {
            "ok": True,
            "documents": int(self.documents),
            "updated_docs": int(self.updated_docs),
            "pdf_backfilled": int(self.pdf_backfilled),
            "text_backfilled": int(self.text_backfilled),
            "chunk_stats_backfilled": int(self.chunk_stats_backfilled),
            "chunk_token_stats_backfilled": int(self.chunk_token_stats_backfilled),
            "chunk_coverage_backfilled": int(self.chunk_coverage_backfilled),
            "chunk_quality_gate_backfilled": int(self.chunk_quality_gate_backfilled),
            "hash_backfilled": int(self.hash_backfilled),
            "errors": int(self.errors),
        }


def _load_deep_scan_run(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    scan_run_id: UUID,
) -> DBDatasetProfileScanRun | None:
    return (
        db.query(DBDatasetProfileScanRun)
        .filter(
            DBDatasetProfileScanRun.id == scan_run_id,
            DBDatasetProfileScanRun.tenant_id == tenant_id,
            DBDatasetProfileScanRun.dataset_id == dataset_id,
        )
        .first()
    )


def _mark_deep_scan_running(db: Session, run: DBDatasetProfileScanRun) -> None:
    run.status = "running"
    run.progress = 0
    run.started_at = _now_utc()
    run.updated_at = run.started_at
    run.error_message = None
    db.commit()


def _build_deep_scan_options(run: DBDatasetProfileScanRun) -> _DeepScanOptions:
    cfg = dict(getattr(run, "config", None) or {})
    max_docs_raw = cfg.get("max_documents")
    max_documents = int(max_docs_raw) if isinstance(max_docs_raw, (int, float)) and int(max_docs_raw) > 0 else None
    return _DeepScanOptions(
        backfill_pdf_quality=bool(cfg.get("backfill_pdf_quality", True)),
        backfill_text_quality=bool(cfg.get("backfill_text_quality", True)),
        backfill_chunk_stats=bool(cfg.get("backfill_chunk_stats", True)),
        backfill_chunk_token_stats=bool(cfg.get("backfill_chunk_token_stats", False)),
        backfill_chunk_coverage=bool(cfg.get("backfill_chunk_coverage", False)),
        backfill_chunk_quality_gate=bool(cfg.get("backfill_chunk_quality_gate", False)),
        compute_file_hash=bool(cfg.get("compute_file_hash", False)),
        max_documents=max_documents,
    )


def _load_deep_scan_documents(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    max_documents: int | None,
) -> list[DBDocument]:
    _dataset, query = build_dataset_documents_query(
        db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id
    )
    ordered_query = query.order_by(DBDocument.created_at.asc(), DBDocument.id.asc())
    if max_documents:
        ordered_query = ordered_query.limit(max_documents)
    return ordered_query.all()


def _flush_deep_scan_progress(
    db: Session,
    run: DBDatasetProfileScanRun,
    *,
    processed: int,
    total: int,
    last_progress_write: float,
    force: bool = False,
) -> float:
    now = time.monotonic()
    if not force and (now - last_progress_write) < 0.5:
        return last_progress_write
    run.progress = max(0, min(100, int((processed / max(1, total)) * 100)))
    run.updated_at = _now_utc()
    db.commit()
    return now


def _mark_deep_scan_completed(db: Session, run: DBDatasetProfileScanRun) -> None:
    run.status = "completed"
    run.progress = 100
    run.finished_at = _now_utc()
    run.updated_at = run.finished_at
    db.commit()


def _persist_deep_scan_summary(
    db: Session,
    run: DBDatasetProfileScanRun,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
) -> None:
    summary = compute_dataset_profile_summary(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
    run.summary = summary.model_dump(mode="json")
    db.commit()


def _complete_empty_deep_scan(
    db: Session,
    run: DBDatasetProfileScanRun,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
) -> dict[str, Any]:
    _mark_deep_scan_completed(db, run)
    _persist_deep_scan_summary(db, run, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
    return {"ok": True, "documents": 0}


def _load_text_for_quality(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
) -> str:
    rec = (
        db.query(DocumentParsedContent.markdown_content)
        .filter(DocumentParsedContent.tenant_id == tenant_id, DocumentParsedContent.document_id == document_id)
        .first()
    )
    if rec and isinstance(rec[0], str) and rec[0].strip():
        return rec[0]

    rows = (
        db.query(DocumentChunk.content)
        .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(50)
        .all()
    )
    sampled = [r[0] for r in rows if r and isinstance(r[0], str) and r[0].strip()]
    if sampled:
        return "\n\n".join(sampled)
    return ""


def _maybe_backfill_pdf_quality(
    meta: dict[str, Any],
    *,
    document: DBDocument,
    tenant_id: UUID,
    dataset_id: UUID,
    temp_root: Path,
    options: _DeepScanOptions,
    stats: _DeepScanStats,
) -> bool:
    if not options.backfill_pdf_quality:
        return False
    if str(getattr(document, "file_type", "") or "").strip().lower() != "pdf":
        return False
    if isinstance(meta.get("pdf_quality"), dict) and meta.get("pdf_quality"):
        return False

    local_path, temp_path = _ensure_local_path(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document=document,
        temp_root=temp_root,
    )
    try:
        quality = score_pdf_quality(
            local_path,
            sample_pages=3,
            use_ocr_validation=bool(getattr(settings, "RAPIDOCR_ENABLED", False)),
        )
        if not isinstance(quality, dict) or not quality:
            return False
        meta["pdf_quality"] = quality
        stats.pdf_backfilled += 1
        return True
    finally:
        if temp_path is not None:
            with contextlib.suppress(Exception):
                temp_path.unlink(missing_ok=True)


def _maybe_backfill_text_quality(
    db: Session,
    meta: dict[str, Any],
    *,
    tenant_id: UUID,
    document: DBDocument,
    options: _DeepScanOptions,
    stats: _DeepScanStats,
) -> bool:
    if not options.backfill_text_quality:
        return False
    if isinstance(meta.get("parsed_text_quality"), dict) and meta.get("parsed_text_quality"):
        return False

    text = _load_text_for_quality(db, tenant_id=tenant_id, document_id=document.id)
    if not text.strip():
        return False

    meta["parsed_text_quality"] = score_parsed_text_quality(text[:200_000]).to_dict()
    stats.text_backfilled += 1
    return True


def _maybe_backfill_chunk_stats(
    db: Session,
    meta: dict[str, Any],
    *,
    tenant_id: UUID,
    document: DBDocument,
    options: _DeepScanOptions,
    stats: _DeepScanStats,
) -> bool:
    if not options.backfill_chunk_stats:
        return False
    existing = meta.get("chunking_stats")
    has_hist = (
        isinstance(existing, dict) and isinstance(existing.get("histogram"), list) and bool(existing.get("histogram"))
    )
    if has_hist:
        return False

    rows = (
        db.query(func.length(func.trim(DocumentChunk.content)))
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document.id,
            DocumentChunk.disabled_at.is_(None),
        )
        .all()
    )
    lengths: list[int] = []
    for row in rows:
        if not row:
            continue
        try:
            length = int(row[0] or 0)
        except Exception:
            length = 0
        if length > 0:
            lengths.append(length)

    if not lengths:
        return False

    from app.services.chunking_stats_utils import compute_chunking_stats_from_lengths

    stats_payload = compute_chunking_stats_from_lengths(lengths, short_threshold=120, duplicate_count=0)
    if not stats_payload:
        return False

    meta["chunking_stats"] = stats_payload
    stats.chunk_stats_backfilled += 1
    return True


def _maybe_backfill_chunk_token_stats(
    db: Session,
    meta: dict[str, Any],
    *,
    tenant_id: UUID,
    document: DBDocument,
    options: _DeepScanOptions,
    stats: _DeepScanStats,
) -> bool:
    if not options.backfill_chunk_token_stats:
        return False
    existing = meta.get("chunking_stats_tokens")
    has_hist = (
        isinstance(existing, dict) and isinstance(existing.get("histogram"), list) and bool(existing.get("histogram"))
    )
    if has_hist:
        return False

    rows = (
        db.query(DocumentChunk.content)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document.id,
            DocumentChunk.disabled_at.is_(None),
        )
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    texts = [row[0] for row in rows if row and isinstance(row[0], str) and row[0].strip()]
    if not texts:
        return False

    from app.services.chunking_stats_utils import compute_chunking_stats_from_texts_tokens

    stats_payload = compute_chunking_stats_from_texts_tokens(texts)
    if not stats_payload:
        return False

    meta["chunking_stats_tokens"] = stats_payload
    stats.chunk_token_stats_backfilled += 1
    return True


def _maybe_backfill_chunk_coverage(
    db: Session,
    meta: dict[str, Any],
    *,
    tenant_id: UUID,
    document: DBDocument,
    options: _DeepScanOptions,
    stats: _DeepScanStats,
) -> bool:
    if not options.backfill_chunk_coverage:
        return False
    existing = meta.get("chunk_coverage")
    has_coverage = isinstance(existing, dict) and (existing.get("coverage_ratio") is not None)
    total_characters = int(getattr(document, "total_characters", 0) or 0)
    if has_coverage or total_characters <= 0:
        return False

    rows = (
        db.query(
            DocumentChunk.start_char,
            DocumentChunk.end_char,
            func.length(DocumentChunk.content),
        )
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document.id,
            DocumentChunk.disabled_at.is_(None),
        )
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    ranges: list[tuple[int, int]] = []
    for row in rows:
        if not row:
            continue
        range_value = _normalize_chunk_range(row)
        if range_value is not None:
            ranges.append(range_value)
    if not ranges:
        return False

    from app.services.chunk_coverage_utils import compute_chunk_coverage_metrics_from_ranges

    coverage = compute_chunk_coverage_metrics_from_ranges(ranges, total_characters=total_characters)
    if not coverage:
        return False

    meta["chunk_coverage"] = {**dict(coverage), "ranges_used": int(len(ranges))}
    stats.chunk_coverage_backfilled += 1
    return True


def _normalize_chunk_range(row: Any) -> tuple[int, int] | None:
    start = row[0]
    end = row[1]
    length = row[2]
    if start is None:
        return None
    try:
        start_value = int(start)
    except Exception:
        get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
        return None

    if end is None:
        try:
            end_value = start_value + int(length or 0)
        except Exception:
            end_value = start_value
    else:
        try:
            end_value = int(end)
        except Exception:
            end_value = start_value
    if end_value <= start_value:
        return None
    return (start_value, end_value)


def _maybe_backfill_chunk_quality_gate(
    meta: dict[str, Any],
    *,
    document: DBDocument,
    options: _DeepScanOptions,
    stats: _DeepScanStats,
) -> bool:
    if not options.backfill_chunk_quality_gate:
        return False
    existing = meta.get("chunk_quality_gate")
    has_gate = isinstance(existing, dict) and isinstance(existing.get("grade"), str) and bool(existing.get("grade"))
    if has_gate:
        return False

    chunk_stats = meta.get("chunking_stats") if isinstance(meta.get("chunking_stats"), dict) else {}
    coverage = meta.get("chunk_coverage") if isinstance(meta.get("chunk_coverage"), dict) else {}
    effective = meta.get("pipeline_effective") if isinstance(meta.get("pipeline_effective"), dict) else {}
    if not chunk_stats and not coverage:
        return False

    from app.services.chunk_quality_gate import compute_chunk_quality_gate

    gate, recommendations, patches = compute_chunk_quality_gate(
        stats={
            "count": int(chunk_stats.get("count") or 0),
            "short_count": int(chunk_stats.get("short_count") or 0),
            "duplicate_count": int(chunk_stats.get("duplicate_count") or 0),
            "covered_chars": int(coverage.get("covered_chars") or 0),
            "coverage_ratio": float(coverage.get("coverage_ratio") or 0.0),
            "overlap_waste_ratio": float(coverage.get("overlap_waste_ratio") or 0.0),
            "gap_count": int(coverage.get("gap_count") or 0),
        },
        total_chunks=int(getattr(document, "chunk_count", 0) or 0),
        total_characters=int(getattr(document, "total_characters", 0) or 0),
        chunk_size=_safe_int(effective.get("chunk_size")),
        chunk_overlap=_safe_int(effective.get("chunk_overlap")),
        original_text_included=False,
        original_text_truncated=False,
        original_text_max_chars=0,
    )
    if not isinstance(gate, dict) or not gate.get("grade"):
        return False

    meta["chunk_quality_gate"] = gate
    if recommendations:
        meta["chunk_quality_recommendations"] = list(recommendations)[:10]
    if patches:
        meta["chunk_quality_patches"] = list(patches)[:10]
    stats.chunk_quality_gate_backfilled += 1
    return True


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _maybe_backfill_file_hash(
    meta: dict[str, Any],
    *,
    document: DBDocument,
    tenant_id: UUID,
    dataset_id: UUID,
    temp_root: Path,
    options: _DeepScanOptions,
    stats: _DeepScanStats,
) -> bool:
    if not options.compute_file_hash:
        return False
    if str(meta.get("file_sha256") or "").strip().lower():
        return False

    local_path, temp_path = _ensure_local_path(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document=document,
        temp_root=temp_root,
    )
    try:
        meta["file_sha256"] = _safe_hash_file(local_path, algo="sha256")
        stats.hash_backfilled += 1
        return True
    finally:
        if temp_path is not None:
            with contextlib.suppress(Exception):
                temp_path.unlink(missing_ok=True)


def _process_deep_scan_document(
    db: Session,
    document: DBDocument,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    temp_root: Path,
    options: _DeepScanOptions,
    stats: _DeepScanStats,
) -> bool:
    meta = dict(getattr(document, "doc_metadata", None) or {})
    changed = _maybe_backfill_pdf_quality(
        meta,
        document=document,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        temp_root=temp_root,
        options=options,
        stats=stats,
    )
    changed = (
        _backfill_page_count(meta, meta.get("pdf_quality") if isinstance(meta.get("pdf_quality"), dict) else None)
        or changed
    )
    changed = (
        _maybe_backfill_text_quality(
            db,
            meta,
            tenant_id=tenant_id,
            document=document,
            options=options,
            stats=stats,
        )
        or changed
    )
    changed = _backfill_language(meta) or changed
    changed = _backfill_parse_quality(meta) or changed
    changed = (
        _maybe_backfill_chunk_stats(
            db,
            meta,
            tenant_id=tenant_id,
            document=document,
            options=options,
            stats=stats,
        )
        or changed
    )
    changed = (
        _maybe_backfill_chunk_token_stats(
            db,
            meta,
            tenant_id=tenant_id,
            document=document,
            options=options,
            stats=stats,
        )
        or changed
    )
    changed = (
        _maybe_backfill_chunk_coverage(
            db,
            meta,
            tenant_id=tenant_id,
            document=document,
            options=options,
            stats=stats,
        )
        or changed
    )
    changed = (
        _maybe_backfill_chunk_quality_gate(
            meta,
            document=document,
            options=options,
            stats=stats,
        )
        or changed
    )
    changed = (
        _maybe_backfill_file_hash(
            meta,
            document=document,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            temp_root=temp_root,
            options=options,
            stats=stats,
        )
        or changed
    )
    if not changed:
        return False

    document.doc_metadata = meta
    stats.updated_docs += 1
    return True


def run_dataset_profile_deep_scan(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    scan_run_id: UUID,
) -> dict[str, Any]:
    """
    Execute a deep scan run.

    Returns a small stats dict for logs/worker result.
    """
    run = _load_deep_scan_run(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
    if run is None:
        raise ValueError("scan_run_not_found")

    _mark_deep_scan_running(db, run)
    options = _build_deep_scan_options(run)
    docs = _load_deep_scan_documents(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        max_documents=options.max_documents,
    )
    if not docs:
        return _complete_empty_deep_scan(
            db,
            run,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
        )

    stats = _DeepScanStats(documents=len(docs))
    temp_root = Path(getattr(settings, "UPLOAD_DIR", "./uploads") or "./uploads")
    last_progress_write = time.monotonic()

    for idx, doc in enumerate(docs, start=1):
        try:
            changed = _process_deep_scan_document(
                db,
                doc,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                temp_root=temp_root,
                options=options,
                stats=stats,
            )
        except Exception as exc:  # noqa: BLE001
            stats.errors += 1
            logger.warning("Deep scan failed for doc=%s: %s", str(getattr(doc, "id", "")), str(exc)[:200])
        else:
            if changed and stats.updated_docs % 20 == 0:
                db.commit()

        last_progress_write = _flush_deep_scan_progress(
            db,
            run,
            processed=idx,
            total=stats.documents,
            last_progress_write=last_progress_write,
        )

    db.commit()
    _mark_deep_scan_completed(db, run)
    _persist_deep_scan_summary(db, run, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
    return stats.as_result()
