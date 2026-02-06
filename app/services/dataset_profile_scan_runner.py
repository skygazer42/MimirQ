"""
Deep dataset profile scan runner.

This performs best-effort *backfills* for missing per-document metrics so that
the dataset profile summary and drill-down pages are more complete.

It is intended to run as a background job (arq worker) but can also run inline
when TASK_QUEUE_ENABLED=false.
"""

from __future__ import annotations

import contextlib
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

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
from app.storage.object.minio import is_minio_uri, minio_service, parse_minio_uri

logger = get_logger("services.dataset_profile_scan")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_hash_file(path: Path, *, algo: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _download_minio_document_to_temp(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    document: DBDocument,
    temp_dir: Path,
) -> Path:
    """
    Download a document stored in MinIO to a local temp path.

    Security:
    - verify bucket matches settings
    - verify object key matches expected naming scheme for the tenant/dataset/doc
    """
    raw_path = str(getattr(document, "file_path", "") or "").strip()
    ref = parse_minio_uri(raw_path)
    if ref.bucket != str(getattr(settings, "MINIO_BUCKET_NAME", "")):
        raise ValueError("object_bucket_denied")

    expected = minio_service.build_document_object_name(
        tenant_id=str(tenant_id),
        dataset_id=str(dataset_id),
        document_id=str(document.id),
        extension=f".{(document.file_type or '').lower()}",
    )
    if ref.object_name != expected:
        raise ValueError("object_key_denied")

    suffix = f".{(document.file_type or '').lower()}" if str(getattr(document, "file_type", "") or "").strip() else ""
    temp_dir.mkdir(parents=True, exist_ok=True)
    out = temp_dir / f"{str(document.id)}{suffix}"
    minio_service.download_object_to_path(
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
) -> tuple[Path, Optional[Path]]:
    """
    Return (local_path, temp_path_if_downloaded).
    """
    raw = str(getattr(document, "file_path", "") or "").strip()
    if not raw or raw.startswith("manual://"):
        raise ValueError("document_file_not_available")

    if is_minio_uri(raw):
        if not bool(getattr(settings, "MINIO_ENABLED", False)):
            raise ValueError("object_storage_disabled")
        temp_dir = (temp_root / str(tenant_id) / ".tmp").resolve(strict=False)
        temp_path = _download_minio_document_to_temp(
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
    run.error_message = None
    db.commit()

    cfg = dict(getattr(run, "config", None) or {})
    backfill_pdf_quality = bool(cfg.get("backfill_pdf_quality", True))
    backfill_text_quality = bool(cfg.get("backfill_text_quality", True))
    compute_file_hash = bool(cfg.get("compute_file_hash", False))
    max_docs_raw = cfg.get("max_documents")
    max_documents = int(max_docs_raw) if isinstance(max_docs_raw, (int, float)) and int(max_docs_raw) > 0 else None

    _dataset, query = build_dataset_documents_query(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)

    # Only fetch fields we need; keep the ORM objects for metadata updates.
    docs = (
        query.order_by(DBDocument.created_at.asc(), DBDocument.id.asc())
        .limit(max_documents) if max_documents else query.order_by(DBDocument.created_at.asc(), DBDocument.id.asc())
    ).all()

    total = len(docs)
    if total == 0:
        run.status = "completed"
        run.progress = 100
        run.finished_at = _now_utc()
        db.commit()
        summary = compute_dataset_profile_summary(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
        run.summary = summary.model_dump()
        db.commit()
        return {"ok": True, "documents": 0}

    temp_root = Path(getattr(settings, "UPLOAD_DIR", "./uploads") or "./uploads")
    updated_docs = 0
    pdf_backfilled = 0
    text_backfilled = 0
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
                        quality = score_pdf_quality(local_path, sample_pages=3, use_ocr_validation=bool(getattr(settings, "RAPIDOCR_ENABLED", False)))
                        if isinstance(quality, dict) and quality:
                            meta["pdf_quality"] = quality
                            changed = True
                            pdf_backfilled += 1
                    finally:
                        if temp_path is not None:
                            with contextlib.suppress(Exception):
                                temp_path.unlink(missing_ok=True)

            # Backfill parsed text quality (density/replace chars).
            if backfill_text_quality:
                if not isinstance(meta.get("parsed_text_quality"), dict) or not meta.get("parsed_text_quality"):
                    text: str = ""
                    rec = (
                        db.query(DocumentParsedContent.markdown_content)
                        .filter(DocumentParsedContent.tenant_id == tenant_id, DocumentParsedContent.document_id == doc.id)
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

            if _backfill_parse_quality(meta):
                changed = True

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
    db.commit()
    # Persist summary snapshot in run (after status update so latest_scan_run reflects completion).
    summary = compute_dataset_profile_summary(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
    run.summary = summary.model_dump()
    db.commit()

    return {
        "ok": True,
        "documents": int(total),
        "updated_docs": int(updated_docs),
        "pdf_backfilled": int(pdf_backfilled),
        "text_backfilled": int(text_backfilled),
        "hash_backfilled": int(hash_backfilled),
        "errors": int(errors),
    }
