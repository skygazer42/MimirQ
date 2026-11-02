"""
Document management API.
"""

import asyncio
import contextlib
import hashlib
import importlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas.document import DocumentPipelineOptions, UrlUploadRequest
from app.api.utils.document_dispatch import schedule_document_processing
from app.api.utils.pipeline_options import PipelineOptionOverrides as PipelineOptionOverrides
from app.api.utils.upload import compute_file_hash, save_upload_file_with_hash
from app.api.utils.url_ingest import URLDownloadOptions, download_url_to_path, validate_url_for_ingest
from app.api.v1 import (
    document_access,
    document_assets,
    document_batch_upload,
    document_batches,
    document_batches_lifecycle,
    document_chunks_read,
    document_content,
    document_dead_letters,
    document_detail,
    document_duplicates,
    document_folders,
    document_health,
    document_lifecycle,
    document_listing,
    document_manual,
    document_mutations,
    document_preview,
    document_processing,
    document_stats,
    document_timeline,
    document_versions,
)
from app.api.v1.document_access import (
    get_document_access as get_document_access,
)
from app.api.v1.document_access import (
    put_document_access as put_document_access,
)
from app.api.v1.document_assets import (
    DOCUMENT_FILE_ACCESS_DENIED_DETAIL as DOCUMENT_FILE_ACCESS_DENIED_DETAIL,
)
from app.api.v1.document_assets import (
    DOCUMENT_FILE_NOT_FOUND_DETAIL as DOCUMENT_FILE_NOT_FOUND_DETAIL,
)
from app.api.v1.document_assets import (
    IMAGE_JPEG_MEDIA_TYPE as IMAGE_JPEG_MEDIA_TYPE,
)
from app.api.v1.document_assets import (
    IMAGE_NOT_FOUND_DETAIL as IMAGE_NOT_FOUND_DETAIL,
)
from app.api.v1.document_assets import (
    INVALID_RANGE_HEADER_DETAIL as INVALID_RANGE_HEADER_DETAIL,
)
from app.api.v1.document_assets import (
    download_document as download_document,
)
from app.api.v1.document_assets import (
    get_image as get_image,
)
from app.api.v1.document_assets import (
    get_image_url as get_image_url,
)
from app.api.v1.document_batches import (
    batch_move_documents as batch_move_documents,
)
from app.api.v1.document_batches import (
    batch_patch_document_user_metadata as batch_patch_document_user_metadata,
)
from app.api.v1.document_batches import (
    batch_reingest_documents as batch_reingest_documents,
)
from app.api.v1.document_batches import (
    batch_retry_documents as batch_retry_documents,
)
from app.api.v1.document_batches import (
    batch_update_document_access as batch_update_document_access,
)
from app.api.v1.document_batches_lifecycle import (
    batch_archive_documents as batch_archive_documents,
)
from app.api.v1.document_batches_lifecycle import (
    batch_delete_documents as batch_delete_documents,
)
from app.api.v1.document_batches_lifecycle import (
    batch_disable_documents as batch_disable_documents,
)
from app.api.v1.document_batches_lifecycle import (
    batch_enable_documents as batch_enable_documents,
)
from app.api.v1.document_batches_lifecycle import (
    batch_unarchive_documents as batch_unarchive_documents,
)
from app.api.v1.document_chunks_read import (
    get_document_chunk as get_document_chunk,
)
from app.api.v1.document_chunks_read import (
    list_document_chunk_matches as list_document_chunk_matches,
)
from app.api.v1.document_chunks_read import (
    list_document_chunks as list_document_chunks,
)
from app.api.v1.document_content import (
    download_document_clean_docx as download_document_clean_docx,
)
from app.api.v1.document_content import (
    get_document_parsed_content as get_document_parsed_content,
)
from app.api.v1.document_detail import (
    get_document as get_document,
)
from app.api.v1.document_health import (
    get_document_health_card as get_document_health_card,
)
from app.api.v1.document_listing import (
    ListDocumentsQueryFields as ListDocumentsQueryFields,
)
from app.api.v1.document_listing import (
    _source_path_prefix_expr as _source_path_prefix_expr,
)
from app.api.v1.document_listing import (
    list_documents as list_documents,
)
from app.api.v1.document_manual import (
    create_document_with_manual_chunks as create_document_with_manual_chunks,
)
from app.api.v1.document_mutations import (
    generate_document_qa as generate_document_qa,
)
from app.api.v1.document_mutations import (
    patch_document_pipeline as patch_document_pipeline,
)
from app.api.v1.document_mutations import (
    patch_document_user_metadata as patch_document_user_metadata,
)
from app.api.v1.document_processing import (
    cancel_document_processing as cancel_document_processing,
)
from app.api.v1.document_processing import (
    delete_document as delete_document,
)
from app.api.v1.document_processing import (
    get_document_status as get_document_status,
)
from app.api.v1.document_processing import (
    retry_document_processing as retry_document_processing,
)
from app.api.v1.document_timeline import (
    get_document_timeline as get_document_timeline,
)
from app.api.v1.document_versions import (
    activate_document_version as activate_document_version,
)
from app.api.v1.document_versions import (
    delete_document_version as delete_document_version,
)
from app.api.v1.document_versions import (
    diff_document_versions as diff_document_versions,
)
from app.api.v1.document_versions import (
    list_document_versions as list_document_versions,
)
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.env import is_production_env
from app.models.dataset import Dataset
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.parsing.factory import parser_factory
from app.parsing.subprocess_runner import run_subprocess_worker
from app.rag.chunking.factory import chunker_factory
from app.rag.core.logging import get_logger
from app.rag.kg.pipeline import extract_events
from app.rag.preprocessing.html_canonical import extract_canonical_url, normalize_url_for_dedup
from app.rag.preprocessing.processor import governance_processor
from app.rag.preprocessing.rules import build_governance_rules
from app.services import dataset_service, document_access_service, ingestion_run_service
from app.services.dataset_precheck_ingestion_suggestion import apply_ingestion_policy_suggestion
from app.services.dataset_precheck_scan_runner import run_dataset_precheck_scan
from app.services.document_identity import (
    build_document_dedup_key,
    compute_pipeline_hash,
    get_content_sha256,
    set_content_sha256,
    sync_pipeline_execution_identity,
)
from app.services.document_index_channel_service import reconcile_document_index_channels
from app.services.document_preview_utils import (
    DATA_IMAGE_PREFIX as DATA_IMAGE_PREFIX,
)
from app.services.document_preview_utils import (
    IMAGE_FILE_EXT_JPEG as IMAGE_FILE_EXT_JPEG,
)
from app.services.document_preview_utils import (
    IMAGE_FILE_EXT_WEBP as IMAGE_FILE_EXT_WEBP,
)
from app.services.document_preview_utils import (
    MINIO_IMAGE_REF_RE as MINIO_IMAGE_REF_RE,
)
from app.services.document_preview_utils import (
    PREVIEW_IMAGE_EXTENSIONS as PREVIEW_IMAGE_EXTENSIONS,
)
from app.services.document_preview_utils import (
    PREVIEW_IMAGE_REF_RE as PREVIEW_IMAGE_REF_RE,
)
from app.services.document_preview_utils import (
    UUID_PATTERN as UUID_PATTERN,
)
from app.services.document_preview_utils import (
    _compute_chunk_preview_quality,
    _materialize_extracted_images_for_preview,
    _materialize_local_images_for_preview,
)
from app.services.document_preview_utils import (
    _rewrite_preview_images_to_minio as _rewrite_preview_images_to_minio,
)
from app.services.index_audit_service import build_index_drift_marker
from app.services.ingestion_policy import (
    match_ingestion_rule,
    parse_ingestion_policy_from_metadata,
    resolve_governance_profile_ref,
)
from app.services.pipeline_config import (
    build_indexing_options,
    merge_pipeline_options,
    resolve_pipeline_effective,
    upsert_pipeline_metadata,
)
from app.storage.object.minio import minio_service as minio_service
from app.storage.object.runtime import (
    document_object_storage_enabled,
    document_object_store_metadata,
    get_document_object_store,
    get_object_store_for_uri,
    is_object_storage_uri,
    object_store_backend_config,
    parse_object_storage_uri,
)
from app.storage.object.runtime import resolve_document_object_reference as resolve_document_object_reference
from app.types.pipeline import PipelineOptions

logger = get_logger("api.documents")

NO_DOCUMENT_ACCESS_DETAIL = document_access_service.NO_DOCUMENT_ACCESS_DETAIL
_assert_document_acl_readable = document_access_service.assert_document_acl_readable
_assert_document_readable_for_lifecycle = document_access_service.assert_document_readable_for_lifecycle
_assert_document_writable_for_lifecycle = document_access_service.assert_document_writable_for_lifecycle
_assert_document_writable_for_unassigned_target = document_access_service.assert_document_writable_for_unassigned_target
_get_document_for_lifecycle = document_access_service.get_document_for_lifecycle

__all__ = [
    "DBDatasetPrecheckScanRun",
    "SessionLocal",
    "_compute_chunk_preview_quality",
    "_materialize_extracted_images_for_preview",
    "_materialize_local_images_for_preview",
    "_rewrite_preview_images_to_minio",
    "apply_ingestion_policy_suggestion",
    "build_governance_rules",
    "build_indexing_options",
    "extract_events",
    "governance_processor",
    "os",
    "run_dataset_precheck_scan",
    "run_subprocess_worker",
    "save_upload_file_with_hash",
]

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
router.include_router(document_access.router)
router.include_router(document_assets.router)
router.include_router(document_batches.router)
router.include_router(document_batches_lifecycle.router)
router.include_router(document_batch_upload.router)
router.include_router(document_duplicates.router)
router.include_router(document_folders.router)
router.include_router(document_stats.router)
router.include_router(document_chunks_read.router)
router.include_router(document_content.router)
router.include_router(document_dead_letters.router)
router.include_router(document_listing.router)
router.include_router(document_manual.router)
router.include_router(document_preview.router)
router.include_router(document_detail.router)
router.include_router(document_health.router)
router.include_router(document_lifecycle.router)
router.include_router(document_mutations.router)
router.include_router(document_processing.router)
router.include_router(document_timeline.router)
router.include_router(document_versions.router)

# Compatibility re-export for existing imports/tests that still resolve the preview
# endpoint from `app.api.v1.documents`.
preview_document = document_preview.preview_document

# Filename validation:
# - We store uploads by UUID on disk/MinIO, so we don't need a strict character allowlist.
# - Still reject path separators / control characters to prevent path traversal and header issues.
# Position tags emitted by some PDF parsers (used for PDF overlay highlighting).
POSITION_TAG_RE = re.compile(r"@@([0-9-]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##")

DOC_NOT_FOUND_DETAIL = "Document not found"
DUPLICATE_DOCUMENT_PROCESSING_DETAIL = "Duplicate document is currently processing"
HTML_FILE_EXTENSION = ".html"
PIPELINE_HASH_TOO_LONG_DETAIL = "pipeline_hash too long"
FILENAME_INVALID_CHARS_DETAIL = "Filename contains invalid characters"
CHUNK_NOT_FOUND_DETAIL = "Chunk not found"
CHUNK_NOT_ACTIVE_PIPELINE_DETAIL = "Chunk is not in the active pipeline version"
DOCUMENT_DEDUP_CONSTRAINT_NAME = "uq_documents_tenant_dataset_dedup_key_active"
CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL = "chunk_overlap must be less than chunk_size"
MANUAL_FILE_PATH_PREFIX = "manual://"
CHUNK_PATCH_OPERATION = "chunk.patch"


def _coerce_bool_preview(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return None


def _coerce_int_preview(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except Exception:
            return None
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except Exception:
            return None
    return None


def _coerce_float_preview(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None
    if isinstance(value, str):
        try:
            return float(value.strip())
        except Exception:
            return None
    return None


def _decode_escaped_input_preview(value: str) -> str:
    """
    Best-effort decode for user input strings like "\\n\\n" / "\\t" / "\\u4e2d".

    Keep aligned with frontend behavior and ingestion SeparatorChunker handling.
    """
    raw = str(value or "")
    if not raw:
        return raw
    try:
        escaped = raw.replace('"', '\\"')
        return json.loads(f'"{escaped}"')
    except Exception:
        return raw


def _filter_chunker_kwargs_for_strategy(strategy: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """
    Filter kwargs to match the chunker __init__ signature (mirrors chunker_factory.get_chunker behavior).
    """
    if not kwargs:
        return {}
    chunker_cls = chunker_factory.SUPPORTED_STRATEGIES.get(strategy)
    if chunker_cls is None:
        return {}

    import inspect

    try:
        sig = inspect.signature(chunker_cls.__init__)
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            return dict(kwargs)
        accepted = {
            p.name
            for p in sig.parameters.values()
            if p.name not in {"self", "chunk_size", "chunk_overlap"}
            and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        }
        return {k: v for k, v in kwargs.items() if k in accepted}
    except Exception:
        return {}


_WINDOWS_DRIVE_LETTER_RE = re.compile(r"^[a-zA-Z]:$")
_UPLOAD_SOURCE_PATH_MAX_LEN = 500


def _assert_upload_filename_has_no_control_chars(raw: str) -> None:
    if "\x7f" in raw or any(ord(ch) < 32 for ch in raw):
        raise HTTPException(status_code=400, detail=FILENAME_INVALID_CHARS_DETAIL)


def _split_upload_path_parts(cleaned: str) -> list[str]:
    parts = [p.strip() for p in cleaned.split("/") if p.strip() and p.strip() != "."]
    if parts and _WINDOWS_DRIVE_LETTER_RE.fullmatch(parts[0]):
        return parts[1:]
    return parts


def _collapse_upload_path_parts(parts: list[str]) -> list[str]:
    stack: list[str] = []
    for p in parts:
        if p == "..":
            if stack:
                stack.pop()
            continue
        stack.append(p)
    return stack


def _drop_fakepath_prefix(parts: list[str]) -> list[str]:
    if len(parts) == 2 and parts[0].lower() == "fakepath":
        return [parts[1]]
    return parts


def _normalize_upload_path_parts(filename: str) -> list[str]:
    raw = str(filename or "")
    if not raw:
        return []
    _assert_upload_filename_has_no_control_chars(raw)

    cleaned = raw.replace("\\", "/").strip()
    if not cleaned:
        return []

    parts = _split_upload_path_parts(cleaned)
    if not parts:
        return []

    return _drop_fakepath_prefix(_collapse_upload_path_parts(parts))


def _normalize_upload_key(filename: str) -> str:
    parts = _normalize_upload_path_parts(filename)
    if not parts:
        return _sanitize_filename(filename)
    key = "/".join(parts)
    if len(key) > _UPLOAD_SOURCE_PATH_MAX_LEN:
        key = key[:_UPLOAD_SOURCE_PATH_MAX_LEN]
    return key


def _sanitize_filename(filename: str) -> str:
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    cleaned = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Filename is required")
    if len(cleaned) > 255:
        raise HTTPException(status_code=400, detail="Filename too long (max 255 characters)")
    if "\x7f" in cleaned or any(ord(ch) < 32 for ch in cleaned):
        raise HTTPException(status_code=400, detail=FILENAME_INVALID_CHARS_DETAIL)
    if cleaned in {".", ".."}:
        raise HTTPException(status_code=400, detail=FILENAME_INVALID_CHARS_DETAIL)
    return cleaned


def _parse_pipeline_json(pipeline: str | None) -> DocumentPipelineOptions | None:
    raw = (pipeline or "").strip()
    if not raw or raw.lower() in {"null", "none", "undefined"}:
        return None
    max_len = int(settings.PIPELINE_FORM_JSON_MAX_CHARS or 200_000)
    if max_len > 0 and len(raw) > max_len:
        raise HTTPException(status_code=400, detail="pipeline is too large")
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("pipeline must be a JSON object")
        return DocumentPipelineOptions.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        msg = (str(exc) or exc.__class__.__name__)[:200]
        detail = "Invalid pipeline JSON" if is_production_env() else f"Invalid pipeline JSON: {msg}"
        raise HTTPException(status_code=400, detail=detail) from exc


def _compute_pipeline_hash(doc_metadata: dict) -> str:
    return compute_pipeline_hash(doc_metadata)


def _validate_chunk_params(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_overlap >= chunk_size:
        raise HTTPException(
            status_code=400,
            detail=CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL,
        )


def _get_document_for_chunk_ops(db: Session, tenant_id: UUID, document_id: UUID) -> DBDocument | None:
    return db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()


def _get_chunk_for_chunk_ops(
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    chunk_id: UUID,
) -> DocumentChunk | None:
    return (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.id == chunk_id,
        )
        .first()
    )


def _assert_document_writable_for_chunk_ops(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document: DBDocument,
) -> None:
    _assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )


def _parse_datetime_best_effort(raw: str | None) -> datetime | None:
    """
    Best-effort datetime parser for connector source metadata.

    Supports:
    - HTTP-date (e.g. Last-Modified: "Wed, 21 Oct 2015 07:28:00 GMT")
    - ISO 8601 timestamps (e.g. "2026-03-04T10:00:00Z")
    """
    value = str(raw or "").strip()
    if not value:
        return None

    with contextlib.suppress(Exception):
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    with contextlib.suppress(Exception):
        iso = value
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    return None


def _normalize_datetime_utc_iso(raw: str | None) -> str | None:
    dt = _parse_datetime_best_effort(raw)
    if dt is None:
        return None
    return dt.isoformat()


class LocalHtmlIngestRequest(BaseModel):
    """Ingest a local HTML payload as a document (internal connector helper)."""

    model_config = ConfigDict(extra="forbid")

    html: str = Field(..., description="HTML content (fragment or full document)")
    source_url: str | None = Field(
        default=None, max_length=2000, description="Best-effort source URL for citations/debug"
    )
    dataset_id: UUID | None = None
    filename: str | None = Field(
        default=None, max_length=500, description="Optional override filename (used for extension + display)"
    )
    parser_backend: str = Field(default=settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Field(default=settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: DocumentPipelineOptions | None = None


@dataclass
class ResolvedDocumentIngestionPolicy:
    parser_backend_choice: str
    chunk_strategy_choice: str
    pipeline_options: PipelineOptions
    ingestion_meta: dict[str, Any] | None


@dataclass
class ResolvedDocumentPipeline:
    parser_backend: str
    chunk_strategy: str


@dataclass
class UrlIngestFile:
    file_id: UUID
    final_path: Path
    file_ext: str
    downloaded: Any
    content_type: str
    fetched_at_iso: str
    content_sha256: str


@dataclass
class LocalHtmlIngestFile:
    file_id: UUID
    file_path: Path
    file_ext: str
    filename: str
    file_size: int
    fetched_at_iso: str
    content_sha256: str


@dataclass
class UrlSourceMetadata:
    final_url: str
    normalized_requested: str | None
    normalized_final: str | None
    canonical_url: str | None
    normalized_canonical: str | None
    normalized_url: str | None
    last_modified_at: str
    last_modified_source: str
    last_modified_raw: str | None
    etag: str | None


@dataclass
class PreparedDocumentIngestion:
    policy: ResolvedDocumentIngestionPolicy
    pipeline: ResolvedDocumentPipeline


def _ext_from_filename(name: str | None) -> str | None:
    if not name:
        return None
    ext = Path(str(name)).suffix.lower()
    return ext if ext else None


def _ext_from_content_type(content_type: str) -> str | None:
    if not content_type:
        return None
    if content_type in {"text/html"}:
        return HTML_FILE_EXTENSION
    if content_type in {"text/plain"}:
        return ".txt"
    if content_type in {"text/markdown", "text/x-markdown"}:
        return ".md"
    if content_type in {"application/pdf"}:
        return ".pdf"
    if content_type in {"application/json"}:
        return ".json"
    if content_type in {"text/xml", "application/xml", "application/rss+xml", "application/atom+xml"}:
        return ".xml"
    return None


def _assert_allowed_file_ext(file_ext: str) -> str:
    file_ext = file_ext.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400, detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )
    return file_ext


def _resolve_url_file_ext(*, filename: str | None, url: str, content_type: str) -> str:
    file_ext = _ext_from_filename(filename)
    if not file_ext:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        file_ext = _ext_from_filename(Path(parsed.path).name)
    if not file_ext:
        file_ext = _ext_from_content_type(content_type)
    if not file_ext:
        if content_type.startswith("text/"):
            file_ext = ".txt"
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported content-type: {content_type or 'unknown'}")
    return _assert_allowed_file_ext(file_ext)


def _resolve_local_html_file_ext(safe_name: str) -> str:
    file_ext = Path(safe_name).suffix.lower() or HTML_FILE_EXTENSION
    if file_ext == ".htm":
        file_ext = HTML_FILE_EXTENSION
    if not file_ext.startswith("."):
        file_ext = "." + file_ext
    return _assert_allowed_file_ext(file_ext)


def _finalize_url_download(temp_path: Path, final_path: Path) -> None:
    try:
        temp_path.replace(final_path)
    except Exception:
        try:
            shutil.move(str(temp_path), str(final_path))
        except Exception as exc:  # noqa: BLE001
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=500, detail=f"failed to finalize downloaded file: {str(exc)[:120]}"
            ) from exc


def _read_html_prefix(path: Path) -> str:
    with path.open("rb") as f:
        return f.read(200_000).decode("utf-8", "ignore")


async def _extract_url_canonical_metadata(
    *,
    content_type: str,
    final_path: Path,
    url_final: str,
) -> tuple[str | None, str | None]:
    if not content_type or "html" not in content_type:
        return None, None

    try:
        html_prefix = await asyncio.to_thread(_read_html_prefix, final_path)
        url_canonical = extract_canonical_url(html_prefix, base_url=url_final)
        url_normalized_canonical = normalize_url_for_dedup(url_canonical) if url_canonical else None
        return url_canonical, url_normalized_canonical
    except Exception:
        return None, None


def _document_pipeline_options(pipeline: DocumentPipelineOptions | None) -> PipelineOptions:
    return PipelineOptions(**(pipeline.model_dump(exclude_none=True) if pipeline else {}))


def _normalized_dataset_default(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None


def _dataset_pipeline_defaults(dataset: Dataset | None) -> tuple[str, str]:
    dataset_default_pb = None
    dataset_default_cs = None
    if dataset is not None:
        ds_meta = getattr(dataset, "dataset_metadata", None)
        if isinstance(ds_meta, dict):
            dataset_default_pb = _normalized_dataset_default(ds_meta.get("default_parser_backend"))
            dataset_default_cs = _normalized_dataset_default(ds_meta.get("default_chunk_strategy"))

    default_pb_eff = dataset_default_pb or str(settings.DEFAULT_PARSER_BACKEND or "auto").strip().lower() or "auto"
    default_cs_eff = (
        dataset_default_cs
        or str(settings.DEFAULT_CHUNK_STRATEGY or "langchain_recursive").strip().lower()
        or "langchain_recursive"
    )
    return default_pb_eff, default_cs_eff


def _rule_backend_choices(
    *,
    matched_rule: Any,
    parser_backend_choice: str,
    chunk_strategy_choice: str,
    default_pb_eff: str,
    default_cs_eff: str,
) -> tuple[str, str]:
    req_pb = (parser_backend_choice or "").strip().lower()
    if req_pb in {"", "auto", default_pb_eff} and matched_rule.parser_backend:
        parser_backend_choice = str(matched_rule.parser_backend)

    req_cs = (chunk_strategy_choice or "").strip().lower()
    if req_cs in {"", default_cs_eff} and matched_rule.chunk_strategy:
        chunk_strategy_choice = str(matched_rule.chunk_strategy)

    return parser_backend_choice, chunk_strategy_choice


def _rule_preprocess_steps(matched_rule: Any) -> list[dict[str, Any]]:
    pp = getattr(matched_rule, "preprocess", None)
    steps = getattr(pp, "steps", None) if pp is not None and bool(getattr(pp, "enabled", True)) else None
    if not isinstance(steps, list) or not steps:
        return []
    return [
        {
            "id": str(getattr(s, "id", "") or "").strip(),
            "params": dict(getattr(s, "params", {}) or {}),
        }
        for s in steps
    ]


def _rule_pipeline_patch(db: Session, *, tenant_id: UUID, matched_rule: Any) -> tuple[PipelineOptions, str | None]:
    patch_dict: dict[str, Any] = {}
    profile_ref = getattr(matched_rule, "governance_profile_ref", None)
    normalized_profile_ref = profile_ref.strip() if isinstance(profile_ref, str) and profile_ref.strip() else None
    if normalized_profile_ref:
        try:
            resolved = resolve_governance_profile_ref(db=db, tenant_id=tenant_id, profile_ref=normalized_profile_ref)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid governance_profile_ref: {str(exc)[:120]}") from exc
        patch_dict.update(dict(resolved.pipeline_patch or {}))
        if resolved.regex_rules:
            patch_dict["governance_regex_rules"] = list(resolved.regex_rules)

    patch_dict.update(dict(getattr(matched_rule, "pipeline_patch", None) or {}))
    policy_patch = PipelineOptions(**patch_dict) if patch_dict else PipelineOptions()
    return policy_patch, normalized_profile_ref


def _policy_from_dataset(dataset: Dataset | None):
    dataset_meta = (getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}
    return parse_ingestion_policy_from_metadata(dataset_meta if isinstance(dataset_meta, dict) else {})  # type: ignore[arg-type]


def _resolve_document_ingestion_policy(
    *,
    db: Session,
    tenant_id: UUID,
    dataset: Dataset,
    filename: str,
    file_ext: str,
    requested_parser_backend: str,
    requested_chunk_strategy: str,
    pipeline: DocumentPipelineOptions | None,
    source_url: str | None,
) -> ResolvedDocumentIngestionPolicy:
    pipeline_options = _document_pipeline_options(pipeline)
    policy = _policy_from_dataset(dataset)
    matched_rule = match_ingestion_rule(policy, filename=filename, file_ext=file_ext)
    default_pb_eff, default_cs_eff = _dataset_pipeline_defaults(dataset)

    parser_backend_choice = str(requested_parser_backend or default_pb_eff)
    chunk_strategy_choice = str(requested_chunk_strategy or default_cs_eff)
    policy_patch = PipelineOptions()
    ingestion_meta: dict[str, Any] | None = None

    if matched_rule is not None:
        parser_backend_choice, chunk_strategy_choice = _rule_backend_choices(
            matched_rule=matched_rule,
            parser_backend_choice=parser_backend_choice,
            chunk_strategy_choice=chunk_strategy_choice,
            default_pb_eff=default_pb_eff,
            default_cs_eff=default_cs_eff,
        )
        preprocess_steps = _rule_preprocess_steps(matched_rule)
        policy_patch, profile_ref = _rule_pipeline_patch(db, tenant_id=tenant_id, matched_rule=matched_rule)
        ingestion_meta = {
            "version": str(getattr(policy, "version", "1") if policy is not None else "1"),
            "rule": {"id": matched_rule.id, "name": matched_rule.name},
            "preprocess": {"enabled": bool(preprocess_steps), "steps": preprocess_steps},
            "governance_profile_ref": profile_ref,
            "source_url": source_url,
        }

    return ResolvedDocumentIngestionPolicy(
        parser_backend_choice=parser_backend_choice,
        chunk_strategy_choice=chunk_strategy_choice,
        pipeline_options=merge_pipeline_options(policy_patch, pipeline_options),
        ingestion_meta=ingestion_meta,
    )


def _resolve_document_pipeline(
    *,
    file_ext: str,
    parser_backend_choice: str,
    chunk_strategy_choice: str,
    preserve_pdf_auto: bool,
) -> ResolvedDocumentPipeline:
    try:
        requested_parser_backend = (parser_backend_choice or "").strip().lower()
        if preserve_pdf_auto and file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
            resolved_parser_backend = "auto"
        else:
            resolved_parser_backend = parser_factory.resolve_backend(file_ext, parser_backend_choice)
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy_choice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ResolvedDocumentPipeline(parser_backend=resolved_parser_backend, chunk_strategy=resolved_chunk_strategy)


def _validate_pipeline_effective_for_strategy(
    *,
    dataset: Dataset,
    pipeline_options: PipelineOptions,
    resolved_chunk_strategy: str,
) -> None:
    pipeline_effective = resolve_pipeline_effective(
        dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}),
        document_metadata={},
        request_overrides=pipeline_options,
    )
    if resolved_chunk_strategy not in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        _validate_chunk_params(pipeline_effective.chunk_size, pipeline_effective.chunk_overlap)


def _create_ingestion_run_if_missing(
    *,
    db: Session,
    tenant_id: UUID,
    dataset: Dataset,
    account_id: str,
    ingestion_run_id: UUID | None,
    ingestion_kind: str | None,
    default_kind: str,
    config: dict[str, Any],
) -> UUID | None:
    if ingestion_run_id is not None:
        return ingestion_run_id
    try:
        ingestion_kind_norm = str(ingestion_kind or default_kind).strip() or default_kind
        ingestion_run = ingestion_run_service.create_run(
            db,
            tenant_id=tenant_id,
            dataset_id=getattr(dataset, "id", None),
            requested_by=account_id,
            kind=ingestion_kind_norm,
            config=config,
            expected_documents=1,
        )
        return ingestion_run.id
    except Exception:
        return None


def _finalize_document_metadata(
    doc_metadata: dict[str, Any],
    *,
    content_sha256: str | None,
    pipeline_options: PipelineOptions,
    ingestion_meta: dict[str, Any] | None,
    ingestion_run_id: UUID | None,
    ingestion_kind: str | None,
    default_kind: str,
    parser_backend_resolved: str | None = None,
) -> tuple[dict[str, Any], str]:
    set_content_sha256(doc_metadata, content_sha256)
    upsert_pipeline_metadata(doc_metadata, options=pipeline_options)
    if ingestion_meta:
        doc_metadata["ingestion"] = ingestion_meta

    pipeline_hash = _compute_pipeline_hash(doc_metadata)
    doc_metadata["pipeline_hash"] = pipeline_hash
    doc_metadata.setdefault("active_pipeline_hash", pipeline_hash)
    doc_metadata.setdefault("active_pipeline_ready", False)
    sync_pipeline_execution_identity(
        doc_metadata,
        content_sha256=content_sha256,
        pipeline_hash=pipeline_hash,
        parser_backend_resolved=parser_backend_resolved,
    )
    if ingestion_run_id is not None:
        doc_metadata.setdefault("created_by_run_id", str(ingestion_run_id))
        doc_metadata["last_ingestion_run_id"] = str(ingestion_run_id)
        doc_metadata["last_ingestion_kind"] = str(ingestion_kind or default_kind)
    return doc_metadata, pipeline_hash


def _enforce_url_upload_quota(db: Session, *, tenant_id: UUID, additional_bytes: int, final_path: Path) -> None:
    try:
        from app.services.tenant_quota_service import enforce_tenant_upload_quotas

        enforce_tenant_upload_quotas(
            db,
            tenant_id=tenant_id,
            additional_docs=1,
            additional_bytes=additional_bytes,
        )
    except HTTPException:
        with contextlib.suppress(OSError):
            final_path.unlink(missing_ok=True)
        raise


def _document_object_storage_enabled() -> bool:
    return document_object_storage_enabled()


def _unlink_ingest_temp(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _document_matches_dedup_identity(
    document: Any,
    *,
    content_sha256: str,
    pipeline_hash: str,
) -> bool:
    expected = build_document_dedup_key(content_sha256=content_sha256, pipeline_hash=pipeline_hash)
    if expected and str(getattr(document, "dedup_key", "") or "").strip() == expected:
        return True
    metadata = dict(getattr(document, "doc_metadata", None) or {})
    return bool(
        expected
        and get_content_sha256(metadata) == str(content_sha256 or "").strip().lower()
        and str(metadata.get("pipeline_hash") or "").strip() == str(pipeline_hash or "").strip()
    )


def _is_document_dedup_integrity_error(exc: IntegrityError) -> bool:
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    if str(getattr(diag, "constraint_name", "") or "").strip() == DOCUMENT_DEDUP_CONSTRAINT_NAME:
        return True
    message = str(getattr(exc, "orig", "") or exc)
    return DOCUMENT_DEDUP_CONSTRAINT_NAME in message


class _DuplicatePersistedDocumentError(RuntimeError):
    def __init__(self, document: Any) -> None:
        super().__init__("duplicate persisted document")
        self.document = document


def _find_duplicate_document_for_persist_conflict(db: Session, *, db_document: Any) -> Any | None:
    dataset_id = getattr(db_document, "dataset_id", None)
    tenant_id = getattr(db_document, "tenant_id", None)
    if not isinstance(dataset_id, UUID) or not isinstance(tenant_id, UUID):
        return None
    doc_metadata = dict(getattr(db_document, "doc_metadata", None) or {})
    content_sha256 = get_content_sha256(doc_metadata)
    pipeline_hash = str(doc_metadata.get("pipeline_hash") or "").strip()
    if content_sha256 and pipeline_hash:
        return _find_duplicate_document(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            file_sha256=content_sha256,
            pipeline_hash=pipeline_hash,
        )
    return None


async def _store_ingested_source(
    *,
    file_path: Path,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
    extension: str,
    content_type: str | None,
) -> str:
    store = get_document_object_store()
    if store is None:
        return str(file_path)
    try:
        return await asyncio.to_thread(
            store.upload_document_file,
            file_path=file_path,
            tenant_id=str(tenant_id),
            dataset_id=str(dataset_id),
            document_id=str(document_id),
            extension=extension,
            content_type=content_type,
        )
    except Exception:
        _unlink_ingest_temp(file_path)
        raise


async def _cleanup_unpersisted_ingested_source(
    stored_path: str,
    *,
    document_metadata: dict[str, Any] | None = None,
) -> None:
    if not is_object_storage_uri(stored_path):
        return
    try:
        ref = parse_object_storage_uri(stored_path)
        store = get_object_store_for_uri(stored_path, document_metadata=document_metadata)
        backend = object_store_backend_config(store)
        if ref.bucket != str(backend.get("bucket", "") or "").strip():
            return
        await asyncio.to_thread(store.delete_object, object_name=ref.object_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to delete unpersisted ingest object: %s", str(exc)[:200])


def _fresh_session_document_exists(*, document_id: UUID) -> bool | None:
    try:
        check_db = SessionLocal()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to open verification session after commit error: %s", str(exc)[:200])
        return None

    try:
        getter = getattr(check_db, "get", None)
        if callable(getter):
            return getter(DBDocument, document_id) is not None
        query = getattr(check_db, "query", None)
        if callable(query):
            row = query(DBDocument).filter(DBDocument.id == document_id).first()
            return row is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to verify document existence after commit error: %s", str(exc)[:200])
        return None
    finally:
        with contextlib.suppress(Exception):
            check_db.close()

    return None


async def _cleanup_commit_ambiguous_ingested_source(
    *,
    document_id: UUID,
    stored_path: str,
    file_path: Path,
    document_metadata: dict[str, Any] | None = None,
) -> None:
    document_exists = _fresh_session_document_exists(document_id=document_id)
    object_backed = is_object_storage_uri(stored_path)
    if document_exists is False:
        await _cleanup_unpersisted_ingested_source(stored_path, document_metadata=document_metadata)
        _unlink_ingest_temp(file_path)
        return
    if object_backed:
        _unlink_ingest_temp(file_path)


def _create_pending_document_record(
    *,
    file_id: UUID,
    tenant_id: UUID,
    dataset: Dataset,
    filename: str,
    file_ext: str,
    file_size: int,
    file_path: str | Path,
    account_id: str,
    doc_metadata: dict[str, Any],
) -> DBDocument:
    db_document = DBDocument(
        id=file_id,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        filename=filename,
        file_type=file_ext.lstrip("."),
        file_size=file_size,
        file_path=str(file_path),
        owner_id=account_id,
        access_mode=None,
        status="pending",
        processing_progress=0,
        doc_metadata=doc_metadata,
    )
    return db_document


def _add_document_to_ingestion_run(
    *,
    db: Session,
    tenant_id: UUID,
    ingestion_run_id: UUID | None,
    db_document: DBDocument,
    source_ref: str | None,
    doc_metadata: dict[str, Any],
) -> None:
    if ingestion_run_id is None:
        return
    with contextlib.suppress(Exception):
        ingestion_run_service.add_document(
            db,
            tenant_id=tenant_id,
            run_id=ingestion_run_id,
            document_id=db_document.id,
            source_ref=source_ref,
            initial_status=str(getattr(db_document, "status", "") or "pending"),
            doc_meta=dict(doc_metadata),
        )


async def _download_url_ingest_file(*, url: str, body: UrlUploadRequest, tenant_id: UUID) -> UrlIngestFile:
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4()
    temp_path = upload_dir / f"{file_id}.urltmp"
    downloaded = await download_url_to_path(
        url,
        temp_path,
        options=URLDownloadOptions(
            max_bytes=int(settings.URL_INGEST_MAX_BYTES or settings.MAX_FILE_SIZE),
            timeout_sec=float(settings.URL_INGEST_TIMEOUT_SEC or 30.0),
            follow_redirects=bool(settings.URL_INGEST_FOLLOW_REDIRECTS),
            user_agent=(body.user_agent or None),
            extra_headers=(body.fetch_headers or None),
        ),
    )

    content_type = (downloaded.content_type or "").split(";", 1)[0].strip().lower()
    file_ext = _resolve_url_file_ext(filename=body.filename, url=url, content_type=content_type)
    final_path = upload_dir / f"{file_id}{file_ext}"
    _finalize_url_download(temp_path, final_path)
    content_sha256 = await asyncio.to_thread(compute_file_hash, final_path)
    return UrlIngestFile(
        file_id=file_id,
        final_path=final_path,
        file_ext=file_ext,
        downloaded=downloaded,
        content_type=content_type,
        fetched_at_iso=datetime.now(timezone.utc).isoformat(),
        content_sha256=content_sha256,
    )


def _write_local_html_ingest_file(*, body: LocalHtmlIngestRequest, tenant_id: UUID) -> LocalHtmlIngestFile:
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    data = str(body.html or "").encode("utf-8", "ignore")
    if int(settings.MAX_FILE_SIZE or 0) > 0 and len(data) > int(settings.MAX_FILE_SIZE):
        raise HTTPException(status_code=400, detail="File too large")

    safe_name = _sanitize_filename(body.filename or "confluence-page.html")
    file_ext = _resolve_local_html_file_ext(safe_name)
    file_id = uuid.uuid4()
    file_path = upload_dir / f"{file_id}{file_ext}"
    try:
        file_path.write_bytes(data)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to write html file: {str(exc)[:120]}") from exc

    return LocalHtmlIngestFile(
        file_id=file_id,
        file_path=file_path,
        file_ext=file_ext,
        filename=safe_name,
        file_size=int(len(data)),
        fetched_at_iso=datetime.now(timezone.utc).isoformat(),
        content_sha256=hashlib.sha256(data).hexdigest(),
    )


async def _url_source_metadata(*, url: str, ingest_file: UrlIngestFile) -> UrlSourceMetadata:
    downloaded = ingest_file.downloaded
    last_modified_raw = str(getattr(downloaded, "last_modified", "") or "").strip() or None
    last_modified_norm = _normalize_datetime_utc_iso(last_modified_raw) if last_modified_raw else None
    etag_raw = str(getattr(downloaded, "etag", "") or "").strip() or None
    if etag_raw and len(etag_raw) > 500:
        etag_raw = etag_raw[:500]

    url_final = str(getattr(downloaded, "final_url", "") or url).strip() or url
    url_normalized_requested = normalize_url_for_dedup(url)
    url_normalized_final = normalize_url_for_dedup(url_final)
    url_canonical, url_normalized_canonical = await _extract_url_canonical_metadata(
        content_type=ingest_file.content_type,
        final_path=ingest_file.final_path,
        url_final=url_final,
    )
    url_normalized = url_normalized_canonical or url_normalized_final or url_normalized_requested
    return UrlSourceMetadata(
        final_url=url_final,
        normalized_requested=url_normalized_requested,
        normalized_final=url_normalized_final,
        canonical_url=url_canonical,
        normalized_canonical=url_normalized_canonical,
        normalized_url=url_normalized,
        last_modified_at=last_modified_norm or ingest_file.fetched_at_iso,
        last_modified_source="http:last-modified" if last_modified_norm else "fallback:fetched_at",
        last_modified_raw=last_modified_raw,
        etag=etag_raw,
    )


def _prepare_document_ingestion(
    *,
    db: Session,
    tenant_id: UUID,
    dataset: Dataset,
    filename: str,
    file_ext: str,
    requested_parser_backend: str,
    requested_chunk_strategy: str,
    pipeline: DocumentPipelineOptions | None,
    source_url: str | None,
    preserve_pdf_auto: bool,
) -> PreparedDocumentIngestion:
    ingestion_policy = _resolve_document_ingestion_policy(
        db=db,
        tenant_id=tenant_id,
        dataset=dataset,
        filename=filename,
        file_ext=file_ext,
        requested_parser_backend=requested_parser_backend,
        requested_chunk_strategy=requested_chunk_strategy,
        pipeline=pipeline,
        source_url=source_url,
    )
    resolved_pipeline = _resolve_document_pipeline(
        file_ext=file_ext,
        parser_backend_choice=ingestion_policy.parser_backend_choice,
        chunk_strategy_choice=ingestion_policy.chunk_strategy_choice,
        preserve_pdf_auto=preserve_pdf_auto,
    )
    _validate_pipeline_effective_for_strategy(
        dataset=dataset,
        pipeline_options=ingestion_policy.pipeline_options,
        resolved_chunk_strategy=resolved_pipeline.chunk_strategy,
    )
    return PreparedDocumentIngestion(policy=ingestion_policy, pipeline=resolved_pipeline)


def _create_url_ingestion_run(
    *,
    db: Session,
    tenant_id: UUID,
    dataset: Dataset,
    account_id: str,
    ingestion_run_id: UUID | None,
    ingestion_kind: str | None,
    body: UrlUploadRequest,
    url: str,
    source: UrlSourceMetadata,
    pipeline: ResolvedDocumentPipeline,
) -> UUID | None:
    run_cfg = {
        "source_url": url,
        "url_final_url": source.final_url or None,
        "url_canonical_url": source.canonical_url,
        "parser_backend_requested": str(body.parser_backend or "")[:80],
        "chunk_strategy_requested": str(body.chunk_strategy or "")[:80],
        "parser_backend": str(pipeline.parser_backend or "")[:80],
        "chunk_strategy": str(pipeline.chunk_strategy or "")[:80],
    }
    return _create_ingestion_run_if_missing(
        db=db,
        tenant_id=tenant_id,
        dataset=dataset,
        account_id=account_id,
        ingestion_run_id=ingestion_run_id,
        ingestion_kind=ingestion_kind,
        default_kind="upload_url",
        config=run_cfg,
    )


def _create_local_html_ingestion_run(
    *,
    db: Session,
    tenant_id: UUID,
    dataset: Dataset,
    account_id: str,
    ingestion_run_id: UUID | None,
    ingestion_kind: str | None,
    body: LocalHtmlIngestRequest,
    source_url: str | None,
    content_type: str,
    pipeline: ResolvedDocumentPipeline,
) -> UUID | None:
    run_cfg = {
        "source_url": source_url,
        "content_type": content_type,
        "parser_backend_requested": str(body.parser_backend or "")[:80],
        "chunk_strategy_requested": str(body.chunk_strategy or "")[:80],
        "parser_backend": str(pipeline.parser_backend or "")[:80],
        "chunk_strategy": str(pipeline.chunk_strategy or "")[:80],
    }
    return _create_ingestion_run_if_missing(
        db=db,
        tenant_id=tenant_id,
        dataset=dataset,
        account_id=account_id,
        ingestion_run_id=ingestion_run_id,
        ingestion_kind=ingestion_kind,
        default_kind="connector_html",
        config=run_cfg,
    )


def _build_url_document_metadata(
    *,
    body: UrlUploadRequest,
    url: str,
    ingest_file: UrlIngestFile,
    source: UrlSourceMetadata,
    pipeline: ResolvedDocumentPipeline,
) -> dict[str, Any]:
    requested_parser_backend = str(body.parser_backend or "").strip().lower()
    parser_backend_resolved = (
        None
        if pipeline.parser_backend == "auto" and requested_parser_backend in {"", "auto"}
        else pipeline.parser_backend
    )
    return {
        "parser_backend": pipeline.parser_backend,
        "parser_backend_requested": str(body.parser_backend or "").lower(),
        "parser_backend_resolved": parser_backend_resolved,
        "chunk_strategy": pipeline.chunk_strategy,
        "chunk_strategy_requested": str(body.chunk_strategy or "").lower(),
        "source_url": url,
        "source_fetched_at": ingest_file.fetched_at_iso,
        "source_last_modified_at": source.last_modified_at,
        "source_last_modified_source": source.last_modified_source,
        "source_last_modified_raw": source.last_modified_raw,
        "source_etag": source.etag,
        "url_content_type": ingest_file.content_type or None,
        "url_final_url": source.final_url or None,
        "url_canonical_url": source.canonical_url,
        "url_normalized_url": source.normalized_url or None,
        "url_normalized_requested": source.normalized_requested or None,
        "url_normalized_final": source.normalized_final or None,
        "url_normalized_canonical": source.normalized_canonical,
    }


def _build_local_html_document_metadata(
    *,
    body: LocalHtmlIngestRequest,
    source_url: str | None,
    url_normalized: str | None,
    fetched_at_iso: str,
    content_type: str,
    pipeline: ResolvedDocumentPipeline,
) -> dict[str, Any]:
    requested_parser_backend = str(body.parser_backend or "").strip().lower()
    parser_backend_resolved = (
        None
        if pipeline.parser_backend == "auto" and requested_parser_backend in {"", "auto"}
        else pipeline.parser_backend
    )
    return {
        "parser_backend": pipeline.parser_backend,
        "parser_backend_requested": str(body.parser_backend or "").lower(),
        "parser_backend_resolved": parser_backend_resolved,
        "chunk_strategy": pipeline.chunk_strategy,
        "chunk_strategy_requested": str(body.chunk_strategy or "").lower(),
        "source_url": source_url,
        "source_fetched_at": fetched_at_iso,
        "source_last_modified_at": fetched_at_iso,
        "source_last_modified_source": "fallback:fetched_at",
        "source_last_modified_raw": None,
        "source_etag": None,
        "url_content_type": content_type,
        "url_final_url": source_url,
        "url_normalized_url": url_normalized or None,
    }


async def _persist_and_process_ingested_document(
    *,
    db: Session,
    background_tasks: BackgroundTasks | None,
    tenant_id: UUID,
    account_id: str,
    dataset: Dataset,
    file_id: UUID,
    filename: str,
    file_ext: str,
    file_size: int,
    file_path: str | Path,
    processing_file_path: Path,
    source_ref: str | None,
    doc_metadata: dict[str, Any],
    pipeline_hash: str,
    pipeline: ResolvedDocumentPipeline,
    ingestion_run_id: UUID | None,
) -> DBDocument:
    db_document = _create_pending_document_record(
        file_id=file_id,
        tenant_id=tenant_id,
        dataset=dataset,
        filename=filename,
        file_ext=file_ext,
        file_size=file_size,
        file_path=file_path,
        account_id=account_id,
        doc_metadata=doc_metadata,
    )
    if bool(settings.UPLOAD_DEDUP_ENABLED):
        db_document.dedup_key = build_document_dedup_key(
            content_sha256=get_content_sha256(doc_metadata),
            pipeline_hash=pipeline_hash,
        )
    keep_local_processing_file = False
    try:
        db.add(db_document)
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
        await _cleanup_unpersisted_ingested_source(
            str(file_path),
            document_metadata=dict(getattr(db_document, "doc_metadata", None) or {}),
        )
        _unlink_ingest_temp(processing_file_path)
        raise

    try:
        db.commit()
    except IntegrityError as exc:
        with contextlib.suppress(Exception):
            db.rollback()
        duplicate = (
            _find_duplicate_document_for_persist_conflict(db, db_document=db_document)
            if _is_document_dedup_integrity_error(exc)
            else None
        )
        await _cleanup_unpersisted_ingested_source(
            str(file_path),
            document_metadata=dict(getattr(db_document, "doc_metadata", None) or {}),
        )
        _unlink_ingest_temp(processing_file_path)
        if duplicate is not None:
            raise _DuplicatePersistedDocumentError(duplicate) from exc
        raise
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
        await _cleanup_commit_ambiguous_ingested_source(
            document_id=file_id,
            stored_path=str(file_path),
            file_path=processing_file_path,
            document_metadata=dict(getattr(db_document, "doc_metadata", None) or {}),
        )
        raise

    try:
        db.refresh(db_document)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Document committed but refresh failed: %s", str(exc)[:200])

    with contextlib.suppress(Exception):
        reconcile_document_index_channels(
            db,
            document=db_document,
            pipeline_hash=pipeline_hash,
            reset_enabled_to_pending=True,
            commit=True,
        )

    _add_document_to_ingestion_run(
        db=db,
        tenant_id=tenant_id,
        ingestion_run_id=ingestion_run_id,
        db_document=db_document,
        source_ref=source_ref,
        doc_metadata=doc_metadata,
    )
    try:
        keep_local_processing_file = await schedule_document_processing(
            db=db,
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            document_id=file_id,
            file_path=processing_file_path,
            requested_by=account_id,
            pipeline_hash=pipeline_hash,
            parser_backend=pipeline.parser_backend,
            chunk_strategy=pipeline.chunk_strategy,
            db_document=db_document,
        )
    finally:
        if is_object_storage_uri(str(file_path)) and not keep_local_processing_file:
            _unlink_ingest_temp(processing_file_path)
    return db_document


async def _ingest_url_upload_request(
    *,
    background_tasks: BackgroundTasks | None,
    body: UrlUploadRequest,
    tenant_id: UUID,
    account_id: str,
    db: Session,
    ingestion_run_id: UUID | None = None,
    ingestion_kind: str | None = None,
) -> DBDocument:
    """
    Shared implementation for URL ingestion.

    - Used by API endpoint and connector runs.
    - If task queue is disabled and `background_tasks` is None, processing runs inline (async).
    """
    if not bool(settings.URL_INGEST_ENABLED):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    url = await validate_url_for_ingest(str(body.url or ""))
    dataset = dataset_service.resolve_writable_dataset(db, tenant_id, account_id, body.dataset_id)
    ingest_file = await _download_url_ingest_file(url=url, body=body, tenant_id=tenant_id)
    source = await _url_source_metadata(url=url, ingest_file=ingest_file)
    safe_name = _sanitize_filename(body.filename or Path(ingest_file.final_path).name)
    prepared = _prepare_document_ingestion(
        db=db,
        tenant_id=tenant_id,
        dataset=dataset,
        filename=safe_name,
        file_ext=ingest_file.file_ext,
        requested_parser_backend=body.parser_backend,
        requested_chunk_strategy=body.chunk_strategy,
        pipeline=body.pipeline,
        source_url=url,
        preserve_pdf_auto=True,
    )
    ingestion_run_id = _create_url_ingestion_run(
        db=db,
        tenant_id=tenant_id,
        dataset=dataset,
        account_id=account_id,
        ingestion_run_id=ingestion_run_id,
        ingestion_kind=ingestion_kind,
        body=body,
        url=url,
        source=source,
        pipeline=prepared.pipeline,
    )

    doc_metadata = _build_url_document_metadata(
        body=body,
        url=url,
        ingest_file=ingest_file,
        source=source,
        pipeline=prepared.pipeline,
    )
    doc_metadata, pipeline_hash = _finalize_document_metadata(
        doc_metadata,
        content_sha256=ingest_file.content_sha256,
        pipeline_options=prepared.policy.pipeline_options,
        ingestion_meta=prepared.policy.ingestion_meta,
        ingestion_run_id=ingestion_run_id,
        ingestion_kind=ingestion_kind,
        default_kind="upload_url",
        parser_backend_resolved=str(doc_metadata.get("parser_backend_resolved") or "").strip() or None,
    )

    if bool(settings.UPLOAD_DEDUP_ENABLED) and ingest_file.content_sha256:
        duplicate = _find_duplicate_document(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset.id,
            file_sha256=ingest_file.content_sha256,
            pipeline_hash=pipeline_hash,
        )
        if duplicate is not None:
            with contextlib.suppress(OSError):
                ingest_file.final_path.unlink(missing_ok=True)
            return await _reuse_duplicate_document_for_ingest(
                background_tasks=background_tasks,
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                duplicate=duplicate,
                content_sha256=ingest_file.content_sha256,
                pipeline_hash=pipeline_hash,
            )

    file_size = int(ingest_file.downloaded.size_bytes)
    _enforce_url_upload_quota(db, tenant_id=tenant_id, additional_bytes=file_size, final_path=ingest_file.final_path)
    stored_path = await _store_ingested_source(
        file_path=ingest_file.final_path,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        document_id=ingest_file.file_id,
        extension=ingest_file.file_ext,
        content_type=ingest_file.content_type or None,
    )
    if is_object_storage_uri(stored_path):
        store = get_document_object_store()
        if store is not None:
            doc_metadata.update(document_object_store_metadata(store))

    try:
        return await _persist_and_process_ingested_document(
            db=db,
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset=dataset,
            file_id=ingest_file.file_id,
            filename=safe_name,
            file_ext=ingest_file.file_ext,
            file_size=file_size,
            file_path=stored_path,
            processing_file_path=ingest_file.final_path,
            source_ref=url,
            doc_metadata=doc_metadata,
            pipeline_hash=pipeline_hash,
            pipeline=prepared.pipeline,
            ingestion_run_id=ingestion_run_id,
        )
    except _DuplicatePersistedDocumentError as exc:
        return await _reuse_duplicate_document_for_ingest(
            background_tasks=background_tasks,
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            duplicate=exc.document,
            content_sha256=ingest_file.content_sha256,
            pipeline_hash=pipeline_hash,
        )


def _duplicate_document_query(db: Session, *, tenant_id: UUID, dataset_id: UUID):
    return (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
        )
        .order_by(DBDocument.updated_at.desc(), DBDocument.created_at.desc())
    )


def _scan_duplicate_documents(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    max_scan: int,
    predicate: Any,
) -> DBDocument | None:
    docs = (
        _duplicate_document_query(db, tenant_id=tenant_id, dataset_id=dataset_id)
        .limit(max(1, int(max_scan or 5000)))
        .all()
    )
    for doc in docs or []:
        meta = dict(getattr(doc, "doc_metadata", None) or {})
        if predicate(meta):
            return doc
    return None


def _find_duplicate_document(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    file_sha256: str,
    pipeline_hash: str,
    max_scan: int = 5000,
) -> DBDocument | None:
    if dataset_id is None:
        return None
    sha = str(file_sha256 or "").strip().lower()
    ph = str(pipeline_hash or "").strip()
    if not sha or not ph:
        return None

    try:
        return (
            _duplicate_document_query(db, tenant_id=tenant_id, dataset_id=dataset_id)
            .filter(
                (DBDocument.doc_metadata["content_sha256"].astext == sha)  # type: ignore[attr-defined]
                | (DBDocument.doc_metadata["file_sha256"].astext == sha)  # type: ignore[attr-defined]
            )
            .filter(DBDocument.doc_metadata["pipeline_hash"].astext == ph)  # type: ignore[attr-defined]
            .first()
        )
    except Exception:
        return _scan_duplicate_documents(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            max_scan=max_scan,
            predicate=lambda meta: (
                get_content_sha256(meta) == sha and str(meta.get("pipeline_hash") or "").strip() == ph
            ),
        )


def _find_duplicate_document_by_sha(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    file_sha256: str,
    max_scan: int = 5000,
) -> DBDocument | None:
    if dataset_id is None:
        return None
    sha = str(file_sha256 or "").strip().lower()
    if not sha:
        return None

    try:
        return (
            _duplicate_document_query(db, tenant_id=tenant_id, dataset_id=dataset_id)
            .filter(
                (DBDocument.doc_metadata["content_sha256"].astext == sha)  # type: ignore[attr-defined]
                | (DBDocument.doc_metadata["file_sha256"].astext == sha)  # type: ignore[attr-defined]
            )
            .first()
        )
    except Exception:
        return _scan_duplicate_documents(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            max_scan=max_scan,
            predicate=lambda meta: get_content_sha256(meta) == sha,
        )


async def _reuse_duplicate_document_for_ingest(
    *,
    background_tasks: BackgroundTasks | None,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    duplicate: DBDocument,
    content_sha256: str,
    pipeline_hash: str,
) -> DBDocument:
    status0 = str(getattr(duplicate, "status", "") or "").strip().lower()
    if status0 in {"pending", "processing"}:
        if _document_matches_dedup_identity(
            duplicate,
            content_sha256=content_sha256,
            pipeline_hash=pipeline_hash,
        ):
            return duplicate
        raise HTTPException(status_code=409, detail=DUPLICATE_DOCUMENT_PROCESSING_DETAIL)

    meta = dict(getattr(duplicate, "doc_metadata", None) or {})
    sync_pipeline_execution_identity(
        meta,
        content_sha256=content_sha256,
        pipeline_hash=pipeline_hash,
        parser_backend_resolved=str(meta.get("parser_backend_resolved") or "").strip() or None,
    )
    duplicate.doc_metadata = meta
    if hasattr(duplicate, "dedup_key"):
        duplicate.dedup_key = build_document_dedup_key(content_sha256=content_sha256, pipeline_hash=pipeline_hash)
    db.commit()
    db.refresh(duplicate)

    if status0 == "failed":
        if background_tasks is None:
            raise HTTPException(status_code=409, detail="Failed duplicate requires retry scheduling context")
        await retry_document_processing(
            document_id=duplicate.id,
            background_tasks=background_tasks,
            force=True,
            skip_if_unchanged=True,
            tenant_id=tenant_id,
            account_id=account_id,
            db=db,
        )
        db.refresh(duplicate)
    return duplicate


@dataclass
class PipelineOverridesFormFields:
    governance_enabled: bool | None = Form(None)
    governance_remove_toc_lines: bool | None = Form(None)
    governance_remove_noise_lines: bool | None = Form(None)
    governance_unwrap_lines: bool | None = Form(None)
    governance_remove_common_lines: bool | None = Form(None)
    governance_unwrap_max_line_length: int | None = Form(None)
    governance_noise_min_chars: int | None = Form(None)
    governance_noise_ratio_threshold: float | None = Form(None)
    governance_common_lines_min_docs: int | None = Form(None)
    governance_common_lines_min_ratio: float | None = Form(None)
    chunk_size: int | None = Form(None)
    chunk_overlap: int | None = Form(None)
    chunk_vector_enabled: bool | None = Form(None)
    bm25_index_enabled: bool | None = Form(None)
    kg_enabled: bool | None = Form(None)
    event_vector_enabled: bool | None = Form(None)
    entity_vector_enabled: bool | None = Form(None)


@dataclass
class UploadDocumentFormFields:
    parser_backend: str = Form(settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Form(settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: str | None = Form(None)
    dataset_id: UUID | None = Form(None)
    user_metadata: str | None = Form(None)


@dataclass
class UploadDocumentsBatchFormFields:
    parser_backend: str = Form(settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Form(settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: str | None = Form(None)
    dataset_id: UUID | None = Form(None)
    precheck_first: bool = Form(False)
    user_metadata_map: str | None = Form(None)
    max_concurrent: int = Form(5)


async def _ingest_local_html_request(
    *,
    background_tasks: BackgroundTasks | None,
    body: LocalHtmlIngestRequest,
    tenant_id: UUID,
    account_id: str,
    db: Session,
    ingestion_run_id: UUID | None = None,
    ingestion_kind: str | None = None,
) -> DBDocument:
    """
    Shared implementation for connector-style ingestion of local HTML content.

    Notes:
    - Kept queue-aware, similar to URL ingest:
      - Enqueue when task queue is enabled
      - Otherwise, when `background_tasks` is None, run inline (connector context)
    - Currently gated by URL_INGEST_ENABLED for backward-compatible security semantics.
    """
    if not bool(settings.URL_INGEST_ENABLED):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    dataset = dataset_service.resolve_writable_dataset(db, tenant_id, account_id, body.dataset_id)
    ingest_file = _write_local_html_ingest_file(body=body, tenant_id=tenant_id)
    content_type = "text/html"
    source_url = str(body.source_url or "").strip() or None
    url_normalized = normalize_url_for_dedup(source_url) if source_url else None

    prepared = _prepare_document_ingestion(
        db=db,
        tenant_id=tenant_id,
        dataset=dataset,
        filename=ingest_file.filename,
        file_ext=ingest_file.file_ext,
        requested_parser_backend=body.parser_backend,
        requested_chunk_strategy=body.chunk_strategy,
        pipeline=body.pipeline,
        source_url=source_url,
        preserve_pdf_auto=False,
    )
    ingestion_run_id = _create_local_html_ingestion_run(
        db=db,
        tenant_id=tenant_id,
        dataset=dataset,
        account_id=account_id,
        ingestion_run_id=ingestion_run_id,
        ingestion_kind=ingestion_kind,
        body=body,
        source_url=source_url,
        content_type=content_type,
        pipeline=prepared.pipeline,
    )

    doc_metadata = _build_local_html_document_metadata(
        body=body,
        source_url=source_url,
        url_normalized=url_normalized,
        fetched_at_iso=ingest_file.fetched_at_iso,
        content_type=content_type,
        pipeline=prepared.pipeline,
    )
    doc_metadata, pipeline_hash = _finalize_document_metadata(
        doc_metadata,
        content_sha256=ingest_file.content_sha256,
        pipeline_options=prepared.policy.pipeline_options,
        ingestion_meta=prepared.policy.ingestion_meta,
        ingestion_run_id=ingestion_run_id,
        ingestion_kind=ingestion_kind,
        default_kind="connector_html",
        parser_backend_resolved=str(doc_metadata.get("parser_backend_resolved") or "").strip() or None,
    )
    if bool(settings.UPLOAD_DEDUP_ENABLED) and ingest_file.content_sha256:
        duplicate = _find_duplicate_document(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset.id,
            file_sha256=ingest_file.content_sha256,
            pipeline_hash=pipeline_hash,
        )
        if duplicate is not None:
            with contextlib.suppress(OSError):
                ingest_file.file_path.unlink(missing_ok=True)
            return await _reuse_duplicate_document_for_ingest(
                background_tasks=background_tasks,
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                duplicate=duplicate,
                content_sha256=ingest_file.content_sha256,
                pipeline_hash=pipeline_hash,
            )

    _enforce_url_upload_quota(
        db,
        tenant_id=tenant_id,
        additional_bytes=ingest_file.file_size,
        final_path=ingest_file.file_path,
    )
    stored_path = await _store_ingested_source(
        file_path=ingest_file.file_path,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        document_id=ingest_file.file_id,
        extension=ingest_file.file_ext,
        content_type=content_type,
    )
    if is_object_storage_uri(stored_path):
        store = get_document_object_store()
        if store is not None:
            doc_metadata.update(document_object_store_metadata(store))

    try:
        return await _persist_and_process_ingested_document(
            db=db,
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset=dataset,
            file_id=ingest_file.file_id,
            filename=ingest_file.filename,
            file_ext=ingest_file.file_ext,
            file_size=ingest_file.file_size,
            file_path=stored_path,
            processing_file_path=ingest_file.file_path,
            source_ref=(source_url or ingest_file.filename)[:1000] if (source_url or ingest_file.filename) else None,
            doc_metadata=doc_metadata,
            pipeline_hash=pipeline_hash,
            pipeline=prepared.pipeline,
            ingestion_run_id=ingestion_run_id,
        )
    except _DuplicatePersistedDocumentError as exc:
        return await _reuse_duplicate_document_for_ingest(
            background_tasks=background_tasks,
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            duplicate=exc.document,
            content_sha256=ingest_file.content_sha256,
            pipeline_hash=pipeline_hash,
        )


document_upload = importlib.import_module("app.api.v1.document_upload")
router.include_router(document_upload.router)

upload_document = document_upload.upload_document
upload_document_from_url = document_upload.upload_document_from_url
upload_documents_batch = document_upload.upload_documents_batch


def _resolve_active_doc_pipeline_key(document_id: UUID, doc_metadata: dict) -> str:
    active_hash = str(
        (doc_metadata or {}).get("active_pipeline_hash") or (doc_metadata or {}).get("pipeline_hash") or ""
    ).strip()
    return f"{document_id}:{active_hash}" if active_hash else str(document_id)


def _apply_chunk_metadata_patch(*, current: dict, patch: dict) -> dict:
    next_meta = dict(current or {})
    for key, value in (patch or {}).items():
        if not isinstance(key, str) or not key.strip():
            continue
        k = key.strip()
        if value is None:
            next_meta.pop(k, None)
        else:
            next_meta[k] = value
    return next_meta


def _normalize_index_consistency_strictness(*, patch_mode: bool = False) -> str:
    strictness = str(settings.INDEX_CONSISTENCY_STRICTNESS or "off").strip().lower()
    if strictness not in {"off", "warn", "strict"}:
        strictness = "off"
    enabled = bool(settings.INDEX_CONSISTENCY_ENABLED)
    patch_strict = bool(settings.INDEX_CONSISTENCY_PATCH_CHUNK_STRICT)
    if patch_mode and patch_strict:
        return "strict"
    if not enabled and strictness != "strict":
        return "off"
    return strictness


def _build_index_channel_result(
    *,
    status: str,
    attempted: bool,
    error: str | None = None,
    vector_id: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": str(status or "skipped"),
        "attempted": bool(attempted),
    }
    if error:
        out["error"] = str(error)[:240]
    if vector_id:
        out["vector_id"] = str(vector_id)[:200]
    return out


def _index_channel_status(value: dict[str, Any] | None) -> str:
    return str((value or {}).get("status") or "skipped").strip().lower()


def _index_drift_marker_rows(drift_markers: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [dict(marker) for marker in (drift_markers or []) if isinstance(marker, dict)][:20]


def _build_chunk_index_operation_result(
    *,
    operation: str,
    strictness: str,
    vector: dict[str, Any],
    bm25: dict[str, Any],
    kg: dict[str, Any] | None = None,
    reconcile: dict[str, Any] | None = None,
    drift_markers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    vector_status = _index_channel_status(vector)
    bm25_status = _index_channel_status(bm25)
    kg_status = _index_channel_status(kg) if isinstance(kg, dict) else "skipped"
    success = all(st in {"ok", "skipped"} for st in (vector_status, bm25_status, kg_status))
    return {
        "schema": "mimirq.index_operation_result.v1",
        "operation": str(operation or "").strip()[:80] or CHUNK_PATCH_OPERATION,
        "strictness": str(strictness or "off").strip().lower(),
        "success": bool(success),
        "vector": dict(vector or {}),
        "bm25": dict(bm25 or {}),
        "kg": (dict(kg or {}) if isinstance(kg, dict) else None),
        "reconcile": (dict(reconcile or {}) if isinstance(reconcile, dict) else None),
        "drift_markers": _index_drift_marker_rows(drift_markers),
    }


def _persist_chunk_index_operation_result(
    *,
    db: Session,
    chunk: DocumentChunk,
    result: dict[str, Any],
    drift_markers: list[dict[str, Any]] | None = None,
) -> None:
    meta = dict(getattr(chunk, "doc_metadata", None) or {})
    meta["index_operation_result"] = dict(result or {})

    if drift_markers:
        existing = meta.get("index_drift_markers")
        existing_rows = [dict(x) for x in existing if isinstance(x, dict)] if isinstance(existing, list) else []
        merged = existing_rows + [dict(x) for x in drift_markers if isinstance(x, dict)]
        meta["index_drift_markers"] = merged[-20:]

    chunk.doc_metadata = meta
    db.commit()
    with contextlib.suppress(Exception):
        db.refresh(chunk)


async def _enqueue_index_drift_reconcile(
    *,
    tenant_id: UUID,
    document_id: UUID,
    requested_by: str,
) -> str | None:
    if not bool(settings.TASK_QUEUE_ENABLED):
        return None

    try:
        from app.tasks.queue import enqueue_rebuild_indexes

        return await enqueue_rebuild_indexes(
            tenant_id=tenant_id,
            document_id=document_id,
            requested_by=str(requested_by or "system:index-drift"),
            job_id=f"index-drift-reconcile:{tenant_id}:{document_id}",
        )
    except Exception:
        return None


def _build_chunk_drift_markers(
    *,
    operation: str,
    strictness: str,
    tenant_id: UUID,
    document_id: UUID,
    chunk: DocumentChunk,
    vector_error: str | None,
    bm25_error: str | None,
    emit_drift_markers: bool,
) -> list[dict[str, Any]]:
    drift_markers: list[dict[str, Any]] = []
    if emit_drift_markers and vector_error:
        drift_markers.append(
            build_index_drift_marker(
                operation=operation,
                strictness=strictness,
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_id=chunk.id,
                channel="vector",
                reason=vector_error,
            )
        )
    if emit_drift_markers and bm25_error:
        drift_markers.append(
            build_index_drift_marker(
                operation=operation,
                strictness=strictness,
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_id=chunk.id,
                channel="bm25",
                reason=bm25_error,
            )
        )
    return drift_markers


async def _record_chunk_index_drift(
    *,
    db: Session,
    document: DBDocument,
    chunk: DocumentChunk,
    tenant_id: UUID,
    account_id: str,
    operation: str,
    strictness: str,
    vector_error: str | None,
    bm25_error: str | None,
    vector_id_after: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    from app.services.index_audit_service import record_index_drift_item

    emit_drift_markers = bool(settings.INDEX_CONSISTENCY_EMIT_DRIFT_MARKERS)
    drift_markers = _build_chunk_drift_markers(
        operation=operation,
        strictness=strictness,
        tenant_id=tenant_id,
        document_id=document.id,
        chunk=chunk,
        vector_error=vector_error,
        bm25_error=bm25_error,
        emit_drift_markers=emit_drift_markers,
    )
    reconcile_task_id: str | None = None
    reconcile_result: dict[str, Any] | None = None
    auto_reconcile_supported = vector_error is None and bm25_error is not None
    if drift_markers and auto_reconcile_supported:
        reconcile_task_id = await _enqueue_index_drift_reconcile(
            tenant_id=tenant_id,
            document_id=document.id,
            requested_by=account_id,
        )
        if reconcile_task_id:
            reconcile_result = {
                "status": "enqueued",
                "scope": "document",
                "channels": ["bm25"],
                "task_id": reconcile_task_id,
            }
        else:
            reconcile_result = {
                "status": "not_enqueued",
                "scope": "document",
                "channels": ["bm25"],
                "reason": "queue_disabled_duplicate_or_unavailable",
            }
    elif drift_markers and vector_error is not None:
        reconcile_result = {
            "status": "unsupported",
            "reason": "document_scoped_auto_reconcile_only_supports_bm25",
        }
    elif drift_markers:
        reconcile_result = {
            "status": "skipped",
        }

    if drift_markers:
        for marker in drift_markers:
            with contextlib.suppress(Exception):
                record_index_drift_item(
                    db=db,
                    dataset_id=getattr(document, "dataset_id", None),
                    marker=marker,
                    reconcile_task_id=(reconcile_task_id if marker.get("channel") == "bm25" else None),
                )

    vector_result = _build_index_channel_result(
        status=("error" if vector_error else "ok"),
        attempted=True,
        error=vector_error,
        vector_id=vector_id_after,
    )
    bm25_result = _build_index_channel_result(
        status=("error" if bm25_error else "ok"),
        attempted=True,
        error=bm25_error,
    )
    operation_result = _build_chunk_index_operation_result(
        operation=operation,
        strictness=strictness,
        vector=vector_result,
        bm25=bm25_result,
        kg=None,
        reconcile=reconcile_result,
        drift_markers=drift_markers,
    )
    _persist_chunk_index_operation_result(
        db=db,
        chunk=chunk,
        result=operation_result,
        drift_markers=drift_markers,
    )
    return operation_result, drift_markers, reconcile_task_id


document_chunks_write = importlib.import_module("app.api.v1.document_chunks_write")
create_document_chunk = document_chunks_write.create_document_chunk
patch_document_chunk = document_chunks_write.patch_document_chunk
delete_document_chunk = document_chunks_write.delete_document_chunk
disable_document_chunk = document_chunks_write.disable_document_chunk
enable_document_chunk = document_chunks_write.enable_document_chunk
reembed_document_chunks = document_chunks_write.reembed_document_chunks
router.include_router(document_chunks_write.router)


document_lifecycle_service = importlib.import_module("app.services.document_lifecycle_service")
_get_document_for_delete = document_lifecycle_service._get_document_for_delete
_assert_document_delete_permission = document_lifecycle_service._assert_document_delete_permission
_cancel_processing_document = document_lifecycle_service._cancel_processing_document
_document_task_ids = document_lifecycle_service._document_task_ids
_abort_document_tasks_before_delete = document_lifecycle_service._abort_document_tasks_before_delete
_add_document_metadata_img_ids = document_lifecycle_service._add_document_metadata_img_ids
_add_chunk_metadata_img_ids = document_lifecycle_service._add_chunk_metadata_img_ids
_delete_document_minio_images = document_lifecycle_service._delete_document_minio_images
_delete_document_table_store = document_lifecycle_service._delete_document_table_store
_delete_minio_document_object = document_lifecycle_service._delete_minio_document_object
_delete_local_document_file = document_lifecycle_service._delete_local_document_file
_delete_document_file = document_lifecycle_service._delete_document_file
_touch_dataset_updated_after_delete = document_lifecycle_service._touch_dataset_updated_after_delete
_delete_document_record = document_lifecycle_service._delete_document_record
_cleanup_document_kg_artifacts = document_lifecycle_service._cleanup_document_kg_artifacts
_delete_document_lifecycle = document_lifecycle_service._delete_document_lifecycle

document_chunk_preview = importlib.import_module("app.api.v1.document_chunk_preview")
router.include_router(document_chunk_preview.router)

ChunkPreviewRequestFields = document_chunk_preview.ChunkPreviewRequestFields
ChunkPreviewByShaFileFields = document_chunk_preview.ChunkPreviewByShaFileFields
preview_chunking = document_chunk_preview.preview_chunking
preview_chunking_by_sha = document_chunk_preview.preview_chunking_by_sha
