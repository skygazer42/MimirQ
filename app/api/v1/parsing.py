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

import asyncio
import contextlib
import hashlib
import json
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, model_validator
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
from app.services.dataset_service import DatasetService
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


class ParsingContentUpdateRequest(BaseModel):
    markdown_content: str = Field(default="")
    original_markdown_content: str | None = None


class ParsingExtractFieldSpec(BaseModel):
    type: Literal["string"] = "string"
    source_kind: str | None = None
    source_visual_kind: str | None = None
    aliases: list[str] = Field(default_factory=list)


class ParsingExtractRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mode: Literal["schema", "prompt"] = "schema"
    schema_: dict[str, ParsingExtractFieldSpec] | None = None
    prompt: str | None = None
    field_hints: dict[str, ParsingExtractFieldSpec] | None = None
    max_evidence: int = Field(default=1, ge=1, le=5)

    @model_validator(mode="before")
    @classmethod
    def _coerce_schema_alias(cls, value: Any):  # noqa: ANN001
        if not isinstance(value, dict):
            return value
        if "schema_" not in value and "schema" in value:
            copied = dict(value)
            copied["schema_"] = copied.get("schema")
            return copied
        return value

    @property
    def schema(self) -> dict[str, ParsingExtractFieldSpec] | None:
        return self.schema_


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


def _strip_storage_nul_chars(value: str) -> str:
    """PostgreSQL text/jsonb cannot store NUL bytes; OCR backends may emit them."""
    if not value:
        return ""
    return value.replace("\x00", "")


def _sanitize_storage_value(value: Any) -> Any:
    if isinstance(value, str):
        return _strip_storage_nul_chars(value)
    if isinstance(value, list):
        return [_sanitize_storage_value(item) for item in value]
    if isinstance(value, dict):
        return {_strip_storage_nul_chars(str(key)): _sanitize_storage_value(item) for key, item in value.items()}
    return value


def _extract_markdown_pair_from_documents(documents: list[dict[str, Any]] | None) -> tuple[str, str]:
    original_parts: list[str] = []
    cleaned_parts: list[str] = []
    has_position_tagged_override = False

    for item in documents or []:
        if not isinstance(item, dict):
            continue

        page_content = _strip_storage_nul_chars(str(item.get("page_content") or ""))
        cleaned_parts.append(page_content)

        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            tagged = metadata.get("position_tagged_markdown")
            if isinstance(tagged, str) and tagged.strip():
                has_position_tagged_override = True
                original_parts.append(_strip_storage_nul_chars(tagged))
                continue

        original_parts.append(page_content)

    original = _strip_storage_nul_chars("\n\n".join(original_parts).strip())
    if has_position_tagged_override:
        cleaned = _strip_storage_nul_chars("\n\n".join(cleaned_parts).strip())
    else:
        cleaned = _strip_storage_nul_chars(_strip_position_tags(original).strip())

    return original, cleaned


def _should_inline_preview_parse(file_ext: str) -> bool:
    if not bool(getattr(settings, "PREVIEW_INLINE_TEXT_PARSE_ENABLED", True)):
        return False
    ext = str(file_ext or "").strip().lower()
    return ext == ".md" or ext in parser_factory.PLAIN_TEXT_EXTENSIONS


def _serialize_inline_parse_documents(documents: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for doc in documents or []:
        metadata = getattr(doc, "metadata", None) or {}
        out.append(
            {
                "page_content": str(getattr(doc, "page_content", "") or ""),
                "metadata": _sanitize_storage_value(metadata if isinstance(metadata, dict) else {}),
                "id": str(getattr(doc, "id", "") or "") or None,
            }
        )
    return out


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
    if isinstance(provenance, dict):
        provenance = dict(provenance)
        provenance.setdefault("payload_requested_backend", str(requested_backend or ""))
        provenance.setdefault("effective_backend", str(resolved_backend or ""))
        provenance.setdefault("execution_mode", "inline_text_preview")
    return {
        "resolved_backend": inline_backend,
        "pdf_quality": None,
        "documents": _serialize_inline_parse_documents(documents),
        "provenance": _sanitize_storage_value(provenance),
    }


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


def _dump_extract_field_spec_map(
    spec_map: dict[str, ParsingExtractFieldSpec] | None,
) -> dict[str, dict[str, Any]] | None:
    if not spec_map:
        return None
    return {key: value.model_dump(exclude_none=True) for key, value in spec_map.items()}


@router.post(
    "/documents/{document_id}/extract",
    response_model=ParsingExtractResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
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
    meta = dict(doc.doc_metadata or {})
    row = (
        db.query(DocumentParsedContent)
        .filter(DocumentParsedContent.document_id == doc.id, DocumentParsedContent.tenant_id == tenant_id)
        .first()
    )
    markdown = ""
    if row is not None:
        markdown = str(getattr(row, "markdown_content", "") or getattr(row, "original_markdown_content", "") or "")
    elements = meta.get("elements") if isinstance(meta.get("elements"), list) else []
    result = extract_parsing_fields(
        markdown=markdown,
        elements=list(elements or []),
        mode=payload.mode,
        schema=_dump_extract_field_spec_map(payload.schema),
        prompt=payload.prompt,
        field_hints=_dump_extract_field_spec_map(payload.field_hints),
        max_evidence=int(payload.max_evidence or 1),
    )
    return ParsingExtractResponse(
        document_id=document_id,
        mode=payload.mode,
        result={key: ParsingExtractFieldResult(**value) for key, value in result.items()},
    )


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return float(int(value))
        f = float(value)
        if f != f:  # NaN
            return None
        return float(f)
    except Exception:
        return None


def _coerce_int(value: Any) -> int:
    try:
        if value is None or isinstance(value, bool):
            return 0
        return int(value)
    except Exception:
        return 0


def _count_to_score(count: int, *, scale: int) -> float:
    """
    Turn a non-negative count into a bounded [0..1] score (saturating).

    Examples (scale=3):
      0 -> 0.0
      1 -> 0.25
      3 -> 0.5
      9 -> 0.75
    """
    c = max(0, int(count or 0))
    s = max(1, int(scale or 1))
    return round(float(c) / float(c + s), 4)


def _load_competition_weights() -> dict[str, float] | None:
    """
    Parse weights JSON (Opt 8) from settings, with a safe default.
    """
    if not bool(getattr(settings, "PARSE_COMPETITION_MATRIX_ENABLED", False)):
        return None

    raw = str(getattr(settings, "PARSE_COMPETITION_MATRIX_WEIGHTS_JSON", "") or "").strip()
    if raw:
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and obj:
                return {str(k): float(v) for k, v in obj.items()}
        except Exception:
            return None

    # Balanced defaults for parser competition scoring.
    return {"text": 0.40, "table": 0.30, "image": 0.15, "reading_order": 0.15}


def _append_pdf_fallback_candidate(candidates: list[str], *, name: str, enabled: bool) -> None:
    if enabled:
        candidates.append(name)


def _magicpdf_fallback_available() -> bool:
    if not bool(getattr(settings, "MAGIC_PDF_ENABLED", False)):
        return False
    if magicpdf_service_configured(getattr(settings, "MAGIC_PDF_API_URL", "")):
        return True
    cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
    models_dir = resolve_magicpdf_models_dir(getattr(settings, "MAGIC_PDF_MODELS_DIR", ""))
    return bool(resolve_cli_command(cli) and models_dir)


def _build_pdf_fallback_candidates() -> list[str]:
    """
    Best-effort fallback order for PDF auto parsing.

    Keep it conservative: we only include backends that appear enabled/configured.
    """
    candidates: list[str] = []

    _append_pdf_fallback_candidate(
        candidates,
        name="mineru",
        enabled=bool(getattr(settings, "MINERU_ENABLED", False))
        and bool(getattr(settings, "MINERU_API_TOKEN", None) or getattr(settings, "MINERU_LOCAL_SERVER_URL", None)),
    )
    _append_pdf_fallback_candidate(
        candidates,
        name="deepseek_ocr",
        enabled=bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False))
        and bool((getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip()),
    )
    _append_pdf_fallback_candidate(
        candidates,
        name="qianfan_ocr",
        enabled=bool(getattr(settings, "QIANFAN_OCR_ENABLED", False))
        and bool((getattr(settings, "QIANFAN_OCR_API_URL", "") or "").strip()),
    )
    _append_pdf_fallback_candidate(
        candidates,
        name="etl4llm",
        enabled=bool(getattr(settings, "ETL4LLM_ENABLED", False))
        and bool((getattr(settings, "ETL4LLM_API_URL", "") or "").strip()),
    )
    _append_pdf_fallback_candidate(
        candidates,
        name="deepdoc",
        enabled=bool(getattr(settings, "DEEPDOC_ENABLED", False)),
    )
    _append_pdf_fallback_candidate(
        candidates,
        name="docling",
        enabled=bool(getattr(settings, "DOCLING_ENABLED", False)),
    )

    # MagicPDF prefers service mode; local CLI remains a fallback.
    try:
        _append_pdf_fallback_candidate(
            candidates,
            name="magicpdf",
            enabled=_magicpdf_fallback_available(),
        )
    except Exception as exc:
        logger.debug(_PARSING_ROUTER_FALLBACK_LOG_MESSAGE, exc)

    _append_pdf_fallback_candidate(
        candidates,
        name="markitdown",
        enabled=bool(getattr(settings, "MARKITDOWN_ENABLED", False)),
    )

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
    existing = db.query(Dataset).filter(Dataset.tenant_id == tenant_id, Dataset.owner_id == account_id).all()
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
    owner_tag = hashlib.blake2b(owner_raw.encode("utf-8"), digest_size=4).hexdigest() if owner_raw else "anon"
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

    doc = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
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


def _filter_parsing_workspace_documents(query):
    """Keep parsing workspace list semantics aligned with workspace detail endpoints."""
    return query.filter(DBDocument.doc_metadata["workspace"].astext == "parsing")  # type: ignore[attr-defined]


@router.get("/documents", response_model=DocumentList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_parsing_documents(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    status: str | None = None,
    dataset_id: Annotated[UUID | None, Query()] = None,
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

    if dataset_id is not None:
        target_dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_readable(db, target_dataset, account_id)
        query = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id)
        query = query.filter(DBDocument.doc_metadata["target_dataset_id"].astext == str(dataset_id))  # type: ignore[attr-defined]
    else:
        query = db.query(DBDocument).filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset.id,
        )
    query = _filter_parsing_workspace_documents(query)

    if status and status != "all":
        query = query.filter(DBDocument.status == status)

    total = query.count()
    items = query.order_by(DBDocument.created_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "items": items}


@router.post("/documents", response_model=DocumentDetail, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def upload_parsing_document(
    file: Annotated[UploadFile, File(...)],
    parser_backend: Annotated[str, Form()] = "auto",
    dataset_id: Annotated[UUID | None, Form()] = None,
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
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )

    dataset = _get_or_create_workspace_dataset(db, tenant_id, account_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)
    target_dataset: Dataset | None = None
    if dataset_id is not None:
        target_dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_writable(db, target_dataset, account_id)

    document_id = uuid.uuid4()

    use_object_storage = document_object_storage_enabled()

    if use_object_storage:
        upload_dir = (Path(settings.UPLOAD_DIR) / str(tenant_id) / ".tmp").resolve(strict=False)
    else:
        upload_dir = _parsing_upload_dir(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    source_path = upload_dir / f"{document_id}{file_ext}"

    file_size = int(await save_upload_file(file, source_path, max_bytes=settings.MAX_FILE_SIZE) or 0)

    if not use_object_storage:
        _assert_path_under_tenant_root(tenant_id=tenant_id, path=source_path)

    meta = {
        "workspace": "parsing",
        "parser_backend_requested": (parser_backend or "").strip().lower() or "auto",
    }
    if target_dataset is not None:
        meta["target_dataset_id"] = str(target_dataset.id)
        meta["target_dataset_name"] = str(target_dataset.name or target_dataset.id)

    stored_path = str(source_path)
    if use_object_storage:
        store = get_document_object_store()
        if store is None:
            raise HTTPException(status_code=503, detail="Object storage is disabled")
        try:
            stored_path = store.upload_document_file(
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
        if is_object_storage_uri(stored_path):
            meta.update(document_object_store_metadata(store))

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


async def _resolve_workspace_source_path(
    *,
    doc: DBDocument,
    tenant_id: UUID,
) -> Path:
    raw_path = str(doc.file_path or "").strip()
    if not raw_path or raw_path.startswith("manual://"):
        raise HTTPException(status_code=404, detail="Source file not available")
    if not is_object_storage_uri(raw_path):
        source_path = Path(raw_path).resolve(strict=False)
        _assert_path_under_tenant_root(tenant_id=tenant_id, path=source_path)
        if not source_path.exists() or not source_path.is_file():
            raise HTTPException(status_code=404, detail=_DETAIL_SOURCE_FILE_NOT_FOUND)
        return source_path

    try:
        store, ref = resolve_document_object_reference(
            raw_path,
            tenant_id=tenant_id,
            dataset_id=doc.dataset_id,
            document_id=doc.id,
            file_type=doc.file_type,
            document_metadata=dict(getattr(doc, "doc_metadata", None) or {}),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Object storage is disabled") from exc
    except ValueError as exc:
        if str(exc) in {"object_bucket_denied", "object_key_denied"}:
            raise HTTPException(status_code=403, detail="Source file access denied") from exc
        raise HTTPException(status_code=404, detail=_DETAIL_SOURCE_FILE_NOT_FOUND) from exc

    try:
        store.stat_object(object_name=ref.object_name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=_DETAIL_SOURCE_FILE_NOT_FOUND) from exc

    temp_dir = (Path(settings.UPLOAD_DIR) / str(tenant_id) / ".tmp").resolve(strict=False)
    suffix = f".{(doc.file_type or '').lower()}"
    temp_path = temp_dir / f"{doc.id}.{uuid.uuid4().hex}{suffix}"
    await asyncio.to_thread(
        store.download_object_to_path,
        object_name=ref.object_name,
        destination=temp_path,
        max_bytes=int(getattr(settings, "MAX_FILE_SIZE", 0) or 0),
    )
    return temp_path


def _set_workspace_parse_processing(doc: DBDocument, db: Session) -> None:
    doc.status = "processing"
    doc.processing_progress = 0
    doc.current_stage = "parsing"
    doc.error_message = None
    db.commit()
    db.refresh(doc)


def _resolve_workspace_requested_backend(meta: Any, parser_backend: str | None) -> str:
    if isinstance(meta, dict):
        requested_backend = parser_backend or meta.get("parser_backend_requested") or "auto"
    else:
        requested_backend = parser_backend or "auto"
    return str(requested_backend or "").strip().lower() or "auto"


def _resolve_workspace_backend(*, file_ext: str, requested_backend: str) -> str:
    if file_ext == ".pdf" and requested_backend in {"", "auto"}:
        return "auto"
    return parser_factory.resolve_backend(file_ext, requested_backend)


def _fail_workspace_backend_mismatch(
    *,
    doc: DBDocument,
    db: Session,
    meta: Any,
    requested_backend: str,
    resolved_backend: str,
    parse_provenance: dict[str, Any] | None,
) -> None:
    diagnostics = _sanitize_storage_value(
        {
            "requested_backend": requested_backend,
            "resolved_backend": resolved_backend,
            "provenance": parse_provenance or {},
        }
    )
    msg = f"Requested parser backend '{requested_backend}' fell back to '{resolved_backend}'"
    doc.status = "failed"
    doc.processing_progress = 0
    doc.current_stage = "failed"
    doc.error_message = msg
    next_meta = dict(meta) if isinstance(meta, dict) else {}
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
    doc: DBDocument,
    requested_backend: str,
    resolved_backend: str,
    image_caption_enabled: bool,
    image_ocr_enabled: bool,
) -> dict[str, Any]:
    optional_image_enrichment = bool(image_caption_enabled) or bool(image_ocr_enabled)
    if _should_inline_preview_parse(file_ext) and not optional_image_enrichment:
        return _parse_inline_text_preview(
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
            "account_id": str(account_id),
            "dataset_id": str(doc.dataset_id),
            "document_id": str(doc.id),
            "file_path": str(source_path),
            "parser_backend": resolved_backend,
            "mode": "preview",
        },
        disconnect_check=request.is_disconnected,
        timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
    )


def _workspace_cross_page_merge_stats(artifact_docs: Any) -> dict[str, int] | None:
    if not artifact_docs or not bool(getattr(settings, "CROSS_PAGE_MERGE_ENABLED", False)):
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
    artifact_docs: Any,
    original_markdown: str,
    markdown: str,
    pdf_quality: dict[str, Any] | None,
    file_ext: str,
    matrix_weights: dict[str, float] | None,
    cross_page_merge_stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    parse_score = _coerce_float(((gate.evidence or {}).get("parse_quality") or {}).get("score"))
    content_chars = _coerce_int(((gate.evidence or {}).get("text_quality") or {}).get("content_chars"))
    stats = compute_parsing_artifact_stats(
        documents=artifact_docs,
        original_markdown=original_markdown,
        markdown=markdown,
        pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
    )
    ro = score_reading_order(original_markdown) if file_ext == ".pdf" else None
    ro_score = _coerce_float((ro or {}).get("score")) if isinstance(ro, dict) else None
    attempt: dict[str, Any] = {
        "backend": str(backend or "").strip(),
        "grade": gate.grade,
        "parse_score": parse_score,
        "content_chars": content_chars,
        "text_score": parse_score,
        "table_score": _count_to_score(_coerce_int(stats.get("table_count")), scale=3),
        "image_score": _count_to_score(_coerce_int(stats.get("image_count")), scale=5),
        "reading_order_score": ro_score,
        "artifact_stats": stats,
        "reading_order": ro,
        "cross_page_merge_stats": (
            dict(cross_page_merge_stats or {}) if isinstance(cross_page_merge_stats, dict) else None
        ),
        "artifact_docs": artifact_docs,
        "original_markdown": original_markdown,
        "markdown": markdown,
        "gate": gate,
    }
    if matrix_weights:
        attempt["matrix_score"] = round(float(compute_competition_matrix_score(attempt, weights=matrix_weights)), 4)
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
    doc: DBDocument,
    source_path: Path,
    request: Request,
    file_ext: str,
    initial_backend: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        cand_backend = parser_factory.resolve_backend(file_ext, candidate)
    except Exception as exc:  # noqa: BLE001
        return None, {
            "from": resolved_backend,
            "to": candidate,
            "accepted": False,
            "error": f"invalid_backend:{str(exc)[:120]}",
        }

    try:
        alt_parsed = await run_subprocess_worker(
            tenant_id=tenant_id,
            payload={
                "action": "parse_documents",
                "tenant_id": str(tenant_id),
                "account_id": str(account_id),
                "dataset_id": str(doc.dataset_id),
                "document_id": str(doc.id),
                "file_path": str(source_path),
                "parser_backend": cand_backend,
                "mode": "preview",
                "pdf_quality": dict(pdf_quality) if isinstance(pdf_quality, dict) else None,
            },
            disconnect_check=request.is_disconnected,
            timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
        )
    except Exception as exc:  # noqa: BLE001
        return None, {"from": resolved_backend, "to": cand_backend, "accepted": False, "error": str(exc)[:200]}

    alt_artifact_docs = alt_parsed.get("documents") if isinstance(alt_parsed, dict) else None
    alt_cross_page_merge_stats = _workspace_cross_page_merge_stats(alt_artifact_docs)
    alt_backend = str(alt_parsed.get("resolved_backend") or cand_backend)
    alt_original, alt_markdown = _extract_markdown_pair_from_documents(alt_artifact_docs)
    alt_gate = _compute_parsing_quality_gate(
        alt_markdown,
        pdf_quality=pdf_quality,
        min_content_chars=min_chars,
        is_pdf=True,
    )
    return (
        {
            "from": initial_backend,
            "to": alt_backend,
            "quality_before": gate.evidence.get("text_quality"),
            "quality_after": alt_gate.evidence.get("text_quality"),
            "grade_before": gate.grade,
            "grade_after": alt_gate.grade,
            "parse_score_before": ((gate.evidence or {}).get("parse_quality") or {}).get("score"),
            "parse_score_after": ((alt_gate.evidence or {}).get("parse_quality") or {}).get("score"),
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
    doc: DBDocument,
    source_path: Path,
    file_ext: str,
    requested_backend: str,
    resolved_backend: str,
    gate: ParsingQualityGate,
    artifact_docs: Any,
    original_markdown: str,
    markdown: str,
    pdf_quality: dict[str, Any] | None,
) -> tuple[str, ParsingQualityGate, Any, str, str, dict[str, int] | None, list[dict[str, Any]]]:
    min_chars = max(0, int(getattr(settings, "PARSE_FALLBACK_MIN_CONTENT_CHARS", 120) or 120))
    min_parse_score = max(0.0, float(getattr(settings, "PARSE_FALLBACK_MIN_PARSE_SCORE", 0.55) or 0.55))
    max_retries = max(0, int(getattr(settings, "PARSE_FALLBACK_MAX_RETRIES", 1) or 1))
    matrix_weights = _load_competition_weights()
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
    gate_parse_score = _coerce_float(((gate.evidence or {}).get("parse_quality") or {}).get("score"))
    gate_content_chars = _coerce_int(((gate.evidence or {}).get("text_quality") or {}).get("content_chars"))
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

    retries_left = int(max_retries)
    filtered_candidates = [
        item for item in _build_pdf_fallback_candidates() if item != (resolved_backend or "").strip().lower()
    ]
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
            initial_backend=resolved_backend,
        )
        if attempt_entry is not None:
            fallback_attempts.append(attempt_entry)
        if candidate_state is None:
            continue
        attempt_candidates.append(
            _build_workspace_parse_attempt(
                backend=str(candidate_state["backend"]),
                gate=candidate_state["gate"],
                artifact_docs=candidate_state["artifact_docs"],
                original_markdown=str(candidate_state["original_markdown"]),
                markdown=str(candidate_state["markdown"]),
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
    selected_backend = str(best.get("backend") or "").strip() or resolved_backend
    best_gate = best.get("gate") or gate
    best_cross_page = best.get("cross_page_merge_stats")
    next_cross_page = dict(best_cross_page) if isinstance(best_cross_page, dict) else cross_page_merge_stats
    for attempt in fallback_attempts:
        attempt["selected"] = str(attempt.get("to") or "") == selected_backend
    if fallback_attempts:
        best_gate = ParsingQualityGate(
            grade=best_gate.grade,
            reasons=list(best_gate.reasons or []),
            evidence={
                **(best_gate.evidence or {}),
                "fallback_attempts": fallback_attempts,
                "fallback_initial_backend": resolved_backend,
                "fallback_final_backend": selected_backend,
                "fallback_selected_backend": selected_backend,
                "fallback_max_retries": int(max_retries),
            },
        )
    return (
        selected_backend,
        best_gate,
        best.get("artifact_docs") if best.get("artifact_docs") is not None else artifact_docs,
        str(best.get("original_markdown") or original_markdown),
        str(best.get("markdown") or markdown),
        next_cross_page,
        fallback_attempts,
    )


def _apply_workspace_vlm_correction(
    *,
    tenant_id: UUID,
    document_id: UUID,
    file_ext: str,
    artifact_docs: Any,
    markdown: str,
    gate: ParsingQualityGate,
    pdf_quality: dict[str, Any] | None,
    vlm_correction_enabled: bool | None,
) -> tuple[str, ParsingQualityGate, dict[str, Any] | None, bool]:
    vlm_correction_requested = (
        bool(getattr(settings, "VLM_CORRECTION_ENABLED", False))
        if vlm_correction_enabled is None
        else bool(vlm_correction_enabled)
    )
    if file_ext != ".pdf" or not vlm_correction_requested:
        return markdown, gate, None, vlm_correction_requested
    try:
        pages = [
            _strip_position_tags(str(item.get("page_content") or "") if isinstance(item, dict) else "")
            for item in (artifact_docs or [])
            if isinstance(item, dict)
        ]
        corrected_pages, audit = maybe_correct_markdown_pages(
            pages,
            enabled=True,
            api_url=str(getattr(settings, "VLM_CORRECTION_API_URL", "") or ""),
            timeout_sec=float(getattr(settings, "VLM_CORRECTION_TIMEOUT_SEC", 60) or 60),
            max_pages=int(getattr(settings, "VLM_CORRECTION_MAX_PAGES", 3) or 3),
            max_chars=int(getattr(settings, "VLM_CORRECTION_MAX_CHARS", 40_000) or 40_000),
            pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
            min_table_quality=float(getattr(settings, "VLM_CORRECTION_MIN_TABLE_QUALITY", 0.6) or 0.6),
            meta={"tenant_id": str(tenant_id), "document_id": str(document_id)},
        )
        vlm_audit = audit.to_dict()
        if len(corrected_pages) != len(pages) or not corrected_pages:
            evidence = dict(gate.evidence or {})
            evidence["vlm_correction"] = {"schema": _VLM_CORRECTION_SCHEMA, **vlm_audit}
            return (
                markdown,
                ParsingQualityGate(
                    grade=gate.grade,
                    reasons=list(gate.reasons or []),
                    evidence=evidence,
                ),
                vlm_audit,
                vlm_correction_requested,
            )
        markdown = _strip_storage_nul_chars("\n\n".join([str(page or "") for page in corrected_pages]).strip())
        gate_after = _compute_parsing_quality_gate(
            markdown,
            pdf_quality=pdf_quality,
            min_content_chars=max(0, int(getattr(settings, "PARSE_FALLBACK_MIN_CONTENT_CHARS", 120) or 120)),
            is_pdf=True,
        )
        next_evidence = dict(gate_after.evidence or {})
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
            if key in (gate.evidence or {}):
                next_evidence[key] = (gate.evidence or {}).get(key)
        next_evidence["vlm_correction"] = {"schema": _VLM_CORRECTION_SCHEMA, **vlm_audit}
        next_gate = ParsingQualityGate(
            grade=gate_after.grade,
            reasons=list(gate_after.reasons or []),
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
                max_images=max(0, int(getattr(settings, "IMAGE_OCR_MAX_IMAGES", 20) or 20)),
                max_ocr_chars=max(0, int(getattr(settings, "IMAGE_OCR_MAX_CHARS", 2000) or 2000)),
            )
            image_ocr_audit = audit.to_dict()
            markdown = _strip_storage_nul_chars(markdown)
        except Exception:
            image_ocr_added = 0
            image_ocr_audit = None
    return markdown, captions_added, image_ocr_added, image_ocr_audit


def _build_workspace_parse_metadata(
    *,
    meta: Any,
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
    gate: ParsingQualityGate | None,
    elements: Any,
    duration_sec: float,
    artifact_stats: dict[str, int],
    fallback_attempts: list[dict[str, Any]],
) -> tuple[dict[str, Any], ParsingQualityGate | None]:
    next_meta = dict(meta) if isinstance(meta, dict) else {}
    next_meta["workspace"] = "parsing"
    next_meta["parser_backend_requested"] = requested_backend
    next_meta["parser_backend"] = resolved_backend
    if isinstance(parse_provenance, dict) and parse_provenance:
        next_meta["parse_provenance"] = parse_provenance
    _apply_workspace_enrichment_metadata(
        next_meta,
        image_caption_enabled=image_caption_enabled,
        captions_added=captions_added,
        image_ocr_enabled=image_ocr_enabled,
        image_ocr_added=image_ocr_added,
        image_ocr_audit=image_ocr_audit,
        vlm_correction_requested=vlm_correction_requested,
        pdf_quality=pdf_quality,
        cross_page_merge_stats=cross_page_merge_stats,
        vlm_audit=vlm_audit,
    )
    gate = _apply_workspace_quality_metadata(
        next_meta,
        file_ext=file_ext,
        original_markdown=original_markdown,
        gate=gate,
        elements=elements,
        duration_sec=duration_sec,
        artifact_stats=artifact_stats,
        fallback_attempts=fallback_attempts,
    )
    return _sanitize_storage_value(next_meta), gate


def _apply_workspace_enrichment_metadata(
    next_meta: dict[str, Any],
    *,
    image_caption_enabled: bool,
    captions_added: int,
    image_ocr_enabled: bool,
    image_ocr_added: int,
    image_ocr_audit: dict[str, Any] | None,
    vlm_correction_requested: bool,
    pdf_quality: dict[str, Any] | None,
    cross_page_merge_stats: dict[str, int] | None,
    vlm_audit: dict[str, Any] | None,
) -> None:
    next_meta["image_caption_enabled"] = bool(image_caption_enabled)
    if image_caption_enabled:
        next_meta["image_captions_added"] = int(captions_added)
    next_meta["image_ocr_enabled"] = bool(image_ocr_enabled)
    if image_ocr_enabled:
        next_meta["image_ocr_added"] = int(image_ocr_added)
        if isinstance(image_ocr_audit, dict) and image_ocr_audit:
            next_meta["image_ocr"] = {"schema": "mimirq.image_ocr.v1", **image_ocr_audit}
    next_meta["vlm_correction_enabled"] = bool(vlm_correction_requested)
    if isinstance(pdf_quality, dict) and pdf_quality:
        next_meta["pdf_quality"] = dict(pdf_quality)
    if isinstance(cross_page_merge_stats, dict) and cross_page_merge_stats:
        next_meta["cross_page_merge"] = {
            "schema": "mimirq.cross_page_merge.v1",
            "enabled": True,
            **cross_page_merge_stats,
        }
    if isinstance(vlm_audit, dict) and vlm_audit:
        next_meta["vlm_correction"] = {"schema": _VLM_CORRECTION_SCHEMA, **vlm_audit}


def _apply_workspace_quality_metadata(
    next_meta: dict[str, Any],
    *,
    file_ext: str,
    original_markdown: str,
    gate: ParsingQualityGate | None,
    elements: Any,
    duration_sec: float,
    artifact_stats: dict[str, int],
    fallback_attempts: list[dict[str, Any]],
) -> ParsingQualityGate | None:
    try:
        ro = score_reading_order(original_markdown) if file_ext == ".pdf" else None
    except Exception:
        ro = None
    if isinstance(ro, dict) and ro:
        next_meta["reading_order"] = ro
    if gate is not None:
        next_meta["quality_gate"] = gate.model_dump()
        gate_evidence = dict(gate.evidence or {})
        if isinstance(gate_evidence.get("parse_quality"), dict):
            next_meta["parse_quality"] = dict(gate_evidence.get("parse_quality") or {})
        if isinstance(gate_evidence.get("text_quality"), dict):
            next_meta["parsed_text_quality"] = dict(gate_evidence.get("text_quality") or {})
    next_meta["elements"] = list(elements or [])
    next_meta["parsed_at"] = datetime.now(UTC).isoformat()
    next_meta["parse_duration_sec"] = round(float(duration_sec), 3)
    if fallback_attempts:
        next_meta["parse_fallback"] = {
            "attempts": fallback_attempts,
            "min_content_chars": max(
                0,
                int(getattr(settings, "PARSE_FALLBACK_MIN_CONTENT_CHARS", 120) or 120),
            ),
            "max_retries": max(
                0,
                int(getattr(settings, "PARSE_FALLBACK_MAX_RETRIES", 1) or 1),
            ),
        }
    next_meta.update(artifact_stats)
    next_meta.update(apply_parse_quality_gate_metadata(next_meta))
    if gate is not None:
        gate_evidence = dict(gate.evidence or {})
        gate_evidence["parse_quality_gate"] = dict(next_meta.get("parse_quality_gate") or {})
        gate = ParsingQualityGate(
            grade=gate.grade,
            reasons=list(gate.reasons or []),
            evidence=gate_evidence,
        )
        next_meta["quality_gate"] = gate.model_dump()
    return gate


def _persist_workspace_parse_result(
    *,
    db: Session,
    doc: DBDocument,
    tenant_id: UUID,
    meta: Any,
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
    gate: ParsingQualityGate | None,
    elements: Any,
    duration_sec: float,
    artifact_docs: Any,
    captions_added: int,
    image_ocr_added: int,
    image_ocr_audit: dict[str, Any] | None,
    fallback_attempts: list[dict[str, Any]],
) -> ParsingContentResponse:
    artifact_stats = compute_parsing_artifact_stats(
        documents=artifact_docs,
        original_markdown=original_markdown,
        markdown=markdown,
        pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
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
        parse_duration_sec=round(float(duration_sec), 3),
        pdf_quality=(dict(pdf_quality) if isinstance(pdf_quality, dict) else None),
        quality_gate=gate,
        elements=list(elements or []),
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
    error_type: str,
    error_message: str,
) -> dict[str, Any]:
    try:
        return build_parse_failure_diagnostics(
            file_path=Path(str(source_path)),
            file_ext=str(file_ext),
            parser_backend_requested=str(requested_backend),
            parser_backend_resolved=str(resolved_backend),
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
    try:
        next_meta = dict(doc.doc_metadata if isinstance(doc.doc_metadata, dict) else {})
        if diagnostics:
            next_meta["parse_diagnostics"] = diagnostics
        doc.doc_metadata = next_meta
    except Exception as exc:
        logger.debug(_PARSING_ROUTER_FALLBACK_LOG_MESSAGE, exc)
    db.commit()


async def _execute_workspace_parse_request(
    *,
    db: Session,
    doc: DBDocument,
    request: Request,
    tenant_id: UUID,
    account_id: str,
    source_path: Path,
    cleanup_path: Path | None,
    meta: Any,
    requested_backend: str,
    resolved_backend: str,
    file_ext: str,
    image_caption_enabled: bool,
    image_ocr_enabled: bool,
    vlm_correction_enabled: bool | None,
) -> ParsingContentResponse:
    try:
        return await _run_workspace_parse_pipeline(
            db=db,
            doc=doc,
            request=request,
            tenant_id=tenant_id,
            account_id=account_id,
            source_path=source_path,
            meta=meta,
            requested_backend=requested_backend,
            resolved_backend=resolved_backend,
            file_ext=file_ext,
            image_caption_enabled=image_caption_enabled,
            image_ocr_enabled=image_ocr_enabled,
            vlm_correction_enabled=vlm_correction_enabled,
        )
    except SubprocessCancelled:
        _persist_workspace_parse_failure(
            doc=doc,
            db=db,
            message="client_disconnected",
            diagnostics={},
        )
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as exc:
        err_type = str((exc.details or {}).get("type") or "")
        msg = (str(exc) or "").strip()
        if not msg:
            details = exc.details or {}
            msg = str(details.get("message") or details.get("type") or exc.__class__.__name__).strip()
        msg = msg[:200]
        logger.error("Subprocess worker failed during workspace parse: %s", msg)
        diagnostics = _build_workspace_parse_diagnostics(
            source_path=source_path,
            file_ext=file_ext,
            requested_backend=requested_backend,
            resolved_backend=resolved_backend,
            error_type=err_type,
            error_message=msg,
        )
        _persist_workspace_parse_failure(doc=doc, db=db, message=msg, diagnostics=diagnostics)
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
        msg = (str(exc) or "").strip() or exc.__class__.__name__
        msg = msg[:200]
        logger.error("Unexpected error during workspace parse: %s", msg)
        diagnostics = _build_workspace_parse_diagnostics(
            source_path=source_path,
            file_ext=file_ext,
            requested_backend=requested_backend,
            resolved_backend=resolved_backend,
            error_type=str(exc.__class__.__name__),
            error_message=msg,
        )
        _persist_workspace_parse_failure(doc=doc, db=db, message=msg, diagnostics=diagnostics)
        raise HTTPException(
            status_code=500,
            detail={"message": _workspace_failure_detail(message=msg, status_code=500), "diagnostics": diagnostics},
        ) from exc
    finally:
        if cleanup_path is not None:
            with contextlib.suppress(Exception):
                cleanup_path.unlink(missing_ok=True)


async def _run_workspace_parse_pipeline(
    *,
    db: Session,
    doc: DBDocument,
    request: Request,
    tenant_id: UUID,
    account_id: str,
    source_path: Path,
    meta: Any,
    requested_backend: str,
    resolved_backend: str,
    file_ext: str,
    image_caption_enabled: bool,
    image_ocr_enabled: bool,
    vlm_correction_enabled: bool | None,
) -> ParsingContentResponse:
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
    resolved_backend = str(parsed.get("resolved_backend") or resolved_backend)
    parse_provenance = parsed.get("provenance") if isinstance(parsed.get("provenance"), dict) else None
    if requested_backend not in {"", "auto"} and resolved_backend != requested_backend:
        _fail_workspace_backend_mismatch(
            doc=doc,
            db=db,
            meta=meta,
            requested_backend=requested_backend,
            resolved_backend=resolved_backend,
            parse_provenance=parse_provenance,
        )
    pdf_quality = parsed.get("pdf_quality") if isinstance(parsed.get("pdf_quality"), dict) else None
    artifact_docs = parsed.get("documents") if isinstance(parsed, dict) else None
    elements = _sanitize_storage_value(normalize_document_elements(artifact_docs))
    original_markdown, markdown = _extract_markdown_pair_from_documents(
        parsed.get("documents") if isinstance(parsed, dict) else None
    )
    gate = _compute_parsing_quality_gate(
        markdown,
        pdf_quality=pdf_quality,
        min_content_chars=max(0, int(getattr(settings, "PARSE_FALLBACK_MIN_CONTENT_CHARS", 120) or 120)),
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
    markdown, gate, vlm_audit, vlm_correction_requested = _apply_workspace_vlm_correction(
        tenant_id=tenant_id,
        document_id=doc.id,
        file_ext=file_ext,
        artifact_docs=artifact_docs,
        markdown=markdown,
        gate=gate,
        pdf_quality=pdf_quality,
        vlm_correction_enabled=vlm_correction_enabled,
    )
    markdown, captions_added, image_ocr_added, image_ocr_audit = _apply_workspace_image_enrichments(
        markdown=markdown,
        source_path=source_path,
        image_caption_enabled=image_caption_enabled,
        image_ocr_enabled=image_ocr_enabled,
    )
    return _persist_workspace_parse_result(
        db=db,
        doc=doc,
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
        elements=_sanitize_storage_value(elements),
        duration_sec=max(0.0, time.perf_counter() - started_at),
        artifact_docs=artifact_docs,
        captions_added=captions_added,
        image_ocr_added=image_ocr_added,
        image_ocr_audit=image_ocr_audit,
        fallback_attempts=fallback_attempts,
    )


@router.post(
    "/documents/{document_id}/parse",
    response_model=ParsingContentResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def parse_workspace_document(
    document_id: uuid.UUID,
    request: Request,
    parser_backend: str | None = None,
    image_caption_enabled: Annotated[bool, Query()] = False,
    image_ocr_enabled: Annotated[bool, Query()] = False,
    vlm_correction_enabled: Annotated[bool | None, Query()] = None,
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
    source_path = await _resolve_workspace_source_path(doc=doc, tenant_id=tenant_id)
    cleanup_path = source_path if is_object_storage_uri(str(doc.file_path or "").strip()) else None
    _set_workspace_parse_processing(doc, db)

    # Resolve parser backend (validate early).
    meta = doc.doc_metadata or {}
    requested_backend = _resolve_workspace_requested_backend(meta, parser_backend)
    file_ext = f".{(doc.file_type or '').lower()}"
    try:
        resolved_backend = _resolve_workspace_backend(file_ext=file_ext, requested_backend=requested_backend)
    except ValueError as exc:
        doc.status = "failed"
        doc.processing_progress = 0
        doc.current_stage = "failed"
        doc.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await _execute_workspace_parse_request(
        db=db,
        doc=doc,
        request=request,
        tenant_id=tenant_id,
        account_id=account_id,
        source_path=source_path,
        cleanup_path=cleanup_path,
        meta=meta,
        requested_backend=requested_backend,
        resolved_backend=resolved_backend,
        file_ext=file_ext,
        image_caption_enabled=bool(image_caption_enabled),
        image_ocr_enabled=bool(image_ocr_enabled),
        vlm_correction_enabled=vlm_correction_enabled,
    )


@router.get(
    "/documents/{document_id}/content",
    response_model=ParsingContentResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_parsing_content(
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
    elements = meta.get("elements") if isinstance(meta, dict) else None
    return ParsingContentResponse(
        document_id=doc.id,
        parser_backend=str(parser_backend or "auto"),
        markdown_content=(row.markdown_content if row else ""),
        original_markdown_content=(row.original_markdown_content if row else ""),
        stats=stats,
        parse_duration_sec=duration_sec,
        pdf_quality=(dict(pdf_quality) if isinstance(pdf_quality, dict) else None),
        quality_gate=(ParsingQualityGate(**quality_gate) if isinstance(quality_gate, dict) else None),
        elements=(list(elements) if isinstance(elements, list) else None),
    )


@router.patch(
    "/documents/{document_id}/content",
    response_model=ParsingContentResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
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
    ds = DatasetService.get_dataset(db, tenant_id, doc.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    markdown = _strip_storage_nul_chars(str(payload.markdown_content or ""))
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
    original = _strip_storage_nul_chars(str(original or ""))

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
    doc.doc_metadata = _sanitize_storage_value(next_meta)

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
    elements = next_meta.get("elements") if isinstance(next_meta, dict) else None

    return ParsingContentResponse(
        document_id=doc.id,
        parser_backend=parser_backend,
        markdown_content=markdown,
        original_markdown_content=original,
        parse_duration_sec=duration_sec,
        elements=(list(elements) if isinstance(elements, list) else None),
    )


@router.delete("/documents/{document_id}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_parsing_document(
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
            if is_object_storage_uri(raw_path):
                store, ref = resolve_document_object_reference(
                    raw_path,
                    tenant_id=tenant_id,
                    dataset_id=doc.dataset_id,
                    document_id=doc.id,
                    file_type=doc.file_type,
                    document_metadata=dict(getattr(doc, "doc_metadata", None) or {}),
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
