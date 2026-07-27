"""Secure compatibility lookup for preview images created before owner sidecars."""

from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.document import DocumentChunk, DocumentParsedContent
from app.services.document_preview_utils import PREVIEW_IMAGE_REF_RE


def _preview_id_variants(preview_id: str) -> tuple[str, str] | None:
    try:
        value = UUID(str(preview_id))
    except ValueError:
        return None
    return value.hex, str(value)


def _content_references_preview_id(content: object, *, preview_id: str) -> bool:
    if not isinstance(content, str) or not content:
        return False
    for match in PREVIEW_IMAGE_REF_RE.finditer(content):
        try:
            if UUID(match.group(1)).hex == preview_id:
                return True
        except ValueError:
            continue
    return False


def find_legacy_preview_document_ids(
    db: Session,
    *,
    tenant_id: UUID,
    preview_id: str,
    max_scan_rows: int = 200,
) -> set[UUID]:
    """Find documents that already contain an exact legacy local-image reference."""
    variants = _preview_id_variants(preview_id)
    if variants is None:
        return set()
    compact_id, _hyphenated_id = variants
    needles = tuple(f"/api/v1/documents/image/{value}" for value in variants)
    limit = max(1, int(max_scan_rows or 1))
    document_ids: set[UUID] = set()

    # Preserve request-time exact-ref verification; ownership resolution stays outside this scan.
    chunk_rows = (
        db.query(DocumentChunk.document_id, DocumentChunk.content)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            or_(*(DocumentChunk.content.contains(needle) for needle in needles)),
        )
        .limit(limit)
        .all()
    )
    for document_id, content in chunk_rows:
        if _content_references_preview_id(content, preview_id=compact_id):
            document_ids.add(document_id)

    parsed_rows = (
        db.query(
            DocumentParsedContent.document_id,
            DocumentParsedContent.markdown_content,
            DocumentParsedContent.original_markdown_content,
        )
        .filter(
            DocumentParsedContent.tenant_id == tenant_id,
            or_(
                *(DocumentParsedContent.markdown_content.contains(needle) for needle in needles),
                *(DocumentParsedContent.original_markdown_content.contains(needle) for needle in needles),
            ),
        )
        .limit(limit)
        .all()
    )
    for document_id, markdown_content, original_markdown_content in parsed_rows:
        if _content_references_preview_id(markdown_content, preview_id=compact_id) or _content_references_preview_id(
            original_markdown_content,
            preview_id=compact_id,
        ):
            document_ids.add(document_id)

    return document_ids


def legacy_preview_ref_belongs_to_document(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    preview_id: str,
) -> bool:
    return document_id in find_legacy_preview_document_ids(
        db,
        tenant_id=tenant_id,
        preview_id=preview_id,
    )
