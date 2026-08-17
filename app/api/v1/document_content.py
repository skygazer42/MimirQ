import uuid
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentParsedContentResponse
from app.api.utils.response_headers import file_response_headers
from app.core.config import settings
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentParsedContent
from app.parsing.factory import ParserFactory
from app.parsing.output import markdown_to_blocks, render_clean_docx_bytes
from app.services.dataset_service import DatasetService
from app.services.document_access_service import assert_document_acl_readable
from app.services.path_safety import resolve_under_base

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

DOC_NOT_FOUND_DETAIL = "Document not found"

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_TEXT_SOURCE_FALLBACK_EXTENSIONS = frozenset(ParserFactory.PLAIN_TEXT_EXTENSIONS | {".md", ".markdown"})
_TEXT_SOURCE_FALLBACK_MAX_BYTES = 8_000_000


def _normalize_document_ext(value: object) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw.startswith("."):
        return raw
    return f".{raw.lstrip('.')}"


def _document_text_source_ext(document: DBDocument) -> str:
    file_type_ext = _normalize_document_ext(getattr(document, "file_type", ""))
    if file_type_ext in _TEXT_SOURCE_FALLBACK_EXTENSIONS:
        return file_type_ext

    for raw_path in (getattr(document, "filename", ""), getattr(document, "file_path", "")):
        ext = Path(str(raw_path or "")).suffix.lower()
        if ext in _TEXT_SOURCE_FALLBACK_EXTENSIONS:
            return ext
    return ""


def _read_local_text_source_fallback(
    document: DBDocument,
    *,
    tenant_id: UUID,
    max_chars: int,
) -> tuple[str, bool] | None:
    if not _document_text_source_ext(document):
        return None

    raw_path = str(getattr(document, "file_path", "") or "").strip()
    if not raw_path or raw_path.startswith("manual://"):
        return None

    path = Path(raw_path)
    upload_root = Path(getattr(settings, "UPLOAD_DIR", "./uploads") or "./uploads")
    safe_path = resolve_under_base(path, base=upload_root / str(tenant_id))
    if safe_path is None or not safe_path.exists() or not safe_path.is_file():
        return None

    char_limit = int(max_chars or 0)
    byte_limit = (char_limit * 4 + 4) if char_limit > 0 else _TEXT_SOURCE_FALLBACK_MAX_BYTES
    try:
        with safe_path.open("rb") as fh:
            raw = fh.read(byte_limit)
        source_size = safe_path.stat().st_size
    except OSError:
        return None

    text = raw.decode("utf-8-sig", errors="replace")
    truncated = source_size > len(raw)
    if char_limit > 0 and len(text) > char_limit:
        text = text[:char_limit]
        truncated = True
    return text, truncated


def _resolve_document_dataset_for_access(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document: DBDocument,
) -> Dataset | None:
    dataset: Dataset | None = None
    if getattr(document, "dataset_id", None):
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
    return dataset


def _document_parsed_content_meta(document: DBDocument) -> dict[str, Any]:
    doc_meta = getattr(document, "doc_metadata", None) or {}
    persisted_meta = doc_meta.get("parsed_content_persisted") if isinstance(doc_meta, dict) else None
    if not isinstance(persisted_meta, dict):
        persisted = {}
    else:
        persisted = dict(persisted_meta)
    if isinstance(doc_meta, dict):
        for key in ("parser_backend", "parser_backend_requested", "parse_duration_sec", "elements"):
            if key in doc_meta and key not in persisted:
                persisted[key] = doc_meta[key]
    return persisted


def _truncate_parsed_content_value(value: str, *, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


def _parsed_content_with_fallback(
    *,
    document: DBDocument,
    tenant_id: UUID,
    row: DocumentParsedContent | None,
    max_chars: int,
) -> tuple[str, str, bool, bool, bool]:
    markdown = (getattr(row, "markdown_content", "") or "") if row is not None else ""
    original = (getattr(row, "original_markdown_content", "") or "") if row is not None else ""
    markdown, markdown_truncated = _truncate_parsed_content_value(markdown, max_chars=max_chars)
    original, original_truncated = _truncate_parsed_content_value(original, max_chars=max_chars)

    if markdown.strip() or original.strip():
        return markdown, original, markdown_truncated, original_truncated, False

    fallback = _read_local_text_source_fallback(document, tenant_id=tenant_id, max_chars=max_chars)
    if fallback is None:
        return markdown, original, markdown_truncated, original_truncated, False

    fallback_text, fallback_truncated = fallback
    if not fallback_text.strip():
        return markdown, original, markdown_truncated, original_truncated, False
    return fallback_text, fallback_text, fallback_truncated, fallback_truncated, True


@router.get(
    "/{document_id}/parsed-content",
    response_model=DocumentParsedContentResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_document_parsed_content(
    document_id: uuid.UUID,
    max_chars: Annotated[int, Query(ge=0, le=2000000)] = 200_000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get persisted parsed markdown content (raw+clean) for a document.

    Availability:
    - Prefer persisted parsed content when the ingestion pipeline enables it.
    - For local text-like source files, fall back to the original text when no parsed cache exists.
    - When unavailable, returns `available=false` with empty strings.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    dataset = _resolve_document_dataset_for_access(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )
    assert_document_acl_readable(db, tenant_id=tenant_id, account_id=account_id, document=document, dataset=dataset)

    row = (
        db.query(DocumentParsedContent)
        .filter(DocumentParsedContent.document_id == document_id, DocumentParsedContent.tenant_id == tenant_id)
        .first()
    )

    max_chars_eff = int(max_chars or 0)
    markdown, original, markdown_truncated, original_truncated, source_fallback_available = (
        _parsed_content_with_fallback(
            document=document,
            tenant_id=tenant_id,
            row=row,
            max_chars=max_chars_eff,
        )
    )

    return DocumentParsedContentResponse(
        document_id=document_id,
        available=row is not None or source_fallback_available,
        markdown_content=markdown,
        original_markdown_content=original,
        persisted_meta=_document_parsed_content_meta(document),
        markdown_truncated=markdown_truncated,
        original_markdown_truncated=original_truncated,
        max_chars=max_chars_eff,
    )


@router.get("/{document_id}/clean-docx", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def download_document_clean_docx(
    document_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
    assert_document_acl_readable(db, tenant_id=tenant_id, account_id=account_id, document=document, dataset=dataset)

    row = (
        db.query(DocumentParsedContent)
        .filter(DocumentParsedContent.document_id == document_id, DocumentParsedContent.tenant_id == tenant_id)
        .first()
    )
    if row is None or not str(getattr(row, "markdown_content", "") or "").strip():
        raise HTTPException(status_code=404, detail="Clean DOCX not available")

    title = Path(str(getattr(document, "filename", "") or "document")).stem
    markdown = str(getattr(row, "markdown_content", "") or "")
    blocks = markdown_to_blocks(markdown)
    if blocks:
        first = blocks[0] if isinstance(blocks[0], dict) else {}
        if str(first.get("type") or "").strip().lower() == "heading" and str(first.get("text") or "").strip() == title:
            blocks = blocks[1:]
    payload = render_clean_docx_bytes(title=title, blocks=blocks)
    headers = file_response_headers(f"{title}_Clean.docx", disposition="inline", cache_control=None)
    return StreamingResponse(
        iter([payload]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )
