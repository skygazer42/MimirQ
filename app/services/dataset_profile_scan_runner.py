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
    run = (
        db.query(DBDatasetProfileScanRun)
        .filter(
            DBDatasetProfileScanRun.id == scan_run_id,
            DBDatasetProfileScanRun.tenant_id == tenant_id,
            DBDatasetProfileScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if run is None:
        raise ValueError("scan_run_not_found")

    # Mark running.
    run.status = "running"
    run.progress = 0
    run.started_at = _now_utc()
    run.updated_at = run.started_at
    run.error_message = None
    db.commit()

    cfg = dict(getattr(run, "config", None) or {})
    backfill_pdf_quality = bool(cfg.get("backfill_pdf_quality", True))
    backfill_text_quality = bool(cfg.get("backfill_text_quality", True))
    backfill_chunk_stats = bool(cfg.get("backfill_chunk_stats", True))
    backfill_chunk_token_stats = bool(cfg.get("backfill_chunk_token_stats", False))
    backfill_chunk_coverage = bool(cfg.get("backfill_chunk_coverage", False))
    backfill_chunk_quality_gate = bool(cfg.get("backfill_chunk_quality_gate", False))
    compute_file_hash = bool(cfg.get("compute_file_hash", False))
    max_docs_raw = cfg.get("max_documents")
    max_documents = int(max_docs_raw) if isinstance(max_docs_raw, (int, float)) and int(max_docs_raw) > 0 else None

    _dataset, query = build_dataset_documents_query(
        db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id
    )

    # Only fetch fields we need; keep the ORM objects for metadata updates.
    docs = (
        query.order_by(DBDocument.created_at.asc(), DBDocument.id.asc()).limit(max_documents)
        if max_documents
        else query.order_by(DBDocument.created_at.asc(), DBDocument.id.asc())
    ).all()

    total = len(docs)
    if total == 0:
        run.status = "completed"
        run.progress = 100
        run.finished_at = _now_utc()
        run.updated_at = run.finished_at
        db.commit()
        summary = compute_dataset_profile_summary(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
        run.summary = summary.model_dump(mode="json")
        db.commit()
        return {"ok": True, "documents": 0}

    temp_root = Path(getattr(settings, "UPLOAD_DIR", "./uploads") or "./uploads")
    updated_docs = 0
    pdf_backfilled = 0
    text_backfilled = 0
    chunk_stats_backfilled = 0
    chunk_token_stats_backfilled = 0
    chunk_coverage_backfilled = 0
    chunk_quality_gate_backfilled = 0
    hash_backfilled = 0
    errors = 0

    last_progress_write = time.monotonic()

    def flush_progress(processed: int, *, force: bool = False) -> None:
        nonlocal last_progress_write
        now = time.monotonic()
        if not force and (now - last_progress_write) < 0.5:
            return
        last_progress_write = now
        pct = int((processed / max(1, total)) * 100)
        run.progress = max(0, min(100, pct))
        run.updated_at = _now_utc()
        db.commit()

    for idx, doc in enumerate(docs, start=1):
        meta = dict(getattr(doc, "doc_metadata", None) or {})
        changed = False

        try:
            # Backfill PDF quality (scan detection).
            if backfill_pdf_quality and str(getattr(doc, "file_type", "") or "").strip().lower() == "pdf":
                if not isinstance(meta.get("pdf_quality"), dict) or not meta.get("pdf_quality"):
                    local_path, temp_path = _ensure_local_path(
                        tenant_id=tenant_id,
                        dataset_id=dataset_id,
                        document=doc,
                        temp_root=temp_root,
                    )
                    try:
                        quality = score_pdf_quality(
                            local_path,
                            sample_pages=3,
                            use_ocr_validation=bool(getattr(settings, "RAPIDOCR_ENABLED", False)),
                        )
                        if isinstance(quality, dict) and quality:
                            meta["pdf_quality"] = quality
                            changed = True
                            pdf_backfilled += 1
                    finally:
                        if temp_path is not None:
                            with contextlib.suppress(Exception):
                                temp_path.unlink(missing_ok=True)

            if _backfill_page_count(
                meta, meta.get("pdf_quality") if isinstance(meta.get("pdf_quality"), dict) else None
            ):
                changed = True

            # Backfill parsed text quality (density/replace chars).
            if backfill_text_quality:
                if not isinstance(meta.get("parsed_text_quality"), dict) or not meta.get("parsed_text_quality"):
                    text: str = ""
                    rec = (
                        db.query(DocumentParsedContent.markdown_content)
                        .filter(
                            DocumentParsedContent.tenant_id == tenant_id, DocumentParsedContent.document_id == doc.id
                        )
                        .first()
                    )
                    if rec and isinstance(rec[0], str) and rec[0].strip():
                        text = rec[0]
                    else:
                        # Fallback: sample first N chunks.
                        rows = (
                            db.query(DocumentChunk.content)
                            .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == doc.id)
                            .order_by(DocumentChunk.chunk_index.asc())
                            .limit(50)
                            .all()
                        )
                        sampled = [r[0] for r in rows if r and isinstance(r[0], str) and r[0].strip()]
                        if sampled:
                            text = "\n\n".join(sampled)

                    if text.strip():
                        scored = score_parsed_text_quality(text[:200_000]).to_dict()
                        meta["parsed_text_quality"] = scored
                        changed = True
                        text_backfilled += 1

            if _backfill_language(meta):
                changed = True

            if _backfill_parse_quality(meta):
                changed = True

            # Backfill per-doc chunking stats (length distribution) for dataset profiling.
            if backfill_chunk_stats:
                existing = meta.get("chunking_stats")
                has_hist = False
                if isinstance(existing, dict):
                    has_hist = isinstance(existing.get("histogram"), list) and bool(existing.get("histogram"))
                if not has_hist:
                    rows = (
                        db.query(func.length(func.trim(DocumentChunk.content)))
                        .filter(
                            DocumentChunk.tenant_id == tenant_id,
                            DocumentChunk.document_id == doc.id,
                            DocumentChunk.disabled_at.is_(None),
                        )
                        .all()
                    )
                    lengths: list[int] = []
                    for r in rows:
                        if not r:
                            continue
                        try:
                            n = int(r[0] or 0)
                        except Exception:
                            n = 0
                        if n > 0:
                            lengths.append(n)

                    if lengths:
                        from app.services.chunking_stats_utils import compute_chunking_stats_from_lengths

                        stats = compute_chunking_stats_from_lengths(lengths, short_threshold=120, duplicate_count=0)
                        if stats:
                            meta["chunking_stats"] = stats
                            changed = True
                            chunk_stats_backfilled += 1

            # Optional: backfill token-based chunking stats (can be expensive).
            if backfill_chunk_token_stats:
                existing = meta.get("chunking_stats_tokens")
                has_hist = False
                if isinstance(existing, dict):
                    has_hist = isinstance(existing.get("histogram"), list) and bool(existing.get("histogram"))
                if not has_hist:
                    rows = (
                        db.query(DocumentChunk.content)
                        .filter(
                            DocumentChunk.tenant_id == tenant_id,
                            DocumentChunk.document_id == doc.id,
                            DocumentChunk.disabled_at.is_(None),
                        )
                        .order_by(DocumentChunk.chunk_index.asc())
                        .all()
                    )
                    texts = [r[0] for r in rows if r and isinstance(r[0], str) and r[0].strip()]
                    if texts:
                        from app.services.chunking_stats_utils import compute_chunking_stats_from_texts_tokens

                        stats = compute_chunking_stats_from_texts_tokens(texts)
                        if stats:
                            meta["chunking_stats_tokens"] = stats
                            changed = True
                            chunk_token_stats_backfilled += 1

            # Optional: backfill chunk coverage metrics (cheap; uses offsets only).
            if backfill_chunk_coverage:
                existing = meta.get("chunk_coverage")
                has_cov = isinstance(existing, dict) and (existing.get("coverage_ratio") is not None)
                total_chars = int(getattr(doc, "total_characters", 0) or 0)
                if not has_cov and total_chars > 0:
                    rows = (
                        db.query(
                            DocumentChunk.start_char,
                            DocumentChunk.end_char,
                            func.length(DocumentChunk.content),
                        )
                        .filter(
                            DocumentChunk.tenant_id == tenant_id,
                            DocumentChunk.document_id == doc.id,
                            DocumentChunk.disabled_at.is_(None),
                        )
                        .order_by(DocumentChunk.chunk_index.asc())
                        .all()
                    )
                    ranges: list[tuple[int, int]] = []
                    for r in rows:
                        if not r:
                            continue
                        s = r[0]
                        e = r[1]
                        ln = r[2]
                        if s is None:
                            continue
                        try:
                            s0 = int(s)
                        except Exception:
                            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                            continue
                        if e is None:
                            try:
                                e0 = s0 + int(ln or 0)
                            except Exception:
                                e0 = s0
                        else:
                            try:
                                e0 = int(e)
                            except Exception:
                                e0 = s0
                        if e0 > s0:
                            ranges.append((s0, e0))
                    if ranges:
                        from app.services.chunk_coverage_utils import compute_chunk_coverage_metrics_from_ranges

                        cov = compute_chunk_coverage_metrics_from_ranges(ranges, total_characters=total_chars)
                        if cov:
                            cov2 = dict(cov)
                            cov2["ranges_used"] = int(len(ranges))
                            meta["chunk_coverage"] = cov2
                            changed = True
                            chunk_coverage_backfilled += 1

            # Optional: backfill chunk quality gate (requires stats/coverage; best-effort).
            if backfill_chunk_quality_gate:
                existing = meta.get("chunk_quality_gate")
                has_gate = (
                    isinstance(existing, dict)
                    and isinstance(existing.get("grade"), str)
                    and bool(existing.get("grade"))
                )
                if not has_gate:
                    stats = meta.get("chunking_stats") if isinstance(meta.get("chunking_stats"), dict) else {}
                    cov = meta.get("chunk_coverage") if isinstance(meta.get("chunk_coverage"), dict) else {}
                    effective = (
                        meta.get("pipeline_effective") if isinstance(meta.get("pipeline_effective"), dict) else {}
                    )
                    try:
                        chunk_size = int(effective.get("chunk_size") or 0)
                    except Exception:
                        chunk_size = 0
                    try:
                        chunk_overlap = int(effective.get("chunk_overlap") or 0)
                    except Exception:
                        chunk_overlap = 0
                    if stats or cov:
                        from app.services.chunk_quality_gate import compute_chunk_quality_gate

                        gate, recs, patches = compute_chunk_quality_gate(
                            stats={
                                "count": int(stats.get("count") or 0),
                                "short_count": int(stats.get("short_count") or 0),
                                "duplicate_count": int(stats.get("duplicate_count") or 0),
                                "covered_chars": int(cov.get("covered_chars") or 0),
                                "coverage_ratio": float(cov.get("coverage_ratio") or 0.0),
                                "overlap_waste_ratio": float(cov.get("overlap_waste_ratio") or 0.0),
                                "gap_count": int(cov.get("gap_count") or 0),
                            },
                            total_chunks=int(getattr(doc, "chunk_count", 0) or 0),
                            total_characters=int(getattr(doc, "total_characters", 0) or 0),
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap,
                            original_text_included=False,
                            original_text_truncated=False,
                            original_text_max_chars=0,
                        )
                        if isinstance(gate, dict) and gate.get("grade"):
                            meta["chunk_quality_gate"] = gate
                            if recs:
                                meta["chunk_quality_recommendations"] = list(recs)[:10]
                            if patches:
                                meta["chunk_quality_patches"] = list(patches)[:10]
                            changed = True
                            chunk_quality_gate_backfilled += 1

            # Optional file hash (expensive; for exact duplicates).
            if compute_file_hash:
                sha = str(meta.get("file_sha256") or "").strip().lower()
                if not sha:
                    local_path, temp_path = _ensure_local_path(
                        tenant_id=tenant_id,
                        dataset_id=dataset_id,
                        document=doc,
                        temp_root=temp_root,
                    )
                    try:
                        meta["file_sha256"] = _safe_hash_file(local_path, algo="sha256")
                        changed = True
                        hash_backfilled += 1
                    finally:
                        if temp_path is not None:
                            with contextlib.suppress(Exception):
                                temp_path.unlink(missing_ok=True)

        except Exception as exc:  # noqa: BLE001
            errors += 1
            logger.warning("Deep scan failed for doc=%s: %s", str(getattr(doc, "id", "")), str(exc)[:200])

        if changed:
            doc.doc_metadata = meta
            updated_docs += 1
            # Commit in small batches to keep long jobs from holding large transactions.
            if updated_docs % 20 == 0:
                db.commit()

        flush_progress(idx)

    # Final commit.
    db.commit()

    run.status = "completed"
    run.progress = 100
    run.finished_at = _now_utc()
    run.updated_at = run.finished_at
    db.commit()
    # Persist summary snapshot in run (after status update so latest_scan_run reflects completion).
    summary = compute_dataset_profile_summary(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
    run.summary = summary.model_dump(mode="json")
    db.commit()

    return {
        "ok": True,
        "documents": int(total),
        "updated_docs": int(updated_docs),
        "pdf_backfilled": int(pdf_backfilled),
        "text_backfilled": int(text_backfilled),
        "chunk_stats_backfilled": int(chunk_stats_backfilled),
        "chunk_token_stats_backfilled": int(chunk_token_stats_backfilled),
        "chunk_coverage_backfilled": int(chunk_coverage_backfilled),
        "chunk_quality_gate_backfilled": int(chunk_quality_gate_backfilled),
        "hash_backfilled": int(hash_backfilled),
        "errors": int(errors),
    }
