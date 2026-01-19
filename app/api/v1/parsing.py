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
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentDetail, DocumentList
from app.api.utils.upload import save_upload_file
from app.core.config import settings
from app.core.database import get_db
from app.models.dataset import Dataset, DatasetPermissionEnum
from app.models.document import Document as DBDocument, DocumentParsedContent
from app.parsing.factory import parser_factory
from app.parsing.subprocess_runner import SubprocessCancelled, SubprocessWorkerError, run_subprocess_worker
from app.services.dataset_service import DatasetService
from app.storage.object.minio import is_minio_uri, minio_service, parse_minio_uri
from app.rag.core.logging import get_logger

logger = get_logger("api.parsing")

router = APIRouter()

# Safe filename characters: letters, digits, CJK, spaces, dots, underscores, hyphens.
SAFE_FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af._\-\s]+$")

POSITION_TAG_RE = re.compile(r"@@([0-9-]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##")


class ParsingContentResponse(BaseModel):
    document_id: UUID
    parser_backend: str = Field(default="auto")
    markdown_content: str = Field(default="")
    original_markdown_content: str = Field(default="")


class ParsingContentUpdateRequest(BaseModel):
    markdown_content: str = Field(default="")
    original_markdown_content: Optional[str] = None


def _validate_filename(filename: str) -> None:
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    if len(filename) > 255:
        raise HTTPException(status_code=400, detail="Filename too long (max 255 characters)")
    if not SAFE_FILENAME_PATTERN.match(filename):
        raise HTTPException(status_code=400, detail="Filename contains invalid characters")


def _strip_position_tags(markdown: str) -> str:
    if not markdown:
        return ""
    return POSITION_TAG_RE.sub("", markdown)


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
    ds = DatasetService.create_dataset(
        db=db,
        tenant_id=tenant_id,
        name="Parsing Workspace",
        description="Auto-created for /parsing (drafts & parsed markdown)",
        permission=DatasetPermissionEnum.ONLY_ME,
        owner_id=account_id,
        partial_members=[],
    )
    meta = dict(getattr(ds, "dataset_metadata", None) or {})
    meta["parsing_workspace"] = True
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
        raise HTTPException(status_code=403, detail="File access denied")


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


@router.get("/documents", response_model=DocumentList)
async def list_parsing_documents(
    skip: int = 0,
    limit: int = 200,
    status: Optional[str] = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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


@router.post("/documents", response_model=DocumentDetail, status_code=201)
async def upload_parsing_document(
    file: UploadFile = File(...),
    parser_backend: str = Form(default="auto"),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Upload a source file into the parsing workspace (no parsing yet).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    _validate_filename(file.filename)

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


@router.post("/documents/{document_id}/parse", response_model=ParsingContentResponse)
async def parse_workspace_document(
    document_id: uuid.UUID,
    request: Request,
    parser_backend: Optional[str] = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
        except ValueError:
            raise HTTPException(status_code=404, detail="Source file not found")
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
        except Exception:
            raise HTTPException(status_code=404, detail="Source file not found")

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
            raise HTTPException(status_code=404, detail="Source file not found")

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
        raise HTTPException(status_code=400, detail=str(exc))

    try:
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
        documents = [
            str(item.get("page_content") or "")
            for item in (parsed.get("documents") or [])
            if isinstance(item, dict)
        ]
        resolved_backend = str(parsed.get("resolved_backend") or resolved_backend)

        original_markdown = "\n\n".join(documents).strip()
        markdown = _strip_position_tags(original_markdown).strip()

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
        next_meta["parsed_at"] = datetime.now(timezone.utc).isoformat()
        doc.doc_metadata = next_meta

        db.commit()
        db.refresh(doc)

        return ParsingContentResponse(
            document_id=doc.id,
            parser_backend=resolved_backend,
            markdown_content=markdown,
            original_markdown_content=original_markdown,
        )
    except SubprocessCancelled:
        # Client disconnected; stop work early.
        doc.status = "failed"
        doc.processing_progress = 0
        doc.current_stage = "failed"
        doc.error_message = "client_disconnected"
        db.commit()
        raise HTTPException(status_code=499, detail="Client closed request")
    except SubprocessWorkerError as exc:
        msg = str(exc)[:200]
        logger.error("Subprocess worker failed during workspace parse: %s", msg)
        doc.status = "failed"
        doc.processing_progress = 0
        doc.current_stage = "failed"
        doc.error_message = msg
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to parse document")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)[:200]
        logger.error("Unexpected error during workspace parse: %s", msg)
        doc.status = "failed"
        doc.processing_progress = 0
        doc.current_stage = "failed"
        doc.error_message = msg
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to parse document")
    finally:
        if temp_path is not None:
            with contextlib.suppress(Exception):
                temp_path.unlink(missing_ok=True)


@router.get("/documents/{document_id}/content", response_model=ParsingContentResponse)
async def get_parsing_content(
    document_id: uuid.UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    doc = _get_workspace_document(db, tenant_id=tenant_id, account_id=account_id, document_id=document_id)
    meta = doc.doc_metadata or {}
    parser_backend = ""
    if isinstance(meta, dict):
        parser_backend = str(meta.get("parser_backend") or meta.get("parser_backend_requested") or "auto")

    row = (
        db.query(DocumentParsedContent)
        .filter(DocumentParsedContent.document_id == doc.id, DocumentParsedContent.tenant_id == tenant_id)
        .first()
    )
    return ParsingContentResponse(
        document_id=doc.id,
        parser_backend=str(parser_backend or "auto"),
        markdown_content=(row.markdown_content if row else ""),
        original_markdown_content=(row.original_markdown_content if row else ""),
    )


@router.patch("/documents/{document_id}/content", response_model=ParsingContentResponse)
async def update_parsing_content(
    document_id: uuid.UUID,
    payload: ParsingContentUpdateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
    if isinstance(next_meta, dict):
        parser_backend = str(next_meta.get("parser_backend") or next_meta.get("parser_backend_requested") or "auto")

    return ParsingContentResponse(
        document_id=doc.id,
        parser_backend=parser_backend,
        markdown_content=markdown,
        original_markdown_content=original,
    )


@router.delete("/documents/{document_id}", status_code=204)
async def delete_parsing_document(
    document_id: uuid.UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
