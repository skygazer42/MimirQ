from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import DocumentParsedContentQuery, DocumentParsedContentResponse
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES, file_response_headers
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document, DocumentParsedContent
from app.parsing.factory import ParserFactory
from app.parsing.output import markdown_to_blocks, render_clean_docx_bytes
from app.services import dataset_service
from app.services.document_access_service import assert_document_readable_for_lifecycle
from app.services.path_safety import resolve_under_base

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)

_TEXT_SOURCE_FALLBACK_EXTENSIONS = frozenset(ParserFactory.PLAIN_TEXT_EXTENSIONS | {".md", ".markdown"})
_TEXT_SOURCE_FALLBACK_MAX_BYTES = 8_000_000


def _is_text_source(document: Document) -> bool:
    file_type_ext = document.file_type.strip().lower()
    if not file_type_ext.startswith("."):
        file_type_ext = f".{file_type_ext}"
    if file_type_ext in _TEXT_SOURCE_FALLBACK_EXTENSIONS:
        return True
    return any(
        Path(path).suffix.lower() in _TEXT_SOURCE_FALLBACK_EXTENSIONS
        for path in (document.filename, document.file_path)
    )


def _read_local_text_source_fallback(
    document: Document,
    *,
    tenant_id: UUID,
    max_chars: int,
) -> tuple[str, bool] | None:
    if not _is_text_source(document):
        return None

    raw_path = document.file_path.strip()
    if not raw_path or raw_path.startswith("manual://"):
        return None

    path = Path(raw_path)
    upload_root = Path(settings.UPLOAD_DIR)
    safe_path = resolve_under_base(path, base=upload_root / str(tenant_id))
    if safe_path is None or not safe_path.is_file():
        return None

    byte_limit = (max_chars * 4 + 4) if max_chars > 0 else _TEXT_SOURCE_FALLBACK_MAX_BYTES
    try:
        with safe_path.open("rb") as fh:
            raw = fh.read(byte_limit)
        source_size = safe_path.stat().st_size
    except OSError:
        return None

    text = raw.decode("utf-8-sig", errors="replace")
    truncated = source_size > len(raw)
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    return text, truncated


def _get_document_and_parsed_content(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document_id: UUID,
) -> tuple[Document, DocumentParsedContent | None]:
    dataset_service.ensure_member(db, tenant_id, account_id)
    document = db.query(Document).filter(Document.id == document_id, Document.tenant_id == tenant_id).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    assert_document_readable_for_lifecycle(db, tenant_id=tenant_id, account_id=account_id, document=document)
    row = (
        db.query(DocumentParsedContent)
        .filter(DocumentParsedContent.document_id == document_id, DocumentParsedContent.tenant_id == tenant_id)
        .first()
    )
    return document, row


def _document_parsed_content_meta(document: Document) -> dict[str, Any]:
    doc_meta = document.doc_metadata
    if not isinstance(doc_meta, dict):
        return {}
    persisted_meta = doc_meta.get("parsed_content_persisted")
    persisted = dict(persisted_meta) if isinstance(persisted_meta, dict) else {}
    for key in ("parser_backend", "parser_backend_requested", "parse_duration_sec", "elements"):
        if key in doc_meta:
            persisted.setdefault(key, doc_meta[key])
    return persisted


def _truncate_parsed_content_value(value: str, *, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


@router.get("/{document_id}/parsed-content", response_model=DocumentParsedContentResponse)
def get_document_parsed_content(
    document_id: UUID,
    params: Annotated[DocumentParsedContentQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentParsedContentResponse:
    """
    Get persisted parsed markdown content (raw+clean) for a document.

    Availability:
    - Prefer persisted parsed content when the ingestion pipeline enables it.
    - For local text-like source files, fall back to the original text when no parsed cache exists.
    - When unavailable, returns `available=false` with empty strings.
    """
    document, row = _get_document_and_parsed_content(
        db, document_id=document_id, tenant_id=tenant_id, account_id=account_id
    )
    content = DocumentParsedContentResponse(
        document_id=document_id,
        available=row is not None,
        persisted_meta=_document_parsed_content_meta(document),
        max_chars=params.max_chars,
    )
    if row is not None:
        content.markdown_content, content.markdown_truncated = _truncate_parsed_content_value(
            row.markdown_content, max_chars=params.max_chars
        )
        content.original_markdown_content, content.original_markdown_truncated = _truncate_parsed_content_value(
            row.original_markdown_content, max_chars=params.max_chars
        )
    if content.markdown_content.strip() or content.original_markdown_content.strip():
        return content

    source = _read_local_text_source_fallback(document, tenant_id=tenant_id, max_chars=params.max_chars)
    if source is None:
        return content
    text, truncated = source
    if not text.strip():
        return content

    content.available = True
    content.markdown_content = text
    content.original_markdown_content = text
    content.markdown_truncated = truncated
    content.original_markdown_truncated = truncated
    return content


@router.get("/{document_id}/clean-docx")
def download_document_clean_docx(
    document_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> StreamingResponse:
    document, row = _get_document_and_parsed_content(
        db, document_id=document_id, tenant_id=tenant_id, account_id=account_id
    )
    if row is None or not row.markdown_content.strip():
        raise HTTPException(status_code=404, detail="Clean DOCX not available")

    title = Path(document.filename or "document").stem
    markdown = row.markdown_content
    blocks = markdown_to_blocks(markdown)
    if blocks:
        first = blocks[0]
        if first["type"].strip().lower() == "heading" and first["text"].strip() == title:
            blocks = blocks[1:]
    payload = render_clean_docx_bytes(title=title, blocks=blocks)
    headers = file_response_headers(f"{title}_Clean.docx", disposition="inline", cache_control=None)
    return StreamingResponse(
        iter([payload]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )
