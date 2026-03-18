"""
Enterprise-grade parsing workspace API.

Why this exists:
- `/api/v1/documents/preview` is intentionally non-persistent.
- `/parsing` UI needs persistence across restarts (upload once, keep list + parsed markdown).

This router stores:
- the original source file (local disk under uploads/{tenant}/parsing/, or MinIO when enabled)
- the parsed markdown in PostgreSQL (document_parsed_contents)

It also reuses dataset permissions for access control by placing workspace documents into a
per-user ONLY_ME dataset (auto-created on demand).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentDetail, DocumentList
from app.api.utils.upload import save_upload_file
from app.core.config import settings
from app.core.database import get_db
from app.core.env import is_production_env
from app.models.dataset import Dataset, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.document import DocumentParsedContent
from app.parsing.artifact_stats import compute_parsing_artifact_stats
from app.parsing.diagnostics import build_parse_failure_diagnostics
from app.parsing.enrich.image_caption import add_image_captions
from app.parsing.factory import parser_factory
from app.parsing.quality.competition import select_best_parse_attempt
from app.parsing.quality.document_quality import score_document_parse_quality
from app.parsing.quality.text_quality import score_parsed_text_quality
from app.parsing.subprocess_runner import SubprocessCancelled, SubprocessWorkerError, run_subprocess_worker
from app.parsing.utils.cli import resolve_cli_command
from app.rag.core.logging import get_logger
from app.services.dataset_service import DatasetService
from app.storage.object.minio import is_minio_uri, minio_service, parse_minio_uri

logger = get_logger("api.parsing")

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

# Filename validation:
# - Workspace uploads are persisted by UUID (local/MinIO), so we don't need a strict allowlist.
# - Still reject path separators / control characters to prevent path traversal and header issues.

_DETAIL_SOURCE_FILE_NOT_FOUND = "Source file not found"

POSITION_TAG_RE = re.compile(r"@@([0-9-]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##")


class ParsingContentResponse(BaseModel):
    document_id: UUID
    parser_backend: str = Field(default="auto")
    markdown_content: str = Field(default="")
    original_markdown_content: str = Field(default="")
    stats: dict[str, int] | None = Field(default=None)
    parse_duration_sec: float | None = Field(default=None)
    pdf_quality: dict[str, Any] | None = Field(default=None)
    quality_gate: ParsingQualityGate | None = Field(default=None)


class ParsingContentUpdateRequest(BaseModel):
    markdown_content: str = Field(default="")
    original_markdown_content: str | None = None


class ParsingQualityGate(BaseModel):
    """
    Unified parsing quality gate (preview/workspace).

    grade:
      - pass: looks OK
      - warn: usable but needs review/tuning
      - fail: likely broken output; best-effort fallback attempted (PDF auto only)
    """

    grade: Literal["pass", "warn", "fail"] = "pass"
    reasons: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


def _sanitize_filename(filename: str) -> str:
    """
    Return a safe filename for storage/display.

    Notes:
    - Some clients send Windows-style paths (e.g. `C:\\fakepath\\a.pdf`) in multipart metadata.
      We intentionally keep only the basename.
    - We still reject control characters to prevent header issues.
    """
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    cleaned = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Filename is required")
    if len(cleaned) > 255:
        raise HTTPException(status_code=400, detail="Filename too long (max 255 characters)")
    if "\x7f" in cleaned or any(ord(ch) < 32 for ch in cleaned):
        raise HTTPException(status_code=400, detail="Filename contains invalid characters")
    if cleaned in {".", ".."}:
        raise HTTPException(status_code=400, detail="Filename contains invalid characters")
    return cleaned


def _strip_position_tags(markdown: str) -> str:
    if not markdown:
        return ""
    return POSITION_TAG_RE.sub("", markdown)


def _grade_max(a: str, b: str) -> str:
    order = {"pass": 0, "warn": 1, "fail": 2}
    ra = order.get(str(a), 0)
    rb = order.get(str(b), 0)
    max_rank = max(ra, rb)
    if max_rank >= 2:
        return "fail"
    if max_rank >= 1:
        return "warn"
    return "pass"


def _compute_parsing_quality_gate(
    markdown: str,
    *,
    pdf_quality: dict[str, Any] | None,
    min_content_chars: int,
    is_pdf: bool,
) -> ParsingQualityGate:
    reasons: list[str] = []
    grade: str = "pass"

    text_quality = score_parsed_text_quality(markdown or "")
    evidence: dict[str, Any] = {
        "text_quality": text_quality.to_dict(),
    }
    evidence["parse_quality"] = score_document_parse_quality(
        pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
        parsed_text_quality=text_quality.to_dict(),
    )
    if is_pdf:
        evidence["min_content_chars"] = int(min_content_chars)
    if isinstance(pdf_quality, dict) and pdf_quality:
        evidence["pdf_quality"] = dict(pdf_quality)

    if not (markdown or "").strip():
        grade = "fail"
        reasons.append("empty_markdown")

    if is_pdf and int(getattr(text_quality, "content_chars", 0) or 0) < int(min_content_chars or 0):
        grade = "fail"
        reasons.append("low_content_chars")

    # Heuristic warnings (best-effort).
    if float(getattr(text_quality, "replacement_ratio", 0.0) or 0.0) >= 0.08:
        grade = _grade_max(grade, "warn")
        reasons.append("high_replacement_ratio")

    if float(getattr(text_quality, "density", 0.0) or 0.0) <= 0.12:
        grade = _grade_max(grade, "warn")
        reasons.append("low_density")

    if isinstance(pdf_quality, dict) and bool(pdf_quality.get("is_scanned", False)):
        grade = _grade_max(grade, "warn")
        reasons.append("pdf_scanned")

    # Dedup (keep order).
    seen: set[str] = set()
    uniq: list[str] = []
    for r in reasons:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(key)

    return ParsingQualityGate(grade=str(grade), reasons=uniq, evidence=evidence)


def _build_pdf_fallback_candidates() -> list[str]:
    """
    Best-effort fallback order for PDF auto parsing.

    Keep it conservative: we only include backends that appear enabled/configured.
    """
    candidates: list[str] = []

    # OCR/structured backends first (scanned/low-quality PDFs).
    if bool(getattr(settings, "MINERU_ENABLED", False)) and bool(
        getattr(settings, "MINERU_API_TOKEN", None) or getattr(settings, "MINERU_LOCAL_SERVER_URL", None)
    ):
        candidates.append("mineru")

    deepseek_ocr_ok = bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False)) and bool(
        (getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip()
    )
    if deepseek_ocr_ok:
        candidates.append("deepseek_ocr")

    etl4llm_ok = bool(getattr(settings, "ETL4LLM_ENABLED", False)) and bool(
        (getattr(settings, "ETL4LLM_API_URL", "") or "").strip()
    )
    if etl4llm_ok:
        candidates.append("etl4llm")

    if bool(getattr(settings, "DEEPDOC_ENABLED", False)):
        candidates.append("deepdoc")

    if bool(getattr(settings, "DOCLING_ENABLED", False)):
        candidates.append("docling")

    # MagicPDF is a CLI; require it to be resolvable.
    try:
        if bool(getattr(settings, "MAGIC_PDF_ENABLED", False)):
            cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
            if resolve_cli_command(cli):
                candidates.append("magicpdf")
    except Exception:
        pass

    if bool(getattr(settings, "MARKITDOWN_ENABLED", False)):
        candidates.append("markitdown")

    # Always keep a basic fallback.
    candidates.append("basic")

    # De-dup while preserving order.
    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        key = (c or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _get_or_create_workspace_dataset(db: Session, tenant_id: UUID, account_id: str) -> Dataset:
    """
    Use a per-user ONLY_ME dataset as the parsing workspace container.

    This gives us enterprise-grade access control for free (download/get/list).
    """
    # Try to find an existing dataset marked as parsing workspace for this owner.
    existing = (
        db.query(Dataset)
        .filter(Dataset.tenant_id == tenant_id, Dataset.owner_id == account_id)
        .all()
    )
    for ds in existing:
        meta = getattr(ds, "dataset_metadata", None) or {}
        if isinstance(meta, dict) and meta.get("parsing_workspace") is True:
            return ds

    # Create a new one (ONLY_ME).
    #
    # IMPORTANT:
    # Dataset names are unique per tenant, so a constant name would conflict across users
    # when auth uses dynamic account ids (e.g. smoke tests, JWT users). Use a stable
    # owner-scoped suffix to avoid collisions while keeping the name readable.
    owner_raw = str(account_id or "").strip()
    owner_tag = hashlib.sha1(owner_raw.encode("utf-8")).hexdigest()[:8] if owner_raw else "anon"
    dataset_name = f"Parsing Workspace [{owner_tag}]"

    try:
        ds = DatasetService.create_dataset(
            db=db,
            tenant_id=tenant_id,
            name=dataset_name,
            description="Auto-created for /parsing (drafts & parsed markdown)",
            permission=DatasetPermissionEnum.ONLY_ME,
            owner_id=account_id,
            partial_members=[],
        )
    except HTTPException as exc:
        # Race condition (or a pre-existing dataset created manually): if a dataset with this
        # name already exists for the same owner, re-use it instead of surfacing a 409.
        if int(getattr(exc, "status_code", 0) or 0) == 409:
            ds = (
                db.query(Dataset)
                .filter(
                    Dataset.tenant_id == tenant_id,
                    Dataset.owner_id == account_id,
                    Dataset.name == dataset_name,
                )
                .first()
            )
            if ds:
                meta = dict(getattr(ds, "dataset_metadata", None) or {})
                meta["parsing_workspace"] = True
                meta["parsing_workspace_owner_tag"] = owner_tag
                ds.dataset_metadata = meta
                db.commit()
                db.refresh(ds)
                return ds
        raise
    meta = dict(getattr(ds, "dataset_metadata", None) or {})
    meta["parsing_workspace"] = True
    meta["parsing_workspace_owner_tag"] = owner_tag
    ds.dataset_metadata = meta
    db.commit()
    db.refresh(ds)
    return ds


def _parsing_upload_dir(tenant_id: UUID) -> Path:
    return (Path(settings.UPLOAD_DIR) / str(tenant_id) / "parsing").resolve(strict=False)


def _assert_path_under_tenant_root(*, tenant_id: UUID, path: Path) -> None:
    upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
    tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
    try:
        path.resolve(strict=False).relative_to(tenant_root)
    except Exception:
        raise HTTPException(status_code=403, detail="File access denied") from None


def _get_workspace_document(db: Session, *, tenant_id: UUID, account_id: str, document_id: UUID) -> DBDocument:
    DatasetService.ensure_member(db, tenant_id, account_id)

    doc = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    meta = doc.doc_metadata or {}
    if not isinstance(meta, dict) or meta.get("workspace") != "parsing":
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, doc.dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)
    else:
        # Should not happen for workspace docs, but keep safe default.
        raise HTTPException(status_code=403, detail="Workspace access denied")

    return doc


@router.get("/documents", response_model=DocumentList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_parsing_documents(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    status: str | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    List parsing workspace documents (persistent across restarts).
    """
    dataset = _get_or_create_workspace_dataset(db, tenant_id, account_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    query = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset.id,
        )
    )

    if status and status != "all":
        query = query.filter(DBDocument.status == status)

    total = query.count()
    items = query.order_by(DBDocument.created_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "items": items}


@router.post("/documents", response_model=DocumentDetail, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def upload_parsing_document(
    file: Annotated[UploadFile, File(...)],
    parser_backend: Annotated[str, Form()] = "auto",
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Upload a source file into the parsing workspace (no parsing yet).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    file.filename = _sanitize_filename(file.filename)

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}")

    dataset = _get_or_create_workspace_dataset(db, tenant_id, account_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    document_id = uuid.uuid4()

    use_object_storage = bool(getattr(settings, "MINIO_ENABLED", False)) and bool(
        getattr(settings, "MINIO_DOCUMENTS_ENABLED", False)
    )

    if use_object_storage:
        upload_dir = (Path(settings.UPLOAD_DIR) / str(tenant_id) / ".tmp").resolve(strict=False)
    else:
        upload_dir = _parsing_upload_dir(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    source_path = upload_dir / f"{document_id}{file_ext}"

    try:
        file_size = int(await save_upload_file(file, source_path, max_bytes=settings.MAX_FILE_SIZE) or 0)
    except HTTPException:
        raise

    if not use_object_storage:
        _assert_path_under_tenant_root(tenant_id=tenant_id, path=source_path)

    meta = {
        "workspace": "parsing",
        "parser_backend_requested": (parser_backend or "").strip().lower() or "auto",
    }

    stored_path = str(source_path)
    if use_object_storage:
        try:
            stored_path = minio_service.upload_document_file(
                file_path=source_path,
                tenant_id=str(tenant_id),
                dataset_id=str(dataset.id),
                document_id=str(document_id),
                extension=file_ext,
                content_type=(file.content_type or "application/octet-stream"),
            )
        finally:
            with contextlib.suppress(Exception):
                source_path.unlink(missing_ok=True)

    doc = DBDocument(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        filename=file.filename,
        file_type=file_ext.lstrip("."),
        file_size=file_size,
        file_path=stored_path,
        status="pending",
        processing_progress=0,
        current_stage="parsing",
        doc_metadata=meta,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.post("/documents/{document_id}/parse", response_model=ParsingContentResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def parse_workspace_document(
    document_id: uuid.UUID,
    request: Request,
    parser_backend: str | None = None,
    image_caption_enabled: Annotated[bool, Query()] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Parse a previously uploaded workspace document and persist markdown.
    """
    doc = _get_workspace_document(db, tenant_id=tenant_id, account_id=account_id, document_id=document_id)
    ds = DatasetService.get_dataset(db, tenant_id, doc.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    raw_path = str(doc.file_path or "").strip()
    if not raw_path or raw_path.startswith("manual://"):
        raise HTTPException(status_code=404, detail="Source file not available")

    temp_path: Path | None = None
    if is_minio_uri(raw_path):
        if not bool(getattr(settings, "MINIO_ENABLED", False)):
            raise HTTPException(status_code=503, detail="Object storage is disabled")
        try:
            ref = parse_minio_uri(raw_path)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=_DETAIL_SOURCE_FILE_NOT_FOUND) from exc
        if ref.bucket != str(getattr(settings, "MINIO_BUCKET_NAME", "")):
            raise HTTPException(status_code=403, detail="Source file access denied")

        dataset_id = str(doc.dataset_id) if doc.dataset_id else str(tenant_id)
        expected_object = minio_service.build_document_object_name(
            tenant_id=str(tenant_id),
            dataset_id=dataset_id,
            document_id=str(doc.id),
            extension=f".{(doc.file_type or '').lower()}",
        )
        if ref.object_name != expected_object:
            raise HTTPException(status_code=403, detail="Source file access denied")

        try:
            minio_service.stat_object(object_name=ref.object_name)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=_DETAIL_SOURCE_FILE_NOT_FOUND) from exc

        temp_dir = (Path(settings.UPLOAD_DIR) / str(tenant_id) / ".tmp").resolve(strict=False)
        suffix = f".{(doc.file_type or '').lower()}"
        temp_path = temp_dir / f"{doc.id}.{uuid.uuid4().hex}{suffix}"
        await asyncio.to_thread(
            minio_service.download_object_to_path,
            object_name=ref.object_name,
            destination=temp_path,
            max_bytes=int(getattr(settings, "MAX_FILE_SIZE", 0) or 0),
        )
        source_path = temp_path
    else:
        source_path = Path(raw_path).resolve(strict=False)
        _assert_path_under_tenant_root(tenant_id=tenant_id, path=source_path)
        if not source_path.exists() or not source_path.is_file():
            raise HTTPException(status_code=404, detail=_DETAIL_SOURCE_FILE_NOT_FOUND)

    doc.status = "processing"
    doc.processing_progress = 0
    doc.current_stage = "parsing"
    doc.error_message = None
    db.commit()
    db.refresh(doc)

    # Resolve parser backend (validate early).
    meta = doc.doc_metadata or {}
    requested_backend = (parser_backend or meta.get("parser_backend_requested") or "auto") if isinstance(meta, dict) else (parser_backend or "auto")
    requested_backend = str(requested_backend or "").strip().lower() or "auto"
    file_ext = f".{(doc.file_type or '').lower()}"
    try:
        if file_ext == ".pdf" and requested_backend in {"", "auto"}:
            resolved_backend = "auto"
        else:
            resolved_backend = parser_factory.resolve_backend(file_ext, requested_backend)
    except ValueError as exc:
        doc.status = "failed"
        doc.processing_progress = 0
        doc.current_stage = "failed"
        doc.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        t0 = time.perf_counter()

        def _extract_markdown(parsed_obj: dict) -> tuple[str, str]:
            docs = [
                str(item.get("page_content") or "")
                for item in (parsed_obj.get("documents") or [])
                if isinstance(item, dict)
            ]
            original = "\n\n".join(docs).strip()
            cleaned = _strip_position_tags(original).strip()
            return original, cleaned

        parsed = await run_subprocess_worker(
            tenant_id=tenant_id,
            payload={
                "action": "parse_documents",
                "tenant_id": str(tenant_id),
                "file_path": str(source_path),
                "parser_backend": resolved_backend,
                "mode": "preview",
            },
            disconnect_check=request.is_disconnected,
            timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
        )
        resolved_backend = str(parsed.get("resolved_backend") or resolved_backend)

        pdf_quality = parsed.get("pdf_quality") if isinstance(parsed.get("pdf_quality"), dict) else None
        artifact_docs = parsed.get("documents") if isinstance(parsed, dict) else None
        original_markdown, markdown = _extract_markdown(parsed if isinstance(parsed, dict) else {})

        captions_added = 0
        if bool(image_caption_enabled):
            # Never fail the parsing request due to optional enrichment.
            try:
                markdown, captions_added = add_image_captions(markdown)
            except Exception:
                captions_added = 0

        min_chars = max(0, int(getattr(settings, "PARSE_FALLBACK_MIN_CONTENT_CHARS", 120) or 120))
        max_retries = max(0, int(getattr(settings, "PARSE_FALLBACK_MAX_RETRIES", 1) or 1))

        gate = _compute_parsing_quality_gate(
            markdown,
            pdf_quality=pdf_quality,
            min_content_chars=min_chars,
            is_pdf=(file_ext == ".pdf"),
        )
        initial_backend = resolved_backend

        # Best-effort PDF fallback for auto parsing in workspace (interactive; safe bounded retries).
        fallback_attempts: list[dict[str, Any]] = []
        attempt_candidates: list[dict[str, Any]] = [
            {
                "backend": resolved_backend,
                "grade": gate.grade,
                "parse_score": ((gate.evidence or {}).get("parse_quality") or {}).get("score"),
                "content_chars": ((gate.evidence or {}).get("text_quality") or {}).get("content_chars"),
                "artifact_docs": artifact_docs,
                "original_markdown": original_markdown,
                "markdown": markdown,
                "gate": gate,
            }
        ]
        if file_ext == ".pdf" and requested_backend in {"", "auto"} and gate.grade == "fail" and max_retries > 0:
            candidates = _build_pdf_fallback_candidates()
            filtered = [c for c in candidates if c != (resolved_backend or "").strip().lower()]
            retries_left = int(max_retries)

            for candidate in filtered:
                if retries_left <= 0:
                    break
                retries_left -= 1

                try:
                    cand_backend = parser_factory.resolve_backend(file_ext, candidate)
                except Exception as exc:  # noqa: BLE001
                    fallback_attempts.append(
                        {
                            "from": resolved_backend,
                            "to": candidate,
                            "accepted": False,
                            "error": f"invalid_backend:{str(exc)[:120]}",
                        }
                    )
                    continue

                try:
                    alt_parsed = await run_subprocess_worker(
                        tenant_id=tenant_id,
                        payload={
                            "action": "parse_documents",
                            "tenant_id": str(tenant_id),
                            "file_path": str(source_path),
                            "parser_backend": cand_backend,
                            "mode": "preview",
                            # Reuse initial quality scoring if present to avoid extra pdfplumber work.
                            "pdf_quality": dict(pdf_quality) if isinstance(pdf_quality, dict) else None,
                        },
                        disconnect_check=request.is_disconnected,
                        timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
                    )
                except Exception as exc:  # noqa: BLE001
                    fallback_attempts.append(
                        {
                            "from": resolved_backend,
                            "to": cand_backend,
                            "accepted": False,
                            "error": str(exc)[:200],
                        }
                    )
                    continue

                alt_backend = str(alt_parsed.get("resolved_backend") or cand_backend)
                alt_original, alt_markdown = _extract_markdown(alt_parsed if isinstance(alt_parsed, dict) else {})
                alt_gate = _compute_parsing_quality_gate(
                    alt_markdown,
                    pdf_quality=pdf_quality,
                    min_content_chars=min_chars,
                    is_pdf=True,
                )

                attempt: dict[str, Any] = {
                    "from": initial_backend,
                    "to": alt_backend,
                    "quality_before": gate.evidence.get("text_quality"),
                    "quality_after": alt_gate.evidence.get("text_quality"),
                    "grade_before": gate.grade,
                    "grade_after": alt_gate.grade,
                    "parse_score_before": ((gate.evidence or {}).get("parse_quality") or {}).get("score"),
                    "parse_score_after": ((alt_gate.evidence or {}).get("parse_quality") or {}).get("score"),
                    "accepted": alt_gate.grade != "fail",
                }
                fallback_attempts.append(attempt)

                attempt_candidates.append(
                    {
                        "backend": alt_backend,
                        "grade": alt_gate.grade,
                        "parse_score": ((alt_gate.evidence or {}).get("parse_quality") or {}).get("score"),
                        "content_chars": ((alt_gate.evidence or {}).get("text_quality") or {}).get("content_chars"),
                        "artifact_docs": alt_parsed.get("documents") if isinstance(alt_parsed, dict) else None,
                        "original_markdown": alt_original,
                        "markdown": alt_markdown,
                        "gate": alt_gate,
                    }
                )

        if len(attempt_candidates) > 1:
            try:
                best = select_best_parse_attempt(attempt_candidates)
            except Exception:
                best = attempt_candidates[0]

            selected_backend = str(best.get("backend") or "").strip() or resolved_backend
            resolved_backend = selected_backend
            gate = best.get("gate") or gate
            artifact_docs = best.get("artifact_docs") if best.get("artifact_docs") is not None else artifact_docs
            original_markdown = str(best.get("original_markdown") or original_markdown)
            markdown = str(best.get("markdown") or markdown)

            for it in fallback_attempts:
                try:
                    it["selected"] = str(it.get("to") or "") == selected_backend
                except Exception:
                    it["selected"] = False

        if fallback_attempts:
            gate = ParsingQualityGate(
                grade=gate.grade,
                reasons=list(gate.reasons or []),
                evidence={
                    **(gate.evidence or {}),
                    "fallback_attempts": fallback_attempts,
                    "fallback_initial_backend": initial_backend,
                    "fallback_final_backend": resolved_backend,
                    "fallback_selected_backend": resolved_backend,
                    "fallback_max_retries": int(max_retries),
                },
            )

        duration_sec = max(0.0, time.perf_counter() - t0)
        artifact_stats = compute_parsing_artifact_stats(
            documents=artifact_docs,
            original_markdown=original_markdown,
            pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
        )

        # Upsert parsed content.
        existing = (
            db.query(DocumentParsedContent)
            .filter(DocumentParsedContent.document_id == doc.id, DocumentParsedContent.tenant_id == tenant_id)
            .first()
        )
        if existing:
            existing.markdown_content = markdown
            existing.original_markdown_content = original_markdown
        else:
            db.add(
                DocumentParsedContent(
                    tenant_id=tenant_id,
                    document_id=doc.id,
                    markdown_content=markdown,
                    original_markdown_content=original_markdown,
                )
            )

        doc.total_characters = len(markdown)
        doc.chunk_count = 0
        doc.status = "completed"
        doc.processing_progress = 100
        doc.current_stage = "completed"
        doc.error_message = None

        next_meta = dict(meta) if isinstance(meta, dict) else {}
        next_meta["workspace"] = "parsing"
        next_meta["parser_backend_requested"] = requested_backend
        next_meta["parser_backend"] = resolved_backend
        next_meta["image_caption_enabled"] = bool(image_caption_enabled)
        if bool(image_caption_enabled):
            next_meta["image_captions_added"] = int(captions_added)
        if isinstance(pdf_quality, dict) and pdf_quality:
            next_meta["pdf_quality"] = dict(pdf_quality)
        if gate is not None:
            next_meta["quality_gate"] = gate.model_dump()
        next_meta["parsed_at"] = datetime.now(UTC).isoformat()
        next_meta["parse_duration_sec"] = round(float(duration_sec), 3)
        if fallback_attempts:
            next_meta["parse_fallback"] = {
                "attempts": fallback_attempts,
                "min_content_chars": int(min_chars),
                "max_retries": int(max_retries),
            }
        next_meta.update(artifact_stats)
        doc.doc_metadata = next_meta

        db.commit()
        db.refresh(doc)

        return ParsingContentResponse(
            document_id=doc.id,
            parser_backend=resolved_backend,
            markdown_content=markdown,
            original_markdown_content=original_markdown,
            stats=artifact_stats,
            parse_duration_sec=round(float(duration_sec), 3),
            pdf_quality=(dict(pdf_quality) if isinstance(pdf_quality, dict) else None),
            quality_gate=gate,
        )
    except SubprocessCancelled:
        # Client disconnected; stop work early.
        doc.status = "failed"
        doc.processing_progress = 0
        doc.current_stage = "failed"
        doc.error_message = "client_disconnected"
        db.commit()
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as exc:
        err_type = (exc.details or {}).get("type")
        msg = (str(exc) or "").strip()
        if not msg:
            details = exc.details or {}
            msg = str(details.get("message") or details.get("type") or exc.__class__.__name__).strip()
        msg = msg[:200]
        logger.error("Subprocess worker failed during workspace parse: %s", msg)
        doc.status = "failed"
        doc.processing_progress = 0
        doc.current_stage = "failed"
        doc.error_message = msg
        diagnostics: dict[str, Any] = {}
        try:
            diagnostics = build_parse_failure_diagnostics(
                file_path=Path(str(source_path)),
                file_ext=str(file_ext),
                parser_backend_requested=str(requested_backend),
                parser_backend_resolved=str(resolved_backend),
                error_type=str(err_type or ""),
                error_message=str(msg),
            )
        except Exception:
            diagnostics = {}
        try:
            meta0 = doc.doc_metadata if isinstance(doc.doc_metadata, dict) else {}
            next_meta = dict(meta0)
            if diagnostics:
                next_meta["parse_diagnostics"] = diagnostics
            doc.doc_metadata = next_meta
        except Exception:
            pass
        db.commit()
        status_code = 400 if err_type == "ValueError" else 500
        prefix = "Invalid input" if status_code == 400 else "Failed to parse document"
        detail_msg = prefix if is_production_env() else f"{prefix}: {msg}"
        raise HTTPException(
            status_code=status_code,
            detail={"message": detail_msg, "diagnostics": diagnostics},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        msg = (str(exc) or "").strip()
        if not msg:
            msg = exc.__class__.__name__
        msg = msg[:200]
        logger.error("Unexpected error during workspace parse: %s", msg)
        doc.status = "failed"
        doc.processing_progress = 0
        doc.current_stage = "failed"
        doc.error_message = msg
        diagnostics: dict[str, Any] = {}
        try:
            diagnostics = build_parse_failure_diagnostics(
                file_path=Path(str(source_path)),
                file_ext=str(file_ext),
                parser_backend_requested=str(requested_backend),
                parser_backend_resolved=str(resolved_backend),
                error_type=str(exc.__class__.__name__),
                error_message=str(msg),
            )
        except Exception:
            diagnostics = {}
        try:
            meta0 = doc.doc_metadata if isinstance(doc.doc_metadata, dict) else {}
            next_meta = dict(meta0)
            if diagnostics:
                next_meta["parse_diagnostics"] = diagnostics
            doc.doc_metadata = next_meta
        except Exception:
            pass
        db.commit()
        detail_msg = "Failed to parse document" if is_production_env() else f"Failed to parse document: {msg}"
        raise HTTPException(
            status_code=500,
            detail={"message": detail_msg, "diagnostics": diagnostics},
        ) from exc
    finally:
        if temp_path is not None:
            with contextlib.suppress(Exception):
                temp_path.unlink(missing_ok=True)


@router.get("/documents/{document_id}/content", response_model=ParsingContentResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_parsing_content(
    document_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    doc = _get_workspace_document(db, tenant_id=tenant_id, account_id=account_id, document_id=document_id)
    meta = doc.doc_metadata or {}
    parser_backend = ""
    duration_sec: float | None = None
    stats: dict[str, int] | None = None
    if isinstance(meta, dict):
        parser_backend = str(meta.get("parser_backend") or meta.get("parser_backend_requested") or "auto")
        raw_duration = meta.get("parse_duration_sec")
        try:
            if raw_duration is not None:
                duration_sec = float(raw_duration)
        except Exception:
            duration_sec = None
        stats = {
            "page_count": int(meta.get("page_count") or 0),
            "table_count": int(meta.get("table_count") or 0),
            "image_count": int(meta.get("image_count") or 0),
            "block_count": int(meta.get("block_count") or 0),
        }

    row = (
        db.query(DocumentParsedContent)
        .filter(DocumentParsedContent.document_id == doc.id, DocumentParsedContent.tenant_id == tenant_id)
        .first()
    )
    pdf_quality = meta.get("pdf_quality") if isinstance(meta, dict) else None
    quality_gate = meta.get("quality_gate") if isinstance(meta, dict) else None
    return ParsingContentResponse(
        document_id=doc.id,
        parser_backend=str(parser_backend or "auto"),
        markdown_content=(row.markdown_content if row else ""),
        original_markdown_content=(row.original_markdown_content if row else ""),
        stats=stats,
        parse_duration_sec=duration_sec,
        pdf_quality=(dict(pdf_quality) if isinstance(pdf_quality, dict) else None),
        quality_gate=(ParsingQualityGate(**quality_gate) if isinstance(quality_gate, dict) else None),
    )


@router.patch("/documents/{document_id}/content", response_model=ParsingContentResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def update_parsing_content(
    document_id: uuid.UUID,
    payload: ParsingContentUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    doc = _get_workspace_document(db, tenant_id=tenant_id, account_id=account_id, document_id=document_id)
    ds = DatasetService.get_dataset(db, tenant_id, doc.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    markdown = str(payload.markdown_content or "")
    original = payload.original_markdown_content
    if original is None:
        # Keep original if not explicitly provided.
        row_existing = (
            db.query(DocumentParsedContent)
            .filter(DocumentParsedContent.document_id == doc.id, DocumentParsedContent.tenant_id == tenant_id)
            .first()
        )
        original = row_existing.original_markdown_content if row_existing else markdown
    else:
        original = str(original or "")

    row = (
        db.query(DocumentParsedContent)
        .filter(DocumentParsedContent.document_id == doc.id, DocumentParsedContent.tenant_id == tenant_id)
        .first()
    )
    if row:
        row.markdown_content = markdown
        row.original_markdown_content = original
    else:
        db.add(
            DocumentParsedContent(
                tenant_id=tenant_id,
                document_id=doc.id,
                markdown_content=markdown,
                original_markdown_content=original,
            )
        )

    doc.total_characters = len(markdown)
    doc.status = "completed"
    doc.processing_progress = 100
    doc.current_stage = "completed"

    meta = doc.doc_metadata or {}
    next_meta = dict(meta) if isinstance(meta, dict) else {}
    next_meta["workspace"] = "parsing"
    next_meta["edited"] = True
    doc.doc_metadata = next_meta

    db.commit()
    db.refresh(doc)

    parser_backend = "auto"
    duration_sec: float | None = None
    if isinstance(next_meta, dict):
        parser_backend = str(next_meta.get("parser_backend") or next_meta.get("parser_backend_requested") or "auto")
        raw_duration = next_meta.get("parse_duration_sec")
        try:
            if raw_duration is not None:
                duration_sec = float(raw_duration)
        except Exception:
            duration_sec = None

    return ParsingContentResponse(
        document_id=doc.id,
        parser_backend=parser_backend,
        markdown_content=markdown,
        original_markdown_content=original,
        parse_duration_sec=duration_sec,
    )


@router.delete("/documents/{document_id}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def delete_parsing_document(
    document_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    doc = _get_workspace_document(db, tenant_id=tenant_id, account_id=account_id, document_id=document_id)
    ds = DatasetService.get_dataset(db, tenant_id, doc.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    # Best-effort delete source file.
    with contextlib.suppress(Exception):
        raw_path = str(doc.file_path or "").strip()
        if raw_path and not raw_path.startswith("manual://"):
            if is_minio_uri(raw_path):
                if bool(getattr(settings, "MINIO_ENABLED", False)):
                    ref = parse_minio_uri(raw_path)
                    if ref.bucket == str(getattr(settings, "MINIO_BUCKET_NAME", "")):
                        dataset_id = str(doc.dataset_id) if doc.dataset_id else str(tenant_id)
                        expected_object = minio_service.build_document_object_name(
                            tenant_id=str(tenant_id),
                            dataset_id=dataset_id,
                            document_id=str(doc.id),
                            extension=f".{(doc.file_type or '').lower()}",
                        )
                        if ref.object_name == expected_object:
                            minio_service.delete_object(object_name=ref.object_name)
            else:
                file_path = Path(raw_path).resolve(strict=False)
                _assert_path_under_tenant_root(tenant_id=tenant_id, path=file_path)
                if file_path.exists() and file_path.is_file():
                    file_path.unlink()

    db.delete(doc)
    db.commit()
    return None
