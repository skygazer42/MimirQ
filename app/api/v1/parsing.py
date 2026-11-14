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

import contextlib
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import DocumentDetail, DocumentList
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.api.utils import save_upload_file
from app.core.async_bridge import run_blocking_in_thread
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.env import is_production_env
from app.models.dataset import Dataset, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.document import DocumentParsedContent
from app.parsing.artifact_stats import compute_parsing_artifact_stats
from app.parsing.diagnostics import build_parse_failure_diagnostics
from app.parsing.enrich.image_caption import add_image_captions
from app.parsing.enrich.image_ocr import add_image_ocr_blocks
from app.parsing.factory import parser_factory
from app.parsing.parsers.magic_pdf_parser import magicpdf_service_configured, resolve_magicpdf_models_dir
from app.parsing.processors.cross_page_merge import merge_cross_page_items
from app.parsing.processors.parse_quality_gate import apply_parse_quality_gate_metadata
from app.parsing.processors.vlm_correction import maybe_correct_markdown_pages
from app.parsing.quality.competition import compute_competition_matrix_score, select_best_parse_attempt
from app.parsing.quality.document_quality import score_document_parse_quality
from app.parsing.quality.reading_order import score_reading_order
from app.parsing.quality.text_quality import score_parsed_text_quality
from app.parsing.routing import should_attempt_pdf_fallback
from app.parsing.subprocess_runner import SubprocessCancelled, SubprocessWorkerError, run_subprocess_worker
from app.parsing.utils.cli import resolve_cli_command
from app.parsing.utils.document_elements import normalize_document_elements
from app.rag.core.logging import get_logger
from app.services import dataset_service
from app.services.document_source_persistence import store_document_source
from app.services.parsing_extract_service import extract_parsing_fields
from app.storage.object.runtime import (
    document_object_storage_enabled,
    document_object_store_metadata,
    get_document_object_store,
    is_object_storage_uri,
    resolve_document_object_reference,
)

logger = get_logger("api.parsing")
_PARSING_ROUTER_FALLBACK_LOG_MESSAGE = "Ignoring non-critical parsing router fallback failure: %s"


router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

# Filename validation:
# - Workspace uploads are persisted by UUID (local/MinIO), so we don't need a strict allowlist.
# - Still reject path separators / control characters to prevent path traversal and header issues.

_DETAIL_SOURCE_FILE_NOT_FOUND = "Source file not found"
_VLM_CORRECTION_SCHEMA = "mimirq.vlm_correction.v1"

POSITION_TAG_RE = re.compile(r"@@([0-9-]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##")


class ParsingElementBBox(BaseModel):
    x0: int
    y0: int
    x1: int
    y1: int


class ParsingElementOut(BaseModel):
    id: str
    kind: Literal["heading", "paragraph", "list", "table", "image", "equation", "seal", "unknown"]
    page: int | None = None
    pages: list[int] | None = None
    visual_kind: str | None = None
    text: str | None = None
    confidence: float | None = None
    source_backend: str | None = None
    source_element_id: str | None = None
    bbox: ParsingElementBBox | None = None
    attributes: dict[str, Any] | None = None


class ParsingContentResponse(BaseModel):
    document_id: UUID
    parser_backend: str = Field(default="auto")
    markdown_content: str = Field(default="")
    original_markdown_content: str = Field(default="")
    stats: dict[str, int] | None = Field(default=None)
    parse_duration_sec: float | None = Field(default=None)
    pdf_quality: dict[str, Any] | None = Field(default=None)
    quality_gate: "ParsingQualityGate | None" = Field(default=None)
    elements: list[ParsingElementOut] | None = Field(default=None)

    @field_validator("parse_duration_sec", mode="before")
    @classmethod
    def parse_stored_duration(cls, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return None


class ParsingContentUpdateRequest(BaseModel):
    markdown_content: str = Field(default="")
    original_markdown_content: str | None = None


class ParsingExtractFieldSpec(BaseModel):
    type: Literal["string"] = "string"
    source_kind: str | None = None
    source_visual_kind: str | None = None
    aliases: list[str] = Field(default_factory=list)


class ParsingExtractRequest(BaseModel):
    model_config = ConfigDict(loc_by_alias=False)

    mode: Literal["schema", "prompt"] = "schema"
    schema_: dict[str, ParsingExtractFieldSpec] | None = Field(
        default=None, validation_alias=AliasChoices("schema_", "schema")
    )
    prompt: str | None = None
    field_hints: dict[str, ParsingExtractFieldSpec] | None = None
    max_evidence: int = Field(default=1, ge=1, le=5)


class ParsingExtractEvidence(BaseModel):
    element_id: str | None = None
    kind: Literal["heading", "paragraph", "list", "table", "image", "equation", "seal", "unknown"] | None = None
    page: int | None = None
    pages: list[int] | None = None
    visual_kind: str | None = None
    bbox: ParsingElementBBox | None = None
    text: str | None = None
    score: float | None = None


class ParsingExtractFieldResult(BaseModel):
    value: str | None = None
    confidence: float | None = None
    evidence: list[ParsingExtractEvidence] = Field(default_factory=list)
    strategy: str | None = None


class ParsingExtractResponse(BaseModel):
    document_id: UUID
    mode: Literal["schema", "prompt"] = "schema"
    result: dict[str, ParsingExtractFieldResult] = Field(default_factory=dict)


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


class ParsingDocumentListQuery(BaseModel):
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=1, le=200)
    status: str | None = None
    dataset_id: UUID | None = None


class ParsingDocumentUploadForm(BaseModel):
    file: UploadFile
    parser_backend: str = "auto"
    dataset_id: UUID | None = None

    @model_validator(mode="before")
    @classmethod
    def omit_empty_form_values(cls, data: object) -> object:
        # Match individual Form fields: only exact empty strings use defaults.
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if value != ""}
        return data


class ParsingDocumentParseQuery(BaseModel):
    parser_backend: str | None = None
    image_caption_enabled: bool = False
    image_ocr_enabled: bool = False
    vlm_correction_enabled: bool | None = None


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
    return POSITION_TAG_RE.sub("", markdown)


def _strip_storage_nul_chars(value: str) -> str:
    """PostgreSQL text/jsonb cannot store NUL bytes; OCR backends may emit them."""
    return value.replace("\x00", "")


def _sanitize_storage_value(value: Any) -> Any:
    if isinstance(value, str):
        return _strip_storage_nul_chars(value)
    if isinstance(value, list):
        return [_sanitize_storage_value(item) for item in value]
    if isinstance(value, dict):
        return {_strip_storage_nul_chars(str(key)): _sanitize_storage_value(item) for key, item in value.items()}
    return value


def _extract_markdown_pair_from_documents(documents: list[dict[str, Any]]) -> tuple[str, str]:
    original_parts: list[str] = []
    cleaned_parts: list[str] = []
    has_position_tagged_override = False

    for item in documents:
        page_content = _strip_storage_nul_chars(item["page_content"])
        cleaned_parts.append(page_content)

        tagged = item["metadata"].get("position_tagged_markdown")
        if isinstance(tagged, str) and tagged.strip():
            has_position_tagged_override = True
            original_parts.append(_strip_storage_nul_chars(tagged))
            continue

        original_parts.append(page_content)

    original = "\n\n".join(original_parts).strip()
    if has_position_tagged_override:
        cleaned = "\n\n".join(cleaned_parts).strip()
    else:
        cleaned = _strip_position_tags(original).strip()

    return original, cleaned


def _should_inline_preview_parse(file_ext: str) -> bool:
    if not settings.PREVIEW_INLINE_TEXT_PARSE_ENABLED:
        return False
    ext = file_ext.strip().lower()
    return ext == ".md" or ext in parser_factory.PLAIN_TEXT_EXTENSIONS


def _parse_inline_text_preview(
    *,
    source_path: Path,
    resolved_backend: str,
    tenant_id: UUID,
    document_id: UUID,
    requested_backend: str,
) -> dict[str, Any]:
    documents, inline_backend, provenance = parser_factory.parse_with_provenance(
        source_path,
        parser_backend=resolved_backend,
        tenant_id=str(tenant_id),
        document_id=str(document_id),
    )
    provenance["payload_requested_backend"] = requested_backend
    provenance["effective_backend"] = resolved_backend
    provenance["execution_mode"] = "inline_text_preview"
    return {
        "resolved_backend": inline_backend,
        "pdf_quality": None,
        "documents": [
            {"page_content": doc.page_content, "metadata": _sanitize_storage_value(doc.metadata), "id": doc.id}
            for doc in documents
        ],
        "provenance": _sanitize_storage_value(provenance),
    }


def _compute_parsing_quality_gate(
    markdown: str,
    *,
    pdf_quality: dict[str, Any] | None,
    min_content_chars: int,
    is_pdf: bool,
) -> ParsingQualityGate:
    reasons: list[str] = []
    grade: Literal["pass", "warn", "fail"] = "pass"

    text_quality = score_parsed_text_quality(markdown)
    evidence: dict[str, Any] = {
        "text_quality": text_quality.to_dict(),
    }
    evidence["parse_quality"] = score_document_parse_quality(
        pdf_quality=pdf_quality,
        parsed_text_quality=text_quality.to_dict(),
    )
    if is_pdf:
        evidence["min_content_chars"] = min_content_chars
    if pdf_quality:
        evidence["pdf_quality"] = dict(pdf_quality)

    if not markdown.strip():
        grade = "fail"
        reasons.append("empty_markdown")

    if is_pdf and text_quality.content_chars < min_content_chars:
        grade = "fail"
        reasons.append("low_content_chars")

    # Heuristic warnings (best-effort).
    if text_quality.replacement_ratio >= 0.08:
        reasons.append("high_replacement_ratio")

    if text_quality.density <= 0.12:
        reasons.append("low_density")

    if pdf_quality is not None and pdf_quality.get("is_scanned", False):
        reasons.append("pdf_scanned")

    if grade == "pass" and reasons:
        grade = "warn"

    return ParsingQualityGate(grade=grade, reasons=reasons, evidence=evidence)


def _dump_extract_field_spec_map(
    spec_map: dict[str, ParsingExtractFieldSpec] | None,
) -> dict[str, dict[str, Any]] | None:
    if not spec_map:
        return None
    return {key: value.model_dump(exclude_none=True) for key, value in spec_map.items()}


@router.post(
    "/documents/{document_id}/extract",
    response_model=ParsingExtractResponse,
)
def extract_parsing_document(
    document_id: uuid.UUID,
    payload: ParsingExtractRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    doc = _get_workspace_document(db, tenant_id=tenant_id, account_id=account_id, document_id=document_id)
    meta = doc.doc_metadata
    row = (
        db.query(DocumentParsedContent)
        .filter(DocumentParsedContent.document_id == doc.id, DocumentParsedContent.tenant_id == tenant_id)
        .first()
    )
    markdown = ""
    if row is not None:
        markdown = row.markdown_content or row.original_markdown_content
    stored_elements = meta.get("elements")
    elements = stored_elements if isinstance(stored_elements, list) else []
    result = extract_parsing_fields(
        markdown=markdown,
        elements=elements,
        mode=payload.mode,
        schema=_dump_extract_field_spec_map(payload.schema_),
        prompt=payload.prompt,
        field_hints=_dump_extract_field_spec_map(payload.field_hints),
        max_evidence=payload.max_evidence,
    )
    return ParsingExtractResponse(
        document_id=document_id,
        mode=payload.mode,
        result=result,
    )


def _count_to_score(count: int, *, scale: int) -> float:
    """
    Turn a non-negative count into a bounded [0..1] score (saturating).

    Examples (scale=3):
      0 -> 0.0
      1 -> 0.25
      3 -> 0.5
      9 -> 0.75
    """
    return round(count / (count + scale), 4)


def _load_competition_weights() -> dict[str, float] | None:
    """
    Parse weights JSON (Opt 8) from settings, with a safe default.
    """
    if not settings.PARSE_COMPETITION_MATRIX_ENABLED:
        return None

    raw = settings.PARSE_COMPETITION_MATRIX_WEIGHTS_JSON.strip()
    if raw:
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and obj:
                return {str(k): float(v) for k, v in obj.items()}
        except Exception:
            return None

    # Balanced defaults for parser competition scoring.
    return {"text": 0.40, "table": 0.30, "image": 0.15, "reading_order": 0.15}


def _magicpdf_fallback_available() -> bool:
    if not settings.MAGIC_PDF_ENABLED:
        return False
    if magicpdf_service_configured(settings.MAGIC_PDF_API_URL):
        return True
    cli = settings.MAGIC_PDF_CLI.strip() or "magic-pdf"
    models_dir = resolve_magicpdf_models_dir(settings.MAGIC_PDF_MODELS_DIR)
    return bool(resolve_cli_command(cli) and models_dir)


def _build_pdf_fallback_candidates() -> list[str]:
    """
    Best-effort fallback order for PDF auto parsing.

    Keep it conservative: we only include backends that appear enabled/configured.
    """
    candidates: list[str] = []

    if settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL):
        candidates.append("mineru")
    if settings.DEEPSEEK_OCR_ENABLED and settings.SILICONFLOW_API_KEY.strip():
        candidates.append("deepseek_ocr")
    if settings.QIANFAN_OCR_ENABLED and settings.QIANFAN_OCR_API_URL.strip():
        candidates.append("qianfan_ocr")
    if settings.ETL4LLM_ENABLED and settings.ETL4LLM_API_URL.strip():
        candidates.append("etl4llm")
    if settings.DEEPDOC_ENABLED:
        candidates.append("deepdoc")
    if settings.DOCLING_ENABLED and settings.DOCLING_API_URL.strip():
        candidates.append("docling")

    # MagicPDF prefers service mode; local CLI remains a fallback.
    try:
        if _magicpdf_fallback_available():
            candidates.append("magicpdf")
    except Exception as exc:
        logger.debug(_PARSING_ROUTER_FALLBACK_LOG_MESSAGE, exc, exc_info=True)

    if settings.MARKITDOWN_ENABLED:
        candidates.append("markitdown")

    # Always keep a basic fallback.
    candidates.append("basic")

    return candidates


def _get_or_create_workspace_dataset(db: Session, tenant_id: UUID, account_id: str) -> Dataset:
    """
    Use a per-user ONLY_ME dataset as the parsing workspace container.

    This gives us enterprise-grade access control for free (download/get/list).
    """
    # Try to find an existing dataset marked as parsing workspace for this owner.
    existing = db.query(Dataset).filter(Dataset.tenant_id == tenant_id, Dataset.owner_id == account_id).all()
    for ds in existing:
        meta = ds.dataset_metadata
        if isinstance(meta, dict) and meta.get("parsing_workspace") is True:
            return ds

    # Create a new one (ONLY_ME).
    #
    # IMPORTANT:
    # Dataset names are unique per tenant, so a constant name would conflict across users
    # when auth uses dynamic account ids (e.g. smoke tests, JWT users). Use a stable
    # owner-scoped suffix to avoid collisions while keeping the name readable.
    owner_tag = hashlib.blake2b(account_id.encode("utf-8"), digest_size=4).hexdigest()
    dataset_name = f"Parsing Workspace [{owner_tag}]"

    try:
        ds = dataset_service.create_dataset(
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
        if exc.status_code == 409:
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
                meta = dict(ds.dataset_metadata or {})
                meta["parsing_workspace"] = True
                meta["parsing_workspace_owner_tag"] = owner_tag
                ds.dataset_metadata = meta
                db.commit()
                db.refresh(ds)
                return ds
        raise
    meta = dict(ds.dataset_metadata or {})
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
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(status_code=403, detail="File access denied") from None


def _get_workspace_document(db: Session, *, tenant_id: UUID, account_id: str, document_id: UUID) -> DBDocument:
    dataset_service.ensure_member(db, tenant_id, account_id)

    doc = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    meta = doc.doc_metadata
    if not isinstance(meta, dict) or meta.get("workspace") != "parsing":
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.dataset_id:
        ds = dataset_service.get_dataset(db, tenant_id, doc.dataset_id)
        dataset_service.assert_dataset_readable(db, ds, account_id)
    else:
        # Should not happen for workspace docs, but keep safe default.
        raise HTTPException(status_code=403, detail="Workspace access denied")

    owner_id = doc.owner_id.strip()
    if owner_id and owner_id != account_id:
        raise HTTPException(status_code=404, detail="Document not found")

    return doc


@router.get("/documents", response_model=DocumentList)
def list_parsing_documents(
    params: Annotated[ParsingDocumentListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    List parsing workspace documents (persistent across restarts).
    """
    workspace_dataset = _get_or_create_workspace_dataset(db, tenant_id, account_id)
    dataset_service.assert_dataset_readable(db, workspace_dataset, account_id)

    query = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id)
    query = query.filter(
        or_(
            DBDocument.dataset_id == workspace_dataset.id,
            DBDocument.owner_id == account_id,
        )
    )

    if params.dataset_id is not None:
        target_dataset = dataset_service.get_dataset(db, tenant_id, params.dataset_id)
        dataset_service.assert_dataset_readable(db, target_dataset, account_id)
        query = query.filter(
            or_(
                DBDocument.dataset_id == params.dataset_id,
                DBDocument.doc_metadata["target_dataset_id"].astext == str(params.dataset_id),
            )
        )
    query = query.filter(DBDocument.doc_metadata["workspace"].astext == "parsing")

    if params.status and params.status != "all":
        query = query.filter(DBDocument.status == params.status)

    total = query.count()
    items = query.order_by(DBDocument.created_at.desc()).offset(params.skip).limit(params.limit).all()
    return {"total": total, "items": items}


def _prepare_parsing_upload_target(
    *, tenant_id: UUID, account_id: str, dataset_id: UUID | None
) -> tuple[UUID, str | None]:
    with SessionLocal() as db:
        dataset_service.ensure_member(db, tenant_id, account_id)
        if dataset_id is not None:
            dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
        else:
            dataset = _get_or_create_workspace_dataset(db, tenant_id, account_id)
        dataset_service.assert_dataset_writable(db, dataset, account_id)
        return dataset.id, dataset.name if dataset_id is not None else None


async def _store_parsing_upload(
    *,
    source_path: Path,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
    file_ext: str,
    content_type: str,
    use_object_storage: bool,
) -> tuple[str, dict[str, Any]]:
    if not use_object_storage:
        await run_blocking_in_thread(_assert_path_under_tenant_root, tenant_id=tenant_id, path=source_path)
        return str(source_path), {}
    try:
        store = get_document_object_store()
        if store is None:
            raise HTTPException(status_code=503, detail="Object storage is disabled")
        stored_path = await store_document_source(
            file_path=source_path,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            extension=file_ext,
            content_type=content_type,
        )
        metadata = document_object_store_metadata(store) if is_object_storage_uri(stored_path) else {}
        return stored_path, metadata
    finally:
        with anyio.fail_after(5.0, shield=True):
            await run_blocking_in_thread(source_path.unlink, missing_ok=True)


def _persist_parsing_upload(
    *,
    id: UUID,
    tenant_id: UUID,
    dataset_id: UUID,
    filename: str,
    file_type: str,
    file_size: int,
    file_path: str,
    owner_id: str,
    status: str,
    processing_progress: int,
    current_stage: str,
    doc_metadata: dict[str, Any],
) -> DocumentDetail:
    # Keep the session and response materialization in this worker even on cancellation.
    with SessionLocal() as worker_db:
        doc = DBDocument(
            id=id,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            file_path=file_path,
            owner_id=owner_id,
            status=status,
            processing_progress=processing_progress,
            current_stage=current_stage,
            doc_metadata=doc_metadata,
        )
        worker_db.add(doc)
        worker_db.commit()
        worker_db.refresh(doc)
        return DocumentDetail.model_validate(doc)


@router.post("/documents", response_model=DocumentDetail, status_code=201)
async def upload_parsing_document(
    form: Annotated[ParsingDocumentUploadForm, Form(media_type="multipart/form-data")],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> DocumentDetail:
    """Upload a source file into the parsing workspace (no parsing yet)."""
    target_dataset_id, target_name = await run_blocking_in_thread(
        _prepare_parsing_upload_target,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=form.dataset_id,
    )
    file = form.file
    file.filename = _sanitize_filename(file.filename)
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400, detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )
    document_id = uuid.uuid4()
    use_object_storage = document_object_storage_enabled()
    upload_dir = (
        Path(settings.UPLOAD_DIR) / str(tenant_id) / ".tmp"
        if use_object_storage
        else await run_blocking_in_thread(_parsing_upload_dir, tenant_id)
    )
    source_path = upload_dir / f"{document_id}{file_ext}"
    file_size = await save_upload_file(file, source_path, max_bytes=settings.MAX_FILE_SIZE)
    meta = {
        "workspace": "parsing",
        "parser_backend_requested": form.parser_backend.strip().lower() or "auto",
    }
    if form.dataset_id is not None:
        meta["target_dataset_id"] = str(target_dataset_id)
        meta["target_dataset_name"] = target_name or str(target_dataset_id)
    stored_path, storage_meta = await _store_parsing_upload(
        source_path=source_path,
        tenant_id=tenant_id,
        dataset_id=target_dataset_id,
        document_id=document_id,
        file_ext=file_ext,
        content_type=file.content_type or "application/octet-stream",
        use_object_storage=use_object_storage,
    )
    meta.update(storage_meta)
    return await run_blocking_in_thread(
        _persist_parsing_upload,
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=target_dataset_id,
        filename=file.filename,
        file_type=file_ext.lstrip("."),
        file_size=file_size,
        file_path=stored_path,
        owner_id=account_id,
        status="pending",
        processing_progress=0,
        current_stage="parsing",
        doc_metadata=meta,
    )


@dataclass(frozen=True)
class _WorkspaceSource:
    id: UUID
    dataset_id: UUID
    file_path: str
    file_type: str
    doc_metadata: dict[str, Any]


def _load_workspace_source(*, tenant_id: UUID, account_id: str, document_id: UUID) -> _WorkspaceSource:
    with SessionLocal() as db:
        doc = _get_workspace_document(db, tenant_id=tenant_id, account_id=account_id, document_id=document_id)
        dataset = dataset_service.get_dataset(db, tenant_id, doc.dataset_id)
        dataset_service.assert_dataset_writable(db, dataset, account_id)
        return _WorkspaceSource(doc.id, doc.dataset_id, doc.file_path, doc.file_type, dict(doc.doc_metadata))


def _local_workspace_source_path(*, raw_path: str, tenant_id: UUID) -> Path:
    source_path = Path(raw_path).resolve(strict=False)
    _assert_path_under_tenant_root(tenant_id=tenant_id, path=source_path)
    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=404, detail=_DETAIL_SOURCE_FILE_NOT_FOUND)
    return source_path


async def _resolve_workspace_source_path(
    *,
    doc: _WorkspaceSource,
    tenant_id: UUID,
) -> Path:
    raw_path = doc.file_path.strip()
    if not raw_path or raw_path.startswith("manual://"):
        raise HTTPException(status_code=404, detail="Source file not available")
    if not is_object_storage_uri(raw_path):
        return await run_blocking_in_thread(_local_workspace_source_path, raw_path=raw_path, tenant_id=tenant_id)

    try:
        store, ref = resolve_document_object_reference(
            raw_path,
            tenant_id=tenant_id,
            dataset_id=doc.dataset_id,
            document_id=doc.id,
            file_type=doc.file_type,
            document_metadata=doc.doc_metadata,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Object storage is disabled") from exc
    except ValueError as exc:
        if str(exc) in {"object_bucket_denied", "object_key_denied"}:
            raise HTTPException(status_code=403, detail="Source file access denied") from exc
        raise HTTPException(status_code=404, detail=_DETAIL_SOURCE_FILE_NOT_FOUND) from exc

    try:
        await run_blocking_in_thread(store.stat_object, object_name=ref.object_name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=_DETAIL_SOURCE_FILE_NOT_FOUND) from exc

    temp_dir = await run_blocking_in_thread((Path(settings.UPLOAD_DIR) / str(tenant_id) / ".tmp").resolve, strict=False)
    suffix = f".{(doc.file_type).lower()}"
    temp_path = temp_dir / f"{doc.id}.{uuid.uuid4().hex}{suffix}"
    try:
        await run_blocking_in_thread(
            store.download_object_to_path,
            object_name=ref.object_name,
            destination=temp_path,
            max_bytes=settings.MAX_FILE_SIZE,
        )
    except BaseException:
        # The bridge waits for the writer before cancellation cleanup removes its output.
        with anyio.fail_after(5.0, shield=True):
            await run_blocking_in_thread(temp_path.unlink, missing_ok=True)
        raise
    return temp_path


def _fail_workspace_backend_mismatch(
    *,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    meta: dict[str, Any],
    requested_backend: str,
    resolved_backend: str,
    parse_provenance: dict[str, Any],
) -> None:
    with SessionLocal() as db:
        doc = _get_workspace_document(db, tenant_id=tenant_id, account_id=account_id, document_id=document_id)
        diagnostics = _sanitize_storage_value(
            {
                "requested_backend": requested_backend,
                "resolved_backend": resolved_backend,
                "provenance": parse_provenance,
            }
        )
        msg = f"Requested parser backend '{requested_backend}' fell back to '{resolved_backend}'"
        doc.status = "failed"
        doc.processing_progress = 0
        doc.current_stage = "failed"
        doc.error_message = msg
        next_meta = dict(meta)
        next_meta["workspace"] = "parsing"
        next_meta["parser_backend_requested"] = requested_backend
        next_meta["parser_backend"] = resolved_backend
        next_meta["parse_diagnostics"] = diagnostics
        doc.doc_metadata = _sanitize_storage_value(next_meta)
        db.commit()
        raise HTTPException(status_code=502, detail={"message": msg, "diagnostics": diagnostics})


async def _parse_workspace_source(
    *,
    source_path: Path,
    file_ext: str,
    request: Request,
    tenant_id: UUID,
    account_id: str,
    doc: _WorkspaceSource,
    requested_backend: str,
    resolved_backend: str,
    image_caption_enabled: bool,
    image_ocr_enabled: bool,
) -> dict[str, Any]:
    optional_image_enrichment = image_caption_enabled or image_ocr_enabled
    if _should_inline_preview_parse(file_ext) and not optional_image_enrichment:
        return await run_blocking_in_thread(
            _parse_inline_text_preview,
            source_path=source_path,
            resolved_backend=resolved_backend,
            tenant_id=tenant_id,
            document_id=doc.id,
            requested_backend=requested_backend,
        )
    return await run_subprocess_worker(
        tenant_id=tenant_id,
        payload={
            "action": "parse_documents",
            "tenant_id": str(tenant_id),
            "account_id": account_id,
            "dataset_id": str(doc.dataset_id),
            "document_id": str(doc.id),
            "file_path": str(source_path),
            "parser_backend": resolved_backend,
            "mode": "preview",
        },
        disconnect_check=request.is_disconnected,
        timeout_sec=settings.TASK_JOB_TIMEOUT_SEC,
    )


def _workspace_cross_page_merge_stats(artifact_docs: list[dict[str, Any]]) -> dict[str, int] | None:
    if not artifact_docs or not settings.CROSS_PAGE_MERGE_ENABLED:
        return None
    try:
        _docs, cross_page_merge_stats = merge_cross_page_items(artifact_docs)
        return cross_page_merge_stats
    except Exception:
        return None


def _build_workspace_parse_attempt(
    *,
    backend: str,
    gate: ParsingQualityGate,
    artifact_docs: list[dict[str, Any]],
    original_markdown: str,
    markdown: str,
    pdf_quality: dict[str, Any] | None,
    file_ext: str,
    matrix_weights: dict[str, float] | None,
    cross_page_merge_stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    parse_score = gate.evidence["parse_quality"]["score"]
    content_chars = gate.evidence["text_quality"]["content_chars"]
    stats = compute_parsing_artifact_stats(
        documents=artifact_docs,
        original_markdown=original_markdown,
        markdown=markdown,
        pdf_quality=pdf_quality,
    )
    ro = score_reading_order(original_markdown) if file_ext == ".pdf" else None
    ro_score = ro["score"] if ro is not None else None
    attempt: dict[str, Any] = {
        "backend": backend.strip(),
        "grade": gate.grade,
        "parse_score": parse_score,
        "content_chars": content_chars,
        "text_score": parse_score,
        "table_score": _count_to_score(stats["table_count"], scale=3),
        "image_score": _count_to_score(stats["image_count"], scale=5),
        "reading_order_score": ro_score,
        "artifact_stats": stats,
        "reading_order": ro,
        "cross_page_merge_stats": cross_page_merge_stats,
        "artifact_docs": artifact_docs,
        "original_markdown": original_markdown,
        "markdown": markdown,
        "gate": gate,
    }
    if matrix_weights:
        attempt["matrix_score"] = round(compute_competition_matrix_score(attempt, weights=matrix_weights), 4)
    return attempt


async def _run_workspace_fallback_candidate(
    *,
    candidate: str,
    resolved_backend: str,
    gate: ParsingQualityGate,
    pdf_quality: dict[str, Any] | None,
    min_chars: int,
    tenant_id: UUID,
    account_id: str,
    doc: _WorkspaceSource,
    source_path: Path,
    request: Request,
    file_ext: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        cand_backend = parser_factory.resolve_backend(file_ext, candidate)
    except Exception as exc:  # noqa: BLE001
        return {
            "from": resolved_backend,
            "to": candidate,
            "accepted": False,
            "error": f"invalid_backend:{str(exc)[:120]}",
        }, None

    try:
        alt_parsed = await run_subprocess_worker(
            tenant_id=tenant_id,
            payload={
                "action": "parse_documents",
                "tenant_id": str(tenant_id),
                "account_id": account_id,
                "dataset_id": str(doc.dataset_id),
                "document_id": str(doc.id),
                "file_path": str(source_path),
                "parser_backend": cand_backend,
                "mode": "preview",
                "pdf_quality": pdf_quality,
            },
            disconnect_check=request.is_disconnected,
            timeout_sec=settings.TASK_JOB_TIMEOUT_SEC,
        )
    except SubprocessCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        return {"from": resolved_backend, "to": cand_backend, "accepted": False, "error": str(exc)[:200]}, None

    alt_artifact_docs = alt_parsed["documents"]
    alt_cross_page_merge_stats = _workspace_cross_page_merge_stats(alt_artifact_docs)
    alt_backend = alt_parsed["resolved_backend"]
    alt_original, alt_markdown = _extract_markdown_pair_from_documents(alt_artifact_docs)
    alt_gate = _compute_parsing_quality_gate(
        alt_markdown,
        pdf_quality=pdf_quality,
        min_content_chars=min_chars,
        is_pdf=True,
    )
    return (
        {
            "from": resolved_backend,
            "to": alt_backend,
            "quality_before": gate.evidence.get("text_quality"),
            "quality_after": alt_gate.evidence.get("text_quality"),
            "grade_before": gate.grade,
            "grade_after": alt_gate.grade,
            "parse_score_before": gate.evidence["parse_quality"]["score"],
            "parse_score_after": alt_gate.evidence["parse_quality"]["score"],
            "accepted": alt_gate.grade != "fail",
        },
        {
            "backend": alt_backend,
            "gate": alt_gate,
            "artifact_docs": alt_artifact_docs,
            "original_markdown": alt_original,
            "markdown": alt_markdown,
            "cross_page_merge_stats": alt_cross_page_merge_stats,
        },
    )


async def _run_workspace_pdf_fallbacks(
    *,
    request: Request,
    tenant_id: UUID,
    account_id: str,
    doc: _WorkspaceSource,
    source_path: Path,
    file_ext: str,
    requested_backend: str,
    resolved_backend: str,
    gate: ParsingQualityGate,
    artifact_docs: list[dict[str, Any]],
    original_markdown: str,
    markdown: str,
    pdf_quality: dict[str, Any] | None,
) -> tuple[str, ParsingQualityGate, list[dict[str, Any]], str, str, dict[str, int] | None, list[dict[str, Any]]]:
    min_chars = max(0, settings.PARSE_FALLBACK_MIN_CONTENT_CHARS)
    min_parse_score = max(0.0, settings.PARSE_FALLBACK_MIN_PARSE_SCORE)
    max_retries = max(0, settings.PARSE_FALLBACK_MAX_RETRIES)
    matrix_weights = await run_blocking_in_thread(_load_competition_weights)
    fallback_attempts: list[dict[str, Any]] = []
    cross_page_merge_stats = _workspace_cross_page_merge_stats(artifact_docs)
    attempt_candidates = [
        _build_workspace_parse_attempt(
            backend=resolved_backend,
            gate=gate,
            artifact_docs=artifact_docs,
            original_markdown=original_markdown,
            markdown=markdown,
            pdf_quality=pdf_quality,
            file_ext=file_ext,
            matrix_weights=matrix_weights,
            cross_page_merge_stats=cross_page_merge_stats,
        )
    ]
    gate_parse_score = gate.evidence["parse_quality"]["score"]
    gate_content_chars = gate.evidence["text_quality"]["content_chars"]
    if not (
        file_ext == ".pdf"
        and requested_backend in {"", "auto"}
        and max_retries > 0
        and should_attempt_pdf_fallback(
            grade=gate.grade,
            parse_score=gate_parse_score,
            content_chars=gate_content_chars,
            min_content_chars=min_chars,
            min_parse_score=min_parse_score,
        )
    ):
        return (
            resolved_backend,
            gate,
            artifact_docs,
            original_markdown,
            markdown,
            cross_page_merge_stats,
            fallback_attempts,
        )

    retries_left = max_retries
    candidates = await run_blocking_in_thread(_build_pdf_fallback_candidates)
    filtered_candidates = [item for item in candidates if item != resolved_backend.strip().lower()]
    for candidate in filtered_candidates:
        if retries_left <= 0:
            break
        retries_left -= 1
        attempt_entry, candidate_state = await _run_workspace_fallback_candidate(
            candidate=candidate,
            resolved_backend=resolved_backend,
            gate=gate,
            pdf_quality=pdf_quality,
            min_chars=min_chars,
            tenant_id=tenant_id,
            account_id=account_id,
            doc=doc,
            source_path=source_path,
            request=request,
            file_ext=file_ext,
        )
        fallback_attempts.append(attempt_entry)
        if candidate_state is None:
            continue
        attempt_candidates.append(
            _build_workspace_parse_attempt(
                backend=candidate_state["backend"],
                gate=candidate_state["gate"],
                artifact_docs=candidate_state["artifact_docs"],
                original_markdown=candidate_state["original_markdown"],
                markdown=candidate_state["markdown"],
                pdf_quality=pdf_quality,
                file_ext=file_ext,
                matrix_weights=matrix_weights,
                cross_page_merge_stats=candidate_state["cross_page_merge_stats"],
            )
        )

    if len(attempt_candidates) == 1:
        return (
            resolved_backend,
            gate,
            artifact_docs,
            original_markdown,
            markdown,
            cross_page_merge_stats,
            fallback_attempts,
        )

    try:
        best = select_best_parse_attempt(attempt_candidates, weights=matrix_weights)
    except Exception:
        best = attempt_candidates[0]
    selected_backend = best["backend"]
    best_gate = best["gate"]
    for attempt in fallback_attempts:
        attempt["selected"] = attempt["to"] == selected_backend
    if fallback_attempts:
        best_gate = ParsingQualityGate(
            grade=best_gate.grade,
            reasons=best_gate.reasons,
            evidence={
                **best_gate.evidence,
                "fallback_attempts": fallback_attempts,
                "fallback_initial_backend": resolved_backend,
                "fallback_final_backend": selected_backend,
                "fallback_selected_backend": selected_backend,
                "fallback_max_retries": max_retries,
            },
        )
    return (
        selected_backend,
        best_gate,
        best["artifact_docs"],
        best["original_markdown"],
        best["markdown"],
        best["cross_page_merge_stats"],
        fallback_attempts,
    )


def _apply_workspace_vlm_correction(
    *,
    tenant_id: UUID,
    document_id: UUID,
    file_ext: str,
    artifact_docs: list[dict[str, Any]],
    markdown: str,
    gate: ParsingQualityGate,
    pdf_quality: dict[str, Any] | None,
    vlm_correction_enabled: bool | None,
) -> tuple[str, ParsingQualityGate, dict[str, Any] | None, bool]:
    vlm_correction_requested = (
        settings.VLM_CORRECTION_ENABLED if vlm_correction_enabled is None else vlm_correction_enabled
    )
    if file_ext != ".pdf" or not vlm_correction_requested:
        return markdown, gate, None, vlm_correction_requested
    try:
        pages = [_strip_position_tags(item["page_content"]) for item in artifact_docs]
        corrected_pages, audit = maybe_correct_markdown_pages(
            pages,
            enabled=True,
            api_url=settings.VLM_CORRECTION_API_URL,
            timeout_sec=settings.VLM_CORRECTION_TIMEOUT_SEC,
            max_pages=settings.VLM_CORRECTION_MAX_PAGES,
            max_chars=settings.VLM_CORRECTION_MAX_CHARS,
            pdf_quality=pdf_quality,
            min_table_quality=settings.VLM_CORRECTION_MIN_TABLE_QUALITY,
            meta={"tenant_id": str(tenant_id), "document_id": str(document_id)},
        )
        vlm_audit = audit.to_dict()
        if len(corrected_pages) != len(pages) or not corrected_pages:
            evidence = dict(gate.evidence)
            evidence["vlm_correction"] = {"schema": _VLM_CORRECTION_SCHEMA, **vlm_audit}
            return (
                markdown,
                ParsingQualityGate(
                    grade=gate.grade,
                    reasons=gate.reasons,
                    evidence=evidence,
                ),
                vlm_audit,
                vlm_correction_requested,
            )
        markdown = _strip_storage_nul_chars("\n\n".join(corrected_pages).strip())
        gate_after = _compute_parsing_quality_gate(
            markdown,
            pdf_quality=pdf_quality,
            min_content_chars=max(0, settings.PARSE_FALLBACK_MIN_CONTENT_CHARS),
            is_pdf=True,
        )
        next_evidence = dict(gate_after.evidence)
        for key in (
            "fallback_attempts",
            "fallback_initial_backend",
            "fallback_final_backend",
            "fallback_selected_backend",
            "fallback_max_retries",
            "competition_matrix",
            "artifact_stats",
            "reading_order",
            "matrix_score",
        ):
            if key in gate.evidence:
                next_evidence[key] = gate.evidence[key]
        next_evidence["vlm_correction"] = {"schema": _VLM_CORRECTION_SCHEMA, **vlm_audit}
        next_gate = ParsingQualityGate(
            grade=gate_after.grade,
            reasons=gate_after.reasons,
            evidence=next_evidence,
        )
        return markdown, next_gate, vlm_audit, vlm_correction_requested
    except Exception:
        return markdown, gate, None, vlm_correction_requested


def _apply_workspace_image_enrichments(
    *,
    markdown: str,
    source_path: Path,
    image_caption_enabled: bool,
    image_ocr_enabled: bool,
) -> tuple[str, int, int, dict[str, Any] | None]:
    captions_added = 0
    if image_caption_enabled:
        try:
            markdown, captions_added = add_image_captions(markdown)
            markdown = _strip_storage_nul_chars(markdown)
        except Exception:
            captions_added = 0
    image_ocr_added = 0
    image_ocr_audit = None
    if image_ocr_enabled:
        try:
            markdown, image_ocr_added, audit = add_image_ocr_blocks(
                markdown,
                origin_path=source_path,
                max_images=max(0, settings.IMAGE_OCR_MAX_IMAGES),
                max_ocr_chars=max(0, settings.IMAGE_OCR_MAX_CHARS),
            )
            image_ocr_audit = audit.to_dict()
            markdown = _strip_storage_nul_chars(markdown)
        except Exception:
            image_ocr_added = 0
            image_ocr_audit = None
    return markdown, captions_added, image_ocr_added, image_ocr_audit


def _build_workspace_parse_metadata(
    *,
    meta: dict[str, Any],
    requested_backend: str,
    resolved_backend: str,
    parse_provenance: dict[str, Any] | None,
    image_caption_enabled: bool,
    captions_added: int,
    image_ocr_enabled: bool,
    image_ocr_added: int,
    image_ocr_audit: dict[str, Any] | None,
    vlm_correction_requested: bool,
    pdf_quality: dict[str, Any] | None,
    cross_page_merge_stats: dict[str, int] | None,
    vlm_audit: dict[str, Any] | None,
    file_ext: str,
    original_markdown: str,
    gate: ParsingQualityGate,
    elements: list[dict[str, Any]],
    duration_sec: float,
    artifact_stats: dict[str, int],
    fallback_attempts: list[dict[str, Any]],
) -> tuple[dict[str, Any], ParsingQualityGate]:
    next_meta = dict(meta)
    next_meta["workspace"] = "parsing"
    next_meta["parser_backend_requested"] = requested_backend
    next_meta["parser_backend"] = resolved_backend
    if parse_provenance:
        next_meta["parse_provenance"] = parse_provenance
    next_meta["image_caption_enabled"] = image_caption_enabled
    if image_caption_enabled:
        next_meta["image_captions_added"] = captions_added
    next_meta["image_ocr_enabled"] = image_ocr_enabled
    if image_ocr_enabled:
        next_meta["image_ocr_added"] = image_ocr_added
        if image_ocr_audit:
            next_meta["image_ocr"] = {"schema": "mimirq.image_ocr.v1", **image_ocr_audit}
    next_meta["vlm_correction_enabled"] = vlm_correction_requested
    if pdf_quality:
        next_meta["pdf_quality"] = dict(pdf_quality)
    if cross_page_merge_stats:
        next_meta["cross_page_merge"] = {
            "schema": "mimirq.cross_page_merge.v1",
            "enabled": True,
            **cross_page_merge_stats,
        }
    if vlm_audit:
        next_meta["vlm_correction"] = {"schema": _VLM_CORRECTION_SCHEMA, **vlm_audit}

    try:
        reading_order = score_reading_order(original_markdown) if file_ext == ".pdf" else None
    except Exception:
        reading_order = None
    if reading_order:
        next_meta["reading_order"] = reading_order
    next_meta["quality_gate"] = gate.model_dump()
    next_meta["parse_quality"] = dict(gate.evidence["parse_quality"])
    next_meta["parsed_text_quality"] = dict(gate.evidence["text_quality"])
    next_meta["elements"] = elements
    next_meta["parsed_at"] = datetime.now(UTC).isoformat()
    next_meta["parse_duration_sec"] = round(duration_sec, 3)
    if fallback_attempts:
        next_meta["parse_fallback"] = {
            "attempts": fallback_attempts,
            "min_content_chars": max(0, settings.PARSE_FALLBACK_MIN_CONTENT_CHARS),
            "max_retries": max(0, settings.PARSE_FALLBACK_MAX_RETRIES),
        }
    next_meta.update(artifact_stats)
    next_meta.update(apply_parse_quality_gate_metadata(next_meta))
    gate = ParsingQualityGate(
        grade=gate.grade,
        reasons=gate.reasons,
        evidence={**gate.evidence, "parse_quality_gate": next_meta["parse_quality_gate"]},
    )
    next_meta["quality_gate"] = gate.model_dump()
    return _sanitize_storage_value(next_meta), gate


def _persist_workspace_parse_result(
    *,
    db: Session,
    doc: DBDocument,
    tenant_id: UUID,
    meta: dict[str, Any],
    requested_backend: str,
    resolved_backend: str,
    parse_provenance: dict[str, Any] | None,
    image_caption_enabled: bool,
    image_ocr_enabled: bool,
    vlm_correction_requested: bool,
    pdf_quality: dict[str, Any] | None,
    cross_page_merge_stats: dict[str, int] | None,
    vlm_audit: dict[str, Any] | None,
    file_ext: str,
    original_markdown: str,
    markdown: str,
    gate: ParsingQualityGate,
    elements: list[dict[str, Any]],
    duration_sec: float,
    artifact_docs: list[dict[str, Any]],
    captions_added: int,
    image_ocr_added: int,
    image_ocr_audit: dict[str, Any] | None,
    fallback_attempts: list[dict[str, Any]],
) -> ParsingContentResponse:
    artifact_stats = compute_parsing_artifact_stats(
        documents=artifact_docs,
        original_markdown=original_markdown,
        markdown=markdown,
        pdf_quality=pdf_quality,
    )
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
    doc.doc_metadata, gate = _build_workspace_parse_metadata(
        meta=meta,
        requested_backend=requested_backend,
        resolved_backend=resolved_backend,
        parse_provenance=parse_provenance,
        image_caption_enabled=image_caption_enabled,
        captions_added=captions_added,
        image_ocr_enabled=image_ocr_enabled,
        image_ocr_added=image_ocr_added,
        image_ocr_audit=image_ocr_audit,
        vlm_correction_requested=vlm_correction_requested,
        pdf_quality=pdf_quality,
        cross_page_merge_stats=cross_page_merge_stats,
        vlm_audit=vlm_audit,
        file_ext=file_ext,
        original_markdown=original_markdown,
        gate=gate,
        elements=elements,
        duration_sec=duration_sec,
        artifact_stats=artifact_stats,
        fallback_attempts=fallback_attempts,
    )
    db.commit()
    db.refresh(doc)
    return ParsingContentResponse(
        document_id=doc.id,
        parser_backend=resolved_backend,
        markdown_content=markdown,
        original_markdown_content=original_markdown,
        stats=artifact_stats,
        parse_duration_sec=round(duration_sec, 3),
        pdf_quality=pdf_quality,
        quality_gate=gate,
        elements=elements,
    )


def _workspace_failure_detail(*, message: str, status_code: int) -> str:
    prefix = "Invalid input" if status_code == 400 else "Failed to parse document"
    return prefix if is_production_env() else f"{prefix}: {message}"


def _build_workspace_parse_diagnostics(
    *,
    source_path: Path,
    file_ext: str,
    requested_backend: str,
    resolved_backend: str,
    error_type: str | None,
    error_message: str,
) -> dict[str, Any]:
    try:
        return build_parse_failure_diagnostics(
            file_path=source_path,
            file_ext=file_ext,
            parser_backend_requested=requested_backend,
            parser_backend_resolved=resolved_backend,
            error_type=error_type,
            error_message=error_message,
        )
    except Exception:
        return {}


def _persist_workspace_parse_failure(
    *,
    doc: DBDocument,
    db: Session,
    message: str,
    diagnostics: dict[str, Any],
) -> None:
    doc.status = "failed"
    doc.processing_progress = 0
    doc.current_stage = "failed"
    doc.error_message = message
    next_meta = dict(doc.doc_metadata)
    if diagnostics:
        next_meta["parse_diagnostics"] = diagnostics
    doc.doc_metadata = next_meta
    db.commit()


def _begin_workspace_parse(
    *,
    tenant_id: UUID,
    account_id: str,
    source: _WorkspaceSource,
    parser_backend: str | None,
) -> tuple[str, str]:
    with SessionLocal() as db:
        doc = _get_workspace_document(db, tenant_id=tenant_id, account_id=account_id, document_id=source.id)
        doc.status = "processing"
        doc.processing_progress = 0
        doc.current_stage = "parsing"
        doc.error_message = None
        db.commit()
        db.refresh(doc)
        requested_backend = parser_backend or source.doc_metadata.get("parser_backend_requested") or "auto"
        requested_backend = requested_backend.strip().lower() or "auto"
        file_ext = f".{source.file_type.lower()}"
        try:
            resolved_backend = (
                "auto"
                if file_ext == ".pdf" and requested_backend == "auto"
                else parser_factory.resolve_backend(file_ext, requested_backend)
            )
        except ValueError as exc:
            _persist_workspace_parse_failure(doc=doc, db=db, message=str(exc), diagnostics={})
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return requested_backend, resolved_backend


def _record_workspace_parse_failure(
    *,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    message: str,
    diagnostics: dict[str, Any],
) -> None:
    with SessionLocal() as db:
        _persist_workspace_parse_failure(
            doc=_get_workspace_document(db, tenant_id=tenant_id, account_id=account_id, document_id=document_id),
            db=db,
            message=message,
            diagnostics=diagnostics,
        )


async def _execute_workspace_parse_request(
    *,
    doc: _WorkspaceSource,
    request: Request,
    tenant_id: UUID,
    account_id: str,
    source_path: Path,
    meta: dict[str, Any],
    requested_backend: str,
    resolved_backend: str,
    file_ext: str,
    image_caption_enabled: bool,
    image_ocr_enabled: bool,
    vlm_correction_enabled: bool | None,
) -> ParsingContentResponse:
    initial_backend = resolved_backend
    try:
        started_at = time.perf_counter()
        parsed = await _parse_workspace_source(
            source_path=source_path,
            file_ext=file_ext,
            request=request,
            tenant_id=tenant_id,
            account_id=account_id,
            doc=doc,
            requested_backend=requested_backend,
            resolved_backend=resolved_backend,
            image_caption_enabled=image_caption_enabled,
            image_ocr_enabled=image_ocr_enabled,
        )
        resolved_backend = parsed["resolved_backend"]
        parse_provenance = parsed["provenance"]
        if requested_backend not in {"", "auto"} and resolved_backend != requested_backend:
            await run_blocking_in_thread(
                _fail_workspace_backend_mismatch,
                document_id=doc.id,
                tenant_id=tenant_id,
                account_id=account_id,
                meta=meta,
                requested_backend=requested_backend,
                resolved_backend=resolved_backend,
                parse_provenance=parse_provenance,
            )
        pdf_quality = parsed["pdf_quality"]
        artifact_docs = parsed["documents"]
        elements = _sanitize_storage_value(normalize_document_elements(artifact_docs))
        original_markdown, markdown = _extract_markdown_pair_from_documents(artifact_docs)
        gate = _compute_parsing_quality_gate(
            markdown,
            pdf_quality=pdf_quality,
            min_content_chars=max(0, settings.PARSE_FALLBACK_MIN_CONTENT_CHARS),
            is_pdf=(file_ext == ".pdf"),
        )
        (
            resolved_backend,
            gate,
            artifact_docs,
            original_markdown,
            markdown,
            cross_page_merge_stats,
            fallback_attempts,
        ) = await _run_workspace_pdf_fallbacks(
            request=request,
            tenant_id=tenant_id,
            account_id=account_id,
            doc=doc,
            source_path=source_path,
            file_ext=file_ext,
            requested_backend=requested_backend,
            resolved_backend=resolved_backend,
            gate=gate,
            artifact_docs=artifact_docs,
            original_markdown=original_markdown,
            markdown=markdown,
            pdf_quality=pdf_quality,
        )
        markdown, gate, vlm_audit, vlm_correction_requested = await run_blocking_in_thread(
            _apply_workspace_vlm_correction,
            tenant_id=tenant_id,
            document_id=doc.id,
            file_ext=file_ext,
            artifact_docs=artifact_docs,
            markdown=markdown,
            gate=gate,
            pdf_quality=pdf_quality,
            vlm_correction_enabled=vlm_correction_enabled,
        )
        markdown, captions_added, image_ocr_added, image_ocr_audit = await run_blocking_in_thread(
            _apply_workspace_image_enrichments,
            markdown=markdown,
            source_path=source_path,
            image_caption_enabled=image_caption_enabled,
            image_ocr_enabled=image_ocr_enabled,
        )

        def persist_result() -> ParsingContentResponse:
            with SessionLocal() as worker_db:
                return _persist_workspace_parse_result(
                    db=worker_db,
                    doc=_get_workspace_document(
                        worker_db, tenant_id=tenant_id, account_id=account_id, document_id=doc.id
                    ),
                    tenant_id=tenant_id,
                    meta=meta,
                    requested_backend=requested_backend,
                    resolved_backend=resolved_backend,
                    parse_provenance=parse_provenance,
                    image_caption_enabled=image_caption_enabled,
                    image_ocr_enabled=image_ocr_enabled,
                    vlm_correction_requested=vlm_correction_requested,
                    pdf_quality=pdf_quality,
                    cross_page_merge_stats=cross_page_merge_stats,
                    vlm_audit=vlm_audit,
                    file_ext=file_ext,
                    original_markdown=_strip_storage_nul_chars(original_markdown),
                    markdown=_strip_storage_nul_chars(markdown),
                    gate=gate,
                    elements=elements,
                    duration_sec=max(0.0, time.perf_counter() - started_at),
                    artifact_docs=artifact_docs,
                    captions_added=captions_added,
                    image_ocr_added=image_ocr_added,
                    image_ocr_audit=image_ocr_audit,
                    fallback_attempts=fallback_attempts,
                )

        return await run_blocking_in_thread(persist_result)
    except SubprocessCancelled:
        await run_blocking_in_thread(
            _record_workspace_parse_failure,
            document_id=doc.id,
            tenant_id=tenant_id,
            account_id=account_id,
            message="client_disconnected",
            diagnostics={},
        )
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as exc:
        err_type = exc.details.get("type")
        msg = (str(exc)).strip()
        if not msg:
            details = exc.details
            msg = str(details.get("message") or details.get("type") or exc.__class__.__name__).strip()
        msg = msg[:200]
        logger.error("Subprocess worker failed during workspace parse: %s", msg, exc_info=True)
        diagnostics = await run_blocking_in_thread(
            _build_workspace_parse_diagnostics,
            source_path=source_path,
            file_ext=file_ext,
            requested_backend=requested_backend,
            resolved_backend=initial_backend,
            error_type=err_type,
            error_message=msg,
        )
        await run_blocking_in_thread(
            _record_workspace_parse_failure,
            document_id=doc.id,
            tenant_id=tenant_id,
            account_id=account_id,
            message=msg,
            diagnostics=diagnostics,
        )
        status_code = 400 if err_type == "ValueError" else 500
        raise HTTPException(
            status_code=status_code,
            detail={
                "message": _workspace_failure_detail(message=msg, status_code=status_code),
                "diagnostics": diagnostics,
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        msg = (str(exc)).strip() or exc.__class__.__name__
        msg = msg[:200]
        logger.error("Unexpected error during workspace parse: %s", msg, exc_info=True)
        diagnostics = await run_blocking_in_thread(
            _build_workspace_parse_diagnostics,
            source_path=source_path,
            file_ext=file_ext,
            requested_backend=requested_backend,
            resolved_backend=initial_backend,
            error_type=exc.__class__.__name__,
            error_message=msg,
        )
        await run_blocking_in_thread(
            _record_workspace_parse_failure,
            document_id=doc.id,
            tenant_id=tenant_id,
            account_id=account_id,
            message=msg,
            diagnostics=diagnostics,
        )
        raise HTTPException(
            status_code=500,
            detail={"message": _workspace_failure_detail(message=msg, status_code=500), "diagnostics": diagnostics},
        ) from exc


@router.post(
    "/documents/{document_id}/parse",
    response_model=ParsingContentResponse,
)
async def parse_workspace_document(
    document_id: uuid.UUID,
    request: Request,
    params: Annotated[ParsingDocumentParseQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
):
    """
    Parse a previously uploaded workspace document and persist markdown.
    """
    doc = await run_blocking_in_thread(
        _load_workspace_source,
        tenant_id=tenant_id,
        account_id=account_id,
        document_id=document_id,
    )
    source_path = await _resolve_workspace_source_path(doc=doc, tenant_id=tenant_id)
    cleanup_path = source_path if is_object_storage_uri(doc.file_path.strip()) else None
    try:
        requested_backend, resolved_backend = await run_blocking_in_thread(
            _begin_workspace_parse,
            tenant_id=tenant_id,
            account_id=account_id,
            source=doc,
            parser_backend=params.parser_backend,
        )
        return await _execute_workspace_parse_request(
            doc=doc,
            request=request,
            tenant_id=tenant_id,
            account_id=account_id,
            source_path=source_path,
            meta=doc.doc_metadata,
            requested_backend=requested_backend,
            resolved_backend=resolved_backend,
            file_ext=f".{doc.file_type.lower()}",
            image_caption_enabled=params.image_caption_enabled,
            image_ocr_enabled=params.image_ocr_enabled,
            vlm_correction_enabled=params.vlm_correction_enabled,
        )
    finally:
        if cleanup_path is not None:
            with anyio.fail_after(5.0, shield=True):
                await run_blocking_in_thread(cleanup_path.unlink, missing_ok=True)


@router.get(
    "/documents/{document_id}/content",
    response_model=ParsingContentResponse,
)
def get_parsing_content(
    document_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    doc = _get_workspace_document(db, tenant_id=tenant_id, account_id=account_id, document_id=document_id)
    meta = doc.doc_metadata
    parser_backend = meta.get("parser_backend") or meta.get("parser_backend_requested") or "auto"
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
    pdf_quality = meta.get("pdf_quality")
    quality_gate = meta.get("quality_gate")
    elements = meta.get("elements")
    return ParsingContentResponse(
        document_id=doc.id,
        parser_backend=str(parser_backend),
        markdown_content=(row.markdown_content if row else ""),
        original_markdown_content=(row.original_markdown_content if row else ""),
        stats=stats,
        parse_duration_sec=meta.get("parse_duration_sec"),
        pdf_quality=(dict(pdf_quality) if isinstance(pdf_quality, dict) else None),
        quality_gate=(ParsingQualityGate(**quality_gate) if isinstance(quality_gate, dict) else None),
        elements=(list(elements) if isinstance(elements, list) else None),
    )


@router.patch(
    "/documents/{document_id}/content",
    response_model=ParsingContentResponse,
)
def update_parsing_content(
    document_id: uuid.UUID,
    payload: ParsingContentUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    doc = _get_workspace_document(db, tenant_id=tenant_id, account_id=account_id, document_id=document_id)
    ds = dataset_service.get_dataset(db, tenant_id, doc.dataset_id)
    dataset_service.assert_dataset_writable(db, ds, account_id)

    markdown = _strip_storage_nul_chars(payload.markdown_content)
    row = (
        db.query(DocumentParsedContent)
        .filter(DocumentParsedContent.document_id == doc.id, DocumentParsedContent.tenant_id == tenant_id)
        .first()
    )
    original = payload.original_markdown_content
    if original is None:
        # Keep original if not explicitly provided.
        original = row.original_markdown_content if row is not None else markdown
    original = _strip_storage_nul_chars(original)
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

    next_meta = dict(doc.doc_metadata)
    next_meta["workspace"] = "parsing"
    next_meta["edited"] = True
    doc.doc_metadata = _sanitize_storage_value(next_meta)

    db.commit()
    db.refresh(doc)

    parser_backend = next_meta.get("parser_backend") or next_meta.get("parser_backend_requested") or "auto"
    elements = next_meta.get("elements")

    return ParsingContentResponse(
        document_id=doc.id,
        parser_backend=str(parser_backend),
        markdown_content=markdown,
        original_markdown_content=original,
        parse_duration_sec=next_meta.get("parse_duration_sec"),
        elements=(list(elements) if isinstance(elements, list) else None),
    )


@router.delete("/documents/{document_id}", status_code=204)
def delete_parsing_document(
    document_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    doc = _get_workspace_document(db, tenant_id=tenant_id, account_id=account_id, document_id=document_id)
    ds = dataset_service.get_dataset(db, tenant_id, doc.dataset_id)
    dataset_service.assert_dataset_writable(db, ds, account_id)

    # Best-effort delete source file.
    with contextlib.suppress(Exception):
        raw_path = doc.file_path.strip()
        if raw_path and not raw_path.startswith("manual://"):
            if is_object_storage_uri(raw_path):
                store, ref = resolve_document_object_reference(
                    raw_path,
                    tenant_id=tenant_id,
                    dataset_id=doc.dataset_id,
                    document_id=doc.id,
                    file_type=doc.file_type,
                    document_metadata=doc.doc_metadata,
                )
                store.delete_object(object_name=ref.object_name)
            else:
                file_path = Path(raw_path).resolve(strict=False)
                _assert_path_under_tenant_root(tenant_id=tenant_id, path=file_path)
                if file_path.exists() and file_path.is_file():
                    file_path.unlink()

    db.delete(doc)
    db.commit()
    return None
