"""
Document management API.
"""
import asyncio
import contextlib
import hashlib
import importlib
import json
import math
import os
import re
import shutil
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from langchain_core.documents import Document
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id, get_current_account_id_from_headers
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import (
    ChunkPreviewItem,
    ChunkPreviewParams,
    ChunkPreviewQualityGate,
    ChunkPreviewQualityReason,
    ChunkPreviewRecommendationPatch,
    ChunkPreviewResponse,
    ChunkPreviewReviewSignals,
    ChunkPreviewStats,
    DocumentBatchUploadResponse,
    DocumentDetail,
    DocumentParsePreview,
    DocumentPipelineOptions,
    ParsedSegment,
)
from app.api.utils.upload import save_upload_file, save_upload_file_with_hash
from app.api.utils.url_ingest import download_url_to_path, validate_url_for_ingest
from app.api.v1 import (
    document_access,
    document_assets,
    document_batch_upload,
    document_batches,
    document_batches_lifecycle,
    document_chunks_read,
    document_content,
    document_detail,
    document_duplicates,
    document_folders,
    document_health,
    document_lifecycle,
    document_listing,
    document_manual,
    document_mutations,
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
from app.core.database import SessionLocal, get_db
from app.core.env import is_production_env
from app.core.token_utils import estimate_tokens, num_tokens_from_string
from app.models.dataset import Dataset, DatasetPermissionEnum
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk, DocumentPermission
from app.parsing.factory import parser_factory
from app.parsing.processors.processor import document_processor
from app.parsing.subprocess_runner import SubprocessCancelled, SubprocessWorkerError, run_subprocess_worker
from app.rag.chunking.factory import chunker_factory
from app.rag.chunking.strategies.separator import SeparatorChunker
from app.rag.core.logging import get_logger
from app.rag.preprocessing.html_canonical import extract_canonical_url, normalize_url_for_dedup
from app.rag.preprocessing.processor import governance_processor
from app.rag.preprocessing.rules import build_governance_rules
from app.services.audit_log_service import audit_log_event
from app.services.dataset_precheck_ingestion_suggestion import apply_ingestion_policy_suggestion
from app.services.dataset_precheck_scan_runner import run_dataset_precheck_scan
from app.services.dataset_service import EDIT_ROLES, DatasetService
from app.services.document_permission_service import DocumentGroupPermissionService
from app.services.index_audit_service import build_index_drift_marker
from app.services.indexer import Indexer
from app.services.ingestion_policy import (
    match_ingestion_rule,
    parse_ingestion_policy_from_metadata,
    resolve_governance_profile_ref,
)
from app.services.ingestion_run_service import IngestionRunService
from app.services.pipeline_config import (
    merge_pipeline_options,
    resolve_pipeline_effective,
    upsert_pipeline_metadata,
)
from app.services.preview_cache import ParseCacheEntry, preview_parse_cache, preview_parse_locks
from app.services.tenant_group_service import TenantGroupService
from app.storage.object.minio import is_minio_uri, minio_service, parse_minio_uri
from app.tasks.queue import enqueue_document_processing
from app.types.document_analytics import compute_document_analytics
from app.types.pipeline import PipelineOptions

logger = get_logger("api.documents")

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
router.include_router(document_chunks_read.router)
router.include_router(document_content.router)
router.include_router(document_detail.router)
router.include_router(document_duplicates.router)
router.include_router(document_folders.router)
router.include_router(document_health.router)
router.include_router(document_lifecycle.router)
router.include_router(document_listing.router)
router.include_router(document_manual.router)
router.include_router(document_mutations.router)
router.include_router(document_processing.router)
router.include_router(document_stats.router)
router.include_router(document_timeline.router)
router.include_router(document_versions.router)

# Filename validation:
# - We store uploads by UUID on disk/MinIO, so we don't need a strict character allowlist.
# - Still reject path separators / control characters to prevent path traversal and header issues.
UUID_PATTERN = r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
PREVIEW_IMAGE_REF_RE = re.compile(rf"(?:https?://[^\s)\"']+)?/api/v1/documents/image/({UUID_PATTERN})")
MINIO_IMAGE_REF_RE = re.compile(r"(?:https?://[^\s)\"']+)?/api/v1/documents/image-url/([^\s)\"']+)")
# Position tags emitted by some PDF parsers (used for PDF overlay highlighting).
POSITION_TAG_RE = re.compile(r"@@([0-9-]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##")

_TIMELINE_REDACT_KEYS = {
    "content",
    "text",
    "markdown",
    "html",
    "raw",
    "prompt",
    "question",
    "answer",
    "secret",
    "token",
    "password",
    "api_key",
}

DOC_NOT_FOUND_DETAIL = 'Document not found'
INVALID_RANGE_HEADER_DETAIL = 'Invalid Range header'
IMAGE_NOT_FOUND_DETAIL = 'Image not found'
IMAGE_JPEG_MEDIA_TYPE = 'image/jpeg'
DUPLICATE_DOCUMENT_PROCESSING_DETAIL = 'Duplicate document is currently processing'
HTML_FILE_EXTENSION = '.html'
PIPELINE_HASH_TOO_LONG_DETAIL = 'pipeline_hash too long'
FILENAME_INVALID_CHARS_DETAIL = 'Filename contains invalid characters'
CHUNK_NOT_FOUND_DETAIL = 'Chunk not found'
CHUNK_NOT_ACTIVE_PIPELINE_DETAIL = 'Chunk is not in the active pipeline version'
DOCUMENT_FILE_ACCESS_DENIED_DETAIL = 'Document file access denied'
DOCUMENT_FILE_NOT_FOUND_DETAIL = 'Document file not found'
NO_DOCUMENT_ACCESS_DETAIL = 'No document access'
DATA_IMAGE_PREFIX = 'data:image'
CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL = 'chunk_overlap must be less than chunk_size'
MANUAL_FILE_PATH_PREFIX = 'manual://'
IMAGE_FILE_EXT_JPEG = '.jpeg'
IMAGE_FILE_EXT_WEBP = '.webp'
CHUNK_PATCH_OPERATION = 'chunk.patch'


def _asset_cache_control(*, token_in_url: bool, max_age: int) -> str:
    if token_in_url:
        return "no-store"
    if max_age > 0:
        return f"private, max-age={max_age}"
    return "no-cache"


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
        escaped = raw.replace("\"", "\\\"")
        return json.loads(f"\"{escaped}\"")
    except Exception:
        return raw


def _sanitize_timeline_details(details: Any) -> dict[str, Any]:
    """
    Best-effort PII-minimal details projection for user-facing timelines.

    Audit logs should already be small, but timeline is displayed broadly; keep it safe by default.
    """
    if not isinstance(details, dict):
        return {}

    out: dict[str, Any] = {}
    for k, v in details.items():
        key = str(k or "").strip()
        if not key:
            continue
        lowered = key.lower()
        if lowered in _TIMELINE_REDACT_KEYS:
            continue

        # Bound large strings/objects to avoid leaking raw content.
        if isinstance(v, str):
            vv = v.strip()
            if len(vv) > 400:
                out[key] = vv[:400] + "..."
            else:
                out[key] = vv
            continue

        if v is None or isinstance(v, (int, float, bool)):
            out[key] = v
            continue

        try:
            dumped = json.dumps(v, ensure_ascii=True, default=str)
            if len(dumped) > 800:
                out[key] = "<redacted>"
            else:
                out[key] = v
        except Exception:
            out[key] = "<redacted>"

    return out


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


def _ensure_preview_page_indices(documents: list[Document]) -> None:
    """
    Ensure each parsed Document has a stable per-document index for preview offset rebasing.

    Some parsers emit multiple Documents without a unique `metadata.page` (or with duplicates).
    Chunk preview joins these docs with "\\n" and returns global `start_index`/`end_index` offsets;
    without a stable key, mapping by `page` can collide and misplace chunks.
    """
    for i, doc in enumerate(documents or []):
        meta = dict(getattr(doc, "metadata", None) or {})
        # Keep existing value if present; otherwise assign a deterministic 1-based index.
        meta.setdefault("page_index", i + 1)
        doc.metadata = meta


def _preview_chunk_has_asset(meta: dict[str, Any], content: str | None = None) -> bool:
    doc_type = str(meta.get("doc_type_kwd") or "").lower()
    if doc_type in {"image", "table"}:
        return True
    if meta.get("image") is not None:
        return True
    if isinstance(meta.get("image_path"), str) and meta.get("image_path").strip():
        return True
    if meta.get("img_id") or meta.get("image_id") or meta.get("image_url"):
        return True
    if content:
        lower = str(content).lower()
        if (DATA_IMAGE_PREFIX in lower) or PREVIEW_IMAGE_REF_RE.search(content) or MINIO_IMAGE_REF_RE.search(content):
            return True
    return False


def _merge_small_chunks_preview(
    *,
    documents: list[Document],
    chunks: list[Document],
    min_chars: int,
) -> list[Document]:
    """
    Preview-time merge of very short chunks (local offsets per parsed Document).

    Notes:
    - Only merges within the same `page_index`.
    - Preserves assets and parent/child semantics (skips those chunks).
    - Keeps `start_char`/`end_char` in *local* coordinates; rebasing happens later.
    """
    min_chars = max(0, int(min_chars or 0))
    if min_chars <= 0 or not documents or not chunks:
        return chunks

    # page_index -> text
    page_text: dict[int, str] = {}
    for i, doc in enumerate(documents):
        meta = dict(getattr(doc, "metadata", None) or {})
        try:
            pi = int(meta.get("page_index") or (i + 1))
        except Exception:
            pi = i + 1
        page_text[pi] = str(doc.page_content or "")

    def _page_index_of(c: Document) -> int | None:
        meta = getattr(c, "metadata", None) or {}
        raw = meta.get("page_index")
        try:
            return int(raw) if raw is not None else None
        except Exception:
            return None

    def _local_range(meta: dict[str, Any]) -> tuple[int, int] | None:
        try:
            s = int(meta.get("start_char")) if meta.get("start_char") is not None else None
            e = int(meta.get("end_char")) if meta.get("end_char") is not None else None
        except Exception:
            return None
        if s is None or e is None:
            return None
        if e < s:
            return None
        return s, e

    def _merge_two(a: Document, b: Document, *, page_index: int) -> Document | None:
        text = page_text.get(page_index)
        if text is None:
            return None
        ma = dict(getattr(a, "metadata", None) or {})
        mb = dict(getattr(b, "metadata", None) or {})
        ra = _local_range(ma)
        rb = _local_range(mb)
        if ra is None or rb is None:
            return None

        start_local = min(ra[0], rb[0])
        end_local = max(ra[1], rb[1])
        start_local = max(0, min(start_local, len(text)))
        end_local = max(start_local, min(end_local, len(text)))
        merged_text = text[start_local:end_local]

        ma["start_char"] = start_local
        ma["end_char"] = end_local
        ma["merged_small_chunks"] = int(ma.get("merged_small_chunks") or 0) + 1
        return Document(page_content=merged_text, metadata=ma, id=getattr(a, "id", None))

    out: list[Document] = []
    pending: Document | None = None
    pending_page: int | None = None

    for c in chunks:
        page_index = _page_index_of(c)
        if pending is not None and page_index != pending_page:
            out.append(pending)
            pending = None
            pending_page = None

        meta = dict(getattr(c, "metadata", None) or {})
        mergeable = (
            page_index is not None
            and page_index in page_text
            and not _preview_chunk_has_asset(meta, c.page_content or "")
            and not (meta.get("chunk_role") or meta.get("parent_id"))
            and _local_range(meta) is not None
        )
        if not mergeable:
            if pending is not None:
                out.append(pending)
                pending = None
                pending_page = None
            out.append(c)
            continue

        content_len = len((c.page_content or "").strip())

        if pending is not None:
            merged = _merge_two(pending, c, page_index=page_index) if page_index is not None else None
            if merged is not None:
                out.append(merged)
            else:
                out.append(pending)
                out.append(c)
            pending = None
            pending_page = None
            continue

        if content_len >= min_chars:
            out.append(c)
            continue

        if out:
            prev = out[-1]
            prev_page = _page_index_of(prev)
            prev_meta = dict(getattr(prev, "metadata", None) or {})
            if (
                prev_page == page_index
                and not _preview_chunk_has_asset(prev_meta, prev.page_content or "")
                and not (prev_meta.get("chunk_role") or prev_meta.get("parent_id"))
                and _local_range(prev_meta) is not None
            ):
                merged = _merge_two(prev, c, page_index=page_index) if page_index is not None else None
                if merged is not None:
                    out[-1] = merged
                    continue

        pending = c
        pending_page = page_index

    if pending is not None:
        out.append(pending)

    return out


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant id") from exc

async def _resolve_account_id_for_asset_request(request: Request, *, tenant_id: UUID | None = None) -> str | None:
    """
    Resolve account id for asset endpoints that may be requested by <img src>.

    - AUTH_MODE=header: allow anonymous in local/dev (headers can't be set by <img>).
    - AUTH_MODE=jwt: require either Authorization header or ?token= query param.
    """
    is_production = is_production_env()
    auth_mode = (getattr(settings, "AUTH_MODE", "jwt") or "jwt").lower()

    if auth_mode == "header":
        account_id = (request.headers.get("x-user-id") or "").strip() or None
        if is_production and not account_id:
            raise HTTPException(status_code=401, detail="X-User-ID header required")
        return account_id

    # jwt mode: allow either Authorization header or `?token=` query param for <img src>.
    authorization = (request.headers.get("authorization") or "").strip()
    token = (request.query_params.get("token") or request.query_params.get("access_token") or "").strip()
    if not authorization and token:
        authorization = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")

    tenant_value = str(tenant_id).strip() if tenant_id is not None else None
    try:
        return await get_current_account_id_from_headers(
            authorization=authorization,
            x_user_id=None,
            x_tenant_id=tenant_value,
        )
    except HTTPException:
        raise HTTPException(status_code=401, detail="Authentication required") from None


def _get_tenant_id_from_request_if_provided(request: Request) -> UUID | None:
    """
    Return tenant id from header/query if explicitly provided; otherwise None.

    This is used for endpoints like `<img src>` where custom headers are not sent.
    """
    tenant_header = str(getattr(settings, "TENANT_HEADER", "") or "X-Tenant-ID").strip() or "X-Tenant-ID"
    raw = (request.headers.get(tenant_header) or "").strip()
    if not raw and tenant_header.lower() != "x-tenant-id":
        raw = (request.headers.get("x-tenant-id") or "").strip()
    if raw:
        return _parse_uuid(raw)

    for key in ("tenant_id", "x_tenant_id", "tenant"):
        raw = (request.query_params.get(key) or "").strip()
        if raw:
            return _parse_uuid(raw)

    return None


def _resolve_tenant_id_for_asset_request(request: Request) -> UUID:
    """
    Resolve tenant id for asset endpoints.

    Priority:
    1) TENANT_HEADER (default: X-Tenant-ID)
    2) ?tenant_id=... query param (or aliases)
    3) settings.DEFAULT_TENANT_ID in non-production
    """
    provided = _get_tenant_id_from_request_if_provided(request)
    if provided is not None:
        return provided

    if is_production_env():
        tenant_header = str(getattr(settings, "TENANT_HEADER", "") or "X-Tenant-ID").strip() or "X-Tenant-ID"
        raise HTTPException(status_code=400, detail=f"{tenant_header} header or tenant_id query param required")
    return _parse_uuid(str(settings.DEFAULT_TENANT_ID))

def _materialize_extracted_images_for_preview(documents: list, *, tenant_id: UUID) -> list:
    """
    Convert in-memory image objects (e.g., DeepDoc PIL.Image in metadata["image"])
    into preview-time Markdown refs that the frontend can render.

    Why:
    - FastAPI cannot JSON-serialize PIL.Image objects in segment metadata.
    - DeepDoc returns images as separate "image" Documents via metadata["image"].

    Strategy:
    - For doc_type_kwd == "image", save the image to uploads/{tenant}/images/{uuid}.jpg
      and replace the segment content with a Markdown image link.
    - Always remove non-serializable "image" objects from metadata.

    Note:
    - We intentionally do NOT set metadata["img_id"] here, because manual ingestion
      uses `metadata.setdefault("img_id", ...)` after rewriting preview images to MinIO.
    """
    if not documents:
        return []

    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    from io import BytesIO

    try:
        from PIL import Image as PILImage  # type: ignore
    except ImportError:
        logger.warning("Pillow not available; dropping preview image objects (hint: pip install Pillow)")
        # If pillow is unavailable, just drop the image objects to avoid 500s.
        for doc in documents:
            meta = getattr(doc, "metadata", None) or {}
            if isinstance(meta, dict) and "image" in meta:
                meta.pop("image", None)
                doc.metadata = meta
        return documents

    for doc in documents:
        meta = getattr(doc, "metadata", None) or {}
        if not isinstance(meta, dict):
            continue

        image_obj = meta.get("image")
        if image_obj is None:
            continue

        doc_type = str(meta.get("doc_type_kwd") or "").lower()
        if doc_type != "image":
            meta.pop("image", None)
            doc.metadata = meta
            continue

        preview_id = uuid.uuid4().hex
        out_path = images_dir / f"{preview_id}.jpg"
        url = f"/api/v1/documents/image/{preview_id}"

        try:
            img = (
                PILImage.open(BytesIO(bytes(image_obj)))
                if isinstance(image_obj, (bytes, bytearray))
                else image_obj
            )
            with contextlib.suppress(Exception):
                if getattr(img, "mode", None) != "RGB":
                    img = img.convert("RGB")

            img.save(out_path, format="JPEG", quality=85, optimize=True)
        except Exception as e:
            logger.warning("Failed to persist preview image: %s", str(e)[:200])
        finally:
            # Always remove the raw image object from metadata to keep JSON-serializable.
            meta.pop("image", None)
            doc.metadata = meta
            if not isinstance(image_obj, (bytes, bytearray)) and hasattr(image_obj, "close"):
                with contextlib.suppress(Exception):
                    image_obj.close()

        # Update content with an image reference.
        caption = (getattr(doc, "page_content", "") or "").strip()
        img_md = f"![image]({url})"
        doc.page_content = f"{img_md}\n\n{caption}" if caption else img_md

        # Optional, non-conflicting preview metadata.
        meta["preview_image_id"] = preview_id
        meta["preview_image_url"] = url
        doc.metadata = meta

    return documents


def _materialize_local_images_for_preview(documents: list, *, tenant_id: UUID) -> list:
    """
    Rewrite local/relative image references in Markdown/HTML into preview-time
    `/api/v1/documents/image/{uuid}` URLs.

    This is mainly for parsers like MagicPDF that output markdown such as:
    - ![](images/xxx.png)
    - <img src="images/xxx.png">

    The referenced files live under metadata["asset_base_dir"]. We copy them into:
    - uploads/{tenant_id}/images/{uuid}.(png|jpg|...)

    so the frontend can load them via the existing `GET /api/v1/documents/image/{image_id}` API.
    """
    if not documents:
        return []

    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # Only process Markdown images and HTML img tags, matching src content.
    md_pat = re.compile(
        r"!\[[^\]]*\]\(\s*(?:<)?([^)\s>]+)(?:>)?(?:\s+['\"][^'\"]*['\"])?\s*\)",
        flags=re.IGNORECASE,
    )
    html_pat = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", flags=re.IGNORECASE)

    max_inline_images = max(0, int(getattr(settings, "MAX_INLINE_IMAGES", 0) or 0))
    max_image_bytes = int(getattr(settings, "MAX_INLINE_IMAGE_BYTES", 10_000_000) or 10_000_000)
    max_image_bytes = max(1_000_000, max_image_bytes)

    supported_exts = {".png", ".jpg", IMAGE_FILE_EXT_JPEG, IMAGE_FILE_EXT_WEBP, ".gif", ".bmp"}

    digest_cache: dict[str, tuple[str, str]] = {}
    from io import BytesIO

    try:
        from PIL import Image as pil_image  # type: ignore
    except ImportError:
        pil_image = None  # type: ignore[assignment]
        pillow_ok = False
    else:
        pillow_ok = True

    from urllib.parse import unquote, urlparse

    for doc in documents:
        content = getattr(doc, "page_content", "") or ""
        if not isinstance(content, str) or not content:
            continue

        lowered = content.lower()
        if "![" not in lowered and "<img" not in lowered:
            continue

        meta = getattr(doc, "metadata", None) or {}
        if not isinstance(meta, dict):
            continue
        base_dir_raw = meta.get("asset_base_dir")
        if not isinstance(base_dir_raw, str) or not base_dir_raw.strip():
            continue

        base_dir = Path(base_dir_raw.strip()).resolve(strict=False)
        if not base_dir.exists() or not base_dir.is_dir():
            continue
        base_dir_resolved = base_dir.resolve(strict=False)

        found: list[str] = []
        seen: set[str] = set()
        for pat in (md_pat, html_pat):
            for m in pat.finditer(content):
                ref = (m.group(1) or "").strip()
                if not ref or ref in seen:
                    continue
                seen.add(ref)
                found.append(ref)

        if not found:
            continue
        if max_inline_images and len(found) > max_inline_images:
            found = found[:max_inline_images]

        replacements: dict[str, str] = {}

        for ref in found:
            ref_stripped = ref.strip()
            if not ref_stripped:
                continue

            # Skip remote/already rewired refs.
            ref_lower = ref_stripped.lower()
            parsed_ref = urlparse(ref_stripped)
            scheme = (parsed_ref.scheme or "").lower().strip()
            if scheme in {"http", "https", "data", "blob"} or (parsed_ref.netloc or "").strip():
                continue
            if "/api/v1/documents/image-url/" in ref_lower or "/api/v1/documents/image/" in ref_lower:
                continue

            # Strip query/fragment and URL-decode (for files like "foo%20bar.png").
            ref_path = ref_stripped.split("?", 1)[0].split("#", 1)[0].strip()
            if not ref_path:
                continue
            try:
                ref_path_decoded = unquote(ref_path)
            except Exception:
                ref_path_decoded = ref_path

            candidate_rel = []
            if ref_path_decoded.startswith("/") and not ref_path_decoded.startswith("/api/"):
                candidate_rel.append(ref_path_decoded.lstrip("/"))
            candidate_rel.append(ref_path_decoded)

            resolved_path: Path | None = None
            for candidate in candidate_rel:
                if not candidate:
                    continue
                try:
                    path_obj = Path(candidate)
                    if not path_obj.is_absolute():
                        path_obj = (base_dir_resolved / path_obj).resolve(strict=False)
                    else:
                        path_obj = path_obj.resolve(strict=False)

                    try:
                        path_obj.relative_to(base_dir_resolved)
                    except Exception:
                        continue

                    if path_obj.exists() and path_obj.is_file():
                        resolved_path = path_obj
                        break
                except Exception:
                    continue

            if resolved_path is None:
                continue

            try:
                if resolved_path.stat().st_size > max_image_bytes:
                    continue
            except Exception:
                continue

            ext = resolved_path.suffix.lower()
            try:
                raw_bytes = resolved_path.read_bytes()
            except Exception:
                continue
            if not raw_bytes or len(raw_bytes) > max_image_bytes:
                continue

            out_ext = ext if ext in supported_exts else ".jpg"
            image_bytes = raw_bytes

            if out_ext == ".jpg" and ext not in supported_exts:
                if not pillow_ok:
                    continue
                try:
                    img = pil_image.open(BytesIO(raw_bytes))  # type: ignore[arg-type]
                    if getattr(img, "mode", None) != "RGB":
                        img = img.convert("RGB")
                    out = BytesIO()  # type: ignore[call-arg]
                    img.save(out, format="JPEG", quality=85, optimize=True)
                    image_bytes = out.getvalue()
                except Exception as e:
                    logger.warning("Failed converting preview local image to JPEG: %s", str(e)[:200])
                    continue

            digest = hashlib.sha256(image_bytes).hexdigest()
            cached = digest_cache.get(digest)
            if cached:
                preview_id, cached_ext = cached
                out_ext = cached_ext
            else:
                preview_id = uuid.uuid4().hex
                out_path = images_dir / f"{preview_id}{out_ext}"
                try:
                    out_path.write_bytes(image_bytes)
                except Exception as e:
                    logger.warning("Failed to persist preview local image: %s", str(e)[:200])
                    continue
                digest_cache[digest] = (preview_id, out_ext)

            url = f"/api/v1/documents/image/{preview_id}"
            replacements[ref] = url

        if not replacements:
            continue

        def _md_repl(m: re.Match, replacements=replacements) -> str:
            raw = m.group(1) or ""
            key = raw.strip()
            new = replacements.get(key)
            if not new:
                return m.group(0)
            return m.group(0).replace(raw, new, 1)

        def _html_repl(m: re.Match, replacements=replacements) -> str:
            raw = m.group(1) or ""
            key = raw.strip()
            new = replacements.get(key)
            if not new:
                return m.group(0)
            return m.group(0).replace(raw, new, 1)

        content = md_pat.sub(_md_repl, content)
        content = html_pat.sub(_html_repl, content)
        doc.page_content = content

    return documents


def _compute_pipeline_hash(doc_metadata: dict) -> str:
    """
    Generate a stable pipeline_hash based on processing-related doc_metadata fields.
    Use cases: task idempotency, lock keys, job_id dedupe (configs do not block each other).
    """
    relevant = {
        # Parser/chunk strategy.
        "parser_backend": doc_metadata.get("parser_backend"),
        "parser_backend_requested": doc_metadata.get("parser_backend_requested"),
        "chunk_strategy": doc_metadata.get("chunk_strategy"),
        "chunk_strategy_requested": doc_metadata.get("chunk_strategy_requested"),
        # Pipeline options (stable structure).
        "pipeline": doc_metadata.get("pipeline") or {},
    }
    raw = json.dumps(relevant, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _find_duplicate_document(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    file_sha256: str | None,
    pipeline_hash: str | None,
) -> DBDocument | None:
    """
    Find an existing document with the same (file_sha256 + pipeline_hash) within a dataset.

    This is used as an optional ingestion optimization to avoid re-embedding identical inputs
    under identical pipeline options.
    """
    if dataset_id is None:
        return None

    sha = str(file_sha256 or "").strip().lower()
    ph = str(pipeline_hash or "").strip()
    if not sha or not ph:
        return None

    # Postgres JSONB fast path.
    try:
        return (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.doc_metadata["file_sha256"].astext == sha,  # type: ignore[attr-defined]
                DBDocument.doc_metadata["pipeline_hash"].astext == ph,  # type: ignore[attr-defined]
            )
            .order_by(DBDocument.created_at.desc())
            .first()
        )
    except Exception:
        # Best-effort fallback for non-Postgres backends: scan a bounded window.
        rows = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
            )
            .order_by(DBDocument.created_at.desc())
            .limit(2000)
            .all()
        )
        for doc in rows:
            meta = doc.doc_metadata if isinstance(doc.doc_metadata, dict) else {}
            sha0 = str(meta.get("file_sha256") or "").strip().lower()
            ph0 = str(meta.get("pipeline_hash") or "").strip()
            if sha0 == sha and ph0 == ph:
                return doc
        return None


def _find_duplicate_document_by_sha(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    file_sha256: str | None,
) -> DBDocument | None:
    """
    Find an existing document with the same file_sha256 within a dataset (any pipeline_hash).

    Used for "cross-version" upload dedup: when the same file is uploaded again with different
    pipeline options, we can reuse the existing document_id and create a new pipeline version.
    """
    if dataset_id is None:
        return None

    sha = str(file_sha256 or "").strip().lower()
    if not sha:
        return None

    try:
        return (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.doc_metadata["file_sha256"].astext == sha,  # type: ignore[attr-defined]
            )
            .order_by(DBDocument.created_at.desc())
            .first()
        )
    except Exception:
        # Best-effort fallback for non-Postgres backends: scan a bounded window.
        rows = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
            )
            .order_by(DBDocument.created_at.desc())
            .limit(2000)
            .all()
        )
        for doc in rows:
            meta = doc.doc_metadata if isinstance(doc.doc_metadata, dict) else {}
            sha0 = str(meta.get("file_sha256") or "").strip().lower()
            if sha0 == sha:
                return doc
        return None


def _apply_user_metadata_patch(*, current: dict, patch: dict, replace: bool) -> dict:
    if replace:
        next_user = dict(patch or {})
    else:
        next_user = dict(current or {})
        for key, value in (patch or {}).items():
            if value is None:
                next_user.pop(key, None)
            else:
                next_user[key] = value

    # Best-effort normalization for common fields.
    tags = next_user.get("tags")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    if isinstance(tags, list):
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in tags:
            if not isinstance(raw, str):
                continue
            val = raw.strip()
            if not val:
                continue
            key = val.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(val[:64])
        next_user["tags"] = cleaned[:50]
    elif tags is None and "tags" in next_user and not replace:
        next_user.pop("tags", None)

    notes = next_user.get("notes")
    if isinstance(notes, str):
        val = notes.strip()
        if not val:
            next_user.pop("notes", None)
        else:
            next_user["notes"] = val[:20_000]

    return next_user


_WINDOWS_DRIVE_LETTER_RE = re.compile(r"^[a-zA-Z]:$")
_UPLOAD_SOURCE_PATH_MAX_LEN = 500


def _normalize_upload_path_parts(filename: str) -> list[str]:
    """
    Best-effort normalization for uploaded file "filename" which may include a relative path.

    This is used ONLY for metadata correlation/display (not filesystem writes).

    We intentionally do NOT preserve absolute paths or path traversal semantics.
    """
    raw = str(filename or "")
    if not raw:
        return []
    if "\x7f" in raw or any(ord(ch) < 32 for ch in raw):
        # Match `_sanitize_filename` behavior: reject control characters (header safety).
        raise HTTPException(status_code=400, detail=FILENAME_INVALID_CHARS_DETAIL)

    cleaned = raw.replace("\\", "/").strip()
    if not cleaned:
        return []

    parts = [p.strip() for p in cleaned.split("/") if p.strip() and p.strip() != "."]
    if parts and _WINDOWS_DRIVE_LETTER_RE.fullmatch(parts[0]):
        parts = parts[1:]
    if not parts:
        return []

    # Collapse ".." with stack semantics (defensive; folder uploads should never send "..").
    stack: list[str] = []
    for p in parts:
        if p == "..":
            if stack:
                stack.pop()
            continue
        stack.append(p)

    # Drop browser "fakepath" (e.g. C:\fakepath\a.pdf) which is not real structure.
    if len(stack) == 2 and stack[0].lower() == "fakepath":
        stack = [stack[1]]

    return stack


def _normalize_upload_key(filename: str) -> str:
    """
    Normalize an upload correlation key:
    - Prefer directory-preserving relative paths when available.
    - Falls back to sanitized basename.
    """
    parts = _normalize_upload_path_parts(filename)
    if not parts:
        return _sanitize_filename(filename)
    key = "/".join(parts)
    if len(key) > _UPLOAD_SOURCE_PATH_MAX_LEN:
        key = key[:_UPLOAD_SOURCE_PATH_MAX_LEN]
    return key


def _normalize_upload_source_path(filename: str) -> str | None:
    """
    Return a normalized relative source path if a directory was provided, else None.

    Examples:
    - "a.pdf" -> None
    - "Docs/sub/a.pdf" -> "Docs/sub/a.pdf"
    - "C:\\fakepath\\a.pdf" -> None
    """
    key = _normalize_upload_key(filename)
    if "/" not in key:
        return None
    # Heuristic: ignore "fakepath" style uploads (after normalization it would not contain "/").
    return key


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

    # Strip any path components some clients include (e.g., Windows fakepath).
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
    """
    Parse JSON-encoded pipeline options from multipart/form-data.

    Frontend uploads use `FormData`, so we accept pipeline config as a JSON string.
    """
    raw = (pipeline or "").strip()
    if not raw or raw.lower() in {"null", "none", "undefined"}:
        return None
    max_len = int(getattr(settings, "PIPELINE_FORM_JSON_MAX_CHARS", 200_000) or 200_000)
    if max_len > 0 and len(raw) > max_len:
        raise HTTPException(status_code=400, detail="pipeline is too large")
    try:
        return DocumentPipelineOptions.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        msg = (str(exc) or exc.__class__.__name__)[:200]
        detail = "Invalid pipeline JSON" if is_production_env() else f"Invalid pipeline JSON: {msg}"
        raise HTTPException(status_code=400, detail=detail) from exc


def _compute_chunk_coverage_metrics(
    chunk_items: list[ChunkPreviewItem], *, total_characters: int
) -> dict[str, float | int]:
    """
    Compute coverage/overlap signals from chunk start/end indices.

    - covered_chars: union length of all chunk ranges (clipped to [0, total_characters])
    - gap_count / largest_gap: uncovered segments within [0, total_characters]
    - overlap_waste_ratio: duplicated chars ratio due to overlap (0-1)
    """
    total = int(total_characters or 0)
    if total <= 0 or not chunk_items:
        return {
            "sum_chunk_chars": 0,
            "covered_chars": 0,
            "coverage_ratio": 0.0,
            "overlap_waste_ratio": 0.0,
            "gap_count": 0,
            "largest_gap": 0,
        }

    sum_chunk_chars = 0
    ranges: list[tuple[int, int]] = []
    for c in chunk_items:
        try:
            s = int(c.start_index)
            e = int(c.end_index)
        except Exception:
            continue
        if e <= s:
            continue
        # Clip to document range.
        s2 = max(0, min(total, s))
        e2 = max(0, min(total, e))
        if e2 <= s2:
            continue
        ranges.append((s2, e2))
        sum_chunk_chars += max(0, e2 - s2)

    if not ranges:
        return {
            "sum_chunk_chars": 0,
            "covered_chars": 0,
            "coverage_ratio": 0.0,
            "overlap_waste_ratio": 0.0,
            "gap_count": 0,
            "largest_gap": total,
        }

    ranges.sort(key=lambda x: (x[0], x[1]))
    covered = 0
    gap_count = 0
    largest_gap = 0

    cur_s, cur_e = ranges[0]
    if cur_s > 0:
        gap_count += 1
        largest_gap = max(largest_gap, cur_s)

    for s, e in ranges[1:]:
        if s > cur_e:
            covered += cur_e - cur_s
            gap = s - cur_e
            gap_count += 1
            largest_gap = max(largest_gap, gap)
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)

    covered += cur_e - cur_s
    if cur_e < total:
        gap_count += 1
        largest_gap = max(largest_gap, total - cur_e)

    sum_chars = int(sum_chunk_chars)
    covered_chars = int(max(0, covered))
    coverage_ratio = float(covered_chars / total) if total > 0 else 0.0
    overlap_waste_ratio = float(max(0, sum_chars - covered_chars) / sum_chars) if sum_chars > 0 else 0.0

    return {
        "sum_chunk_chars": sum_chars,
        "covered_chars": covered_chars,
        "coverage_ratio": coverage_ratio,
        "overlap_waste_ratio": overlap_waste_ratio,
        "gap_count": int(gap_count),
        "largest_gap": int(largest_gap),
    }


def _compute_chunk_coverage_metrics_from_ranges(
    ranges: list[tuple[int, int]], *, total_characters: int
) -> dict[str, float | int]:
    """
    Compute coverage/overlap signals from chunk start/end ranges.

    Same semantics as `_compute_chunk_coverage_metrics`, but avoids requiring `ChunkPreviewItem`
    objects when callers only need lightweight stats (e.g. auto-tune).
    """
    total = int(total_characters or 0)
    if total <= 0 or not ranges:
        return {
            "sum_chunk_chars": 0,
            "covered_chars": 0,
            "coverage_ratio": 0.0,
            "overlap_waste_ratio": 0.0,
            "gap_count": 0,
            "largest_gap": 0,
        }

    sum_chunk_chars = 0
    clipped: list[tuple[int, int]] = []
    for s, e in ranges:
        try:
            s0 = int(s)
            e0 = int(e)
        except Exception:
            continue
        if e0 <= s0:
            continue
        # Clip to document range.
        s2 = max(0, min(total, s0))
        e2 = max(0, min(total, e0))
        if e2 <= s2:
            continue
        clipped.append((s2, e2))
        sum_chunk_chars += max(0, e2 - s2)

    if not clipped:
        return {
            "sum_chunk_chars": 0,
            "covered_chars": 0,
            "coverage_ratio": 0.0,
            "overlap_waste_ratio": 0.0,
            "gap_count": 0,
            "largest_gap": total,
        }

    clipped.sort(key=lambda x: (x[0], x[1]))
    covered = 0
    gap_count = 0
    largest_gap = 0

    cur_s, cur_e = clipped[0]
    if cur_s > 0:
        gap_count += 1
        largest_gap = max(largest_gap, cur_s)

    for s, e in clipped[1:]:
        if s > cur_e:
            covered += cur_e - cur_s
            gap = s - cur_e
            gap_count += 1
            largest_gap = max(largest_gap, gap)
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)

    covered += cur_e - cur_s
    if cur_e < total:
        gap_count += 1
        largest_gap = max(largest_gap, total - cur_e)

    sum_chars = int(sum_chunk_chars)
    covered_chars = int(max(0, covered))
    coverage_ratio = float(covered_chars / total) if total > 0 else 0.0
    overlap_waste_ratio = float(max(0, sum_chars - covered_chars) / sum_chars) if sum_chars > 0 else 0.0

    return {
        "sum_chunk_chars": sum_chars,
        "covered_chars": covered_chars,
        "coverage_ratio": coverage_ratio,
        "overlap_waste_ratio": overlap_waste_ratio,
        "gap_count": int(gap_count),
        "largest_gap": int(largest_gap),
    }


def _compute_chunk_length_histogram(
    lengths: list[int],
    *,
    unit: Literal["chars", "tokens"],
    target_bins: int = 8,
) -> list[dict[str, object]]:
    """
    Compute a coarse histogram for chunk length distribution.

    Returned bins use the schema:
      {label: "min-max", min: int, max: int, count: int}

    Notes:
    - Bin bounds are best-effort; the UI should treat them as descriptive, not strict.
    - We keep bin widths "round" to keep charts readable.
    """
    values: list[int] = []
    for x in (lengths or []):
        try:
            n = int(x)
        except Exception:
            continue
        values.append(max(0, n))
    if not values:
        return []

    max_val = max(values)
    bins = max(3, min(12, int(target_bins or 8)))
    base = 25 if unit == "tokens" else 50

    # Choose a rounded step size so we end up with ~bins buckets.
    if max_val <= 0:
        step = base
    else:
        step = int(math.ceil((max_val / bins) / base) * base)
        step = max(base, step) if step > 0 else base

    bin_count = max(1, int(math.ceil((max_val + 1) / step))) if step > 0 else 1
    out: list[dict[str, object]] = []
    for i in range(bin_count):
        lo = int(i * step)
        hi = int((i + 1) * step)
        out.append({"label": f"{lo}-{hi}", "min": lo, "max": hi, "count": 0})

    for v in values:
        idx = int(v // step) if step > 0 else 0
        if idx < 0:
            idx = 0
        if idx >= len(out):
            idx = len(out) - 1
        out[idx]["count"] = int(out[idx].get("count") or 0) + 1
    return out


def _compute_chunk_preview_review_signals(
    *,
    chunk_items: list[ChunkPreviewItem],
    unit: Literal["chars", "tokens"],
    strategy: str,
) -> ChunkPreviewReviewSignals:
    """
    Optional per-chunk review signals (best-effort) for enterprise tuning/auditing.

    Designed to be close to frontend's review-signals.ts so results are explainable.
    """
    basis: Literal["all", "child"] = "all"
    strict_no_overlap = str(strategy or "") == "separator"

    # Coverage basis: for parent_child, analyze child chunks when available.
    analysis = list(chunk_items or [])
    if str(strategy or "") == "parent_child":
        filtered: list[ChunkPreviewItem] = []
        for c in analysis:
            meta = getattr(c, "metadata", None) or {}
            role = meta.get("chunk_role") if isinstance(meta, dict) else None
            if role != "parent":
                filtered.append(c)
        if filtered:
            analysis = filtered
            basis = "child"

    # Gaps / overlaps from start/end indices.
    gap_indices: set[int] = set()
    overlap_indices: set[int] = set()
    gap_before_by_index: dict[int, int] = {}
    overlap_prev_by_index: dict[int, int] = {}

    def _key(c: ChunkPreviewItem) -> tuple[int, int, int]:
        try:
            s = int(getattr(c, "start_index", 0) or 0)
        except Exception:
            s = 0
        try:
            e = int(getattr(c, "end_index", s) or s)
        except Exception:
            e = s
        try:
            i = int(getattr(c, "index", 0) or 0)
        except Exception:
            i = 0
        return (s, e, i)

    sorted_items = sorted(analysis, key=_key)
    covered_end = 0
    for c in sorted_items:
        try:
            idx = int(c.index)
        except Exception:
            continue
        try:
            start = int(getattr(c, "start_index", 0) or 0)
        except Exception:
            start = 0
        try:
            end = int(getattr(c, "end_index", start) or start)
        except Exception:
            end = start

        start = max(0, start)
        end = max(start, end)

        if start > covered_end:
            gap = start - covered_end
            if gap > 0:
                gap_indices.add(idx)
                gap_before_by_index[idx] = int(gap)
        elif start < covered_end:
            overlap = covered_end - start
            chunk_len = max(1, end - start)
            if overlap > 0:
                overlap_prev_by_index[idx] = int(overlap)
            is_high = overlap > 0 and (strict_no_overlap or (overlap / chunk_len) >= 0.6 or overlap >= 800)
            if is_high:
                overlap_indices.add(idx)

        if end > covered_end:
            covered_end = end

    # Short chunks.
    short_indices: set[int] = set()
    threshold = 40 if unit == "tokens" else 120
    for c in chunk_items or []:
        try:
            idx = int(c.index)
        except Exception:
            continue
        if unit == "tokens":
            val = getattr(c, "tokens_est", None)
            try:
                n = int(val) if val is not None else 0
            except Exception:
                n = 0
        else:
            try:
                n = int(getattr(c, "length", 0) or 0)
            except Exception:
                n = 0
        if n > 0 and n < threshold:
            short_indices.add(idx)

    # Duplicates (content hash).
    duplicate_indices: set[int] = set()
    seen: dict[str, int] = {}
    for c in chunk_items or []:
        try:
            idx = int(c.index)
        except Exception:
            continue
        trimmed = str(getattr(c, "content", "") or "").strip()
        if not trimmed:
            continue
        digest = hashlib.blake2b(trimmed.encode("utf-8"), digest_size=16).hexdigest()
        prev = seen.get(digest)
        if prev is not None:
            duplicate_indices.add(prev)
            duplicate_indices.add(idx)
        else:
            seen[digest] = idx

    return ChunkPreviewReviewSignals(
        basis=basis,
        short_indices=sorted(short_indices),
        duplicate_indices=sorted(duplicate_indices),
        gap_indices=sorted(gap_indices),
        overlap_indices=sorted(overlap_indices),
        gap_before_by_index=gap_before_by_index,
        overlap_prev_by_index=overlap_prev_by_index,
    )


def _compute_chunk_preview_quality(
    *,
    stats: ChunkPreviewStats,
    total_chunks: int,
    total_characters: int,
    chunk_size: int,
    chunk_overlap: int,
    original_text_included: bool,
    original_text_truncated: bool,
    original_text_max_chars: int,
) -> tuple[ChunkPreviewQualityGate, list[str], list[ChunkPreviewRecommendationPatch]]:
    """
    Enterprise-friendly quality gate (heuristics; best-effort).

    Goal: surface actionable signals when tuning chunking.
    """
    from app.services.chunk_quality_gate import compute_chunk_quality_gate

    stats_dict = {
        "count": int(getattr(stats, "count", 0) or 0),
        "short_count": int(getattr(stats, "short_count", 0) or 0),
        "duplicate_count": int(getattr(stats, "duplicate_count", 0) or 0),
        "covered_chars": int(getattr(stats, "covered_chars", 0) or 0),
        "coverage_ratio": float(getattr(stats, "coverage_ratio", 0.0) or 0.0),
        "overlap_waste_ratio": float(getattr(stats, "overlap_waste_ratio", 0.0) or 0.0),
        "gap_count": int(getattr(stats, "gap_count", 0) or 0),
    }

    gate_raw, recs, patches_raw = compute_chunk_quality_gate(
        stats=stats_dict,
        total_chunks=int(total_chunks or 0),
        total_characters=int(total_characters or 0),
        chunk_size=int(chunk_size or 0),
        chunk_overlap=int(chunk_overlap or 0),
        original_text_included=bool(original_text_included),
        original_text_truncated=bool(original_text_truncated),
        original_text_max_chars=int(original_text_max_chars or 0),
    )

    # Convert raw dict payloads into response models (best-effort).
    reason_items: list[ChunkPreviewQualityReason] = []
    for r in (gate_raw.get("reason_items") if isinstance(gate_raw, dict) else []) or []:
        if not isinstance(r, dict):
            continue
        try:
            reason_items.append(
                ChunkPreviewQualityReason(
                    code=str(r.get("code") or "")[:80],
                    severity=str(r.get("severity") or "info"),  # type: ignore[arg-type]
                    message=str(r.get("message") or "")[:200],
                    meta=dict(r.get("meta") or {}),
                )
            )
        except Exception:
            continue

    patches: list[ChunkPreviewRecommendationPatch] = []
    for p in (patches_raw or []):
        if not isinstance(p, dict):
            continue
        try:
            patches.append(
                ChunkPreviewRecommendationPatch(
                    id=str(p.get("id") or "")[:80],
                    title=str(p.get("title") or "")[:120],
                    description=str(p.get("description") or "")[:400],
                    target=str(p.get("target") or "preview"),  # type: ignore[arg-type]
                    patch=dict(p.get("patch") or {}),
                )
            )
        except Exception:
            continue

    grade = str(gate_raw.get("grade") if isinstance(gate_raw, dict) else "pass") or "pass"
    reasons = gate_raw.get("reasons") if isinstance(gate_raw, dict) else []
    legacy_reasons = [str(x) for x in reasons] if isinstance(reasons, list) else []

    return (
        ChunkPreviewQualityGate(grade=grade, reasons=legacy_reasons[:10], reason_items=reason_items[:10]),
        list(recs or [])[:10],
        patches[:10],
    )


def _to_pipeline_options(
    *,
    pipeline: DocumentPipelineOptions | None = None,
    overrides: "PipelineOptionOverrides | None" = None,
    **legacy_overrides: Any,
) -> PipelineOptions:
    resolved_overrides = _resolve_pipeline_option_overrides(overrides=overrides, legacy_overrides=legacy_overrides)
    overrides_dict = {k: v for k, v in asdict(resolved_overrides).items() if v is not None}

    if pipeline is None:
        pipeline = DocumentPipelineOptions(**overrides_dict) if overrides_dict else None
    elif overrides_dict:
        # Explicit form fields override JSON pipeline (backward compatible).
        try:
            merged = pipeline.model_dump()
            merged.update(overrides_dict)
            pipeline = DocumentPipelineOptions(**merged)
        except Exception as exc:  # noqa: BLE001
            msg = (str(exc) or exc.__class__.__name__)[:200]
            detail = "Invalid pipeline options" if is_production_env() else f"Invalid pipeline options: {msg}"
            raise HTTPException(status_code=400, detail=detail) from exc

    if pipeline is None:
        return PipelineOptions()

    data = pipeline.model_dump(exclude_none=True)
    return PipelineOptions(**data) if data else PipelineOptions()


@dataclass(frozen=True)
class PipelineOptionOverrides:
    governance_enabled: bool | None = None
    governance_remove_toc_lines: bool | None = None
    governance_remove_noise_lines: bool | None = None
    governance_unwrap_lines: bool | None = None
    governance_remove_common_lines: bool | None = None
    governance_unwrap_max_line_length: int | None = None
    governance_noise_min_chars: int | None = None
    governance_noise_ratio_threshold: float | None = None
    governance_common_lines_min_docs: int | None = None
    governance_common_lines_min_ratio: float | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    chunk_vector_enabled: bool | None = None
    bm25_index_enabled: bool | None = None
    kg_enabled: bool | None = None
    event_vector_enabled: bool | None = None
    entity_vector_enabled: bool | None = None


def _resolve_pipeline_option_overrides(
    *,
    overrides: PipelineOptionOverrides | None,
    legacy_overrides: dict[str, Any],
) -> PipelineOptionOverrides:
    base = overrides or PipelineOptionOverrides()
    if not legacy_overrides:
        return base
    return cast(PipelineOptionOverrides, replace(base, **legacy_overrides))


def _validate_chunk_params(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_overlap >= chunk_size:
        raise HTTPException(
            status_code=400,
            detail=CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL,
        )


def _rewrite_preview_images_to_minio(
    text: str,
    *,
    tenant_id: str,
    dataset_id: str,
    document_id: str,
    images_dir: Path,
    local_id_to_img_id: dict[str, str],
    digest_to_img_id: dict[str, str],
    start_index: int = 0,
) -> tuple[str, list[str], int]:
    """
    Convert preview-time local image refs (/api/v1/documents/image/{uuid}) into
    persisted MinIO refs (/api/v1/documents/image-url/{img_id}) and upload images.

    Returns:
    - rewritten text
    - ordered list of img_id values referenced by this text (unique)
    - next asset index
    """
    if not settings.MINIO_ENABLED:
        return text, [], start_index
    if not isinstance(text, str) or not text:
        return text, [], start_index

    # Already MinIO-backed.
    existing: list[str] = []
    for m in MINIO_IMAGE_REF_RE.finditer(text):
        val = (m.group(1) or "").strip()
        if val and val not in existing:
            existing.append(val)
    if existing:
        return text, existing, start_index

    if "/api/v1/documents/image/" not in text:
        return text, [], start_index

    matches = list(PREVIEW_IMAGE_REF_RE.finditer(text))
    if not matches:
        return text, [], start_index

    max_inline_images = max(0, int(getattr(settings, "MAX_INLINE_IMAGES", 0) or 0))
    if max_inline_images and len(matches) > max_inline_images:
        matches = matches[:max_inline_images]

    image_exts = [".png", ".jpg", IMAGE_FILE_EXT_JPEG, IMAGE_FILE_EXT_WEBP, ".gif", ".bmp"]
    max_bytes = int(getattr(settings, "MAX_INLINE_IMAGE_BYTES", 10_000_000) or 10_000_000)
    max_bytes = max(1_000_000, max_bytes)

    referenced_img_ids: list[str] = []
    seen_local_ids: set[str] = set()

    for m in matches:
        raw_id = m.group(1)
        if not raw_id:
            continue
        try:
            local_id = uuid.UUID(raw_id).hex
        except ValueError:
            continue

        if local_id in seen_local_ids:
            continue
        seen_local_ids.add(local_id)

        img_id = local_id_to_img_id.get(local_id)
        if not img_id:
            # Find local file.
            img_path: Path | None = None
            for ext in image_exts:
                candidate = images_dir / f"{local_id}{ext}"
                if candidate.exists() and candidate.is_file():
                    img_path = candidate
                    break
            if img_path is None:
                try:
                    for candidate in images_dir.glob(f"{local_id}.*"):
                        if candidate.suffix.lower() in image_exts and candidate.exists() and candidate.is_file():
                            img_path = candidate
                            break
                except OSError:
                    img_path = None

            if img_path is None:
                continue

            try:
                if img_path.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue

            try:
                raw = img_path.read_bytes()
            except OSError:
                continue
            if not raw or len(raw) > max_bytes:
                continue

            # Convert to JPEG (image-url endpoint assumes ".jpg").
            from io import BytesIO

            try:
                from PIL import Image as PILImage  # type: ignore
            except ImportError:
                logger.warning("Pillow not available; skipping preview image upload to MinIO (hint: pip install Pillow)")
                continue

            img = None
            converted = None
            try:
                img = PILImage.open(BytesIO(raw))
                if img.mode in ("RGBA", "P"):
                    converted = img.convert("RGB")
                    out_img = converted
                else:
                    out_img = img
                out = BytesIO()
                out_img.save(out, format="JPEG", quality=85, optimize=True)
                image_bytes = out.getvalue()
            except Exception as e:
                logger.warning("Failed converting preview image %s to JPEG: %s", local_id, str(e)[:200])
                continue
            finally:
                for to_close in (converted, img):
                    if to_close is None:
                        continue
                    with contextlib.suppress(Exception):
                        to_close.close()

            digest = hashlib.sha256(image_bytes).hexdigest()
            img_id = digest_to_img_id.get(digest)
            if not img_id:
                chunk_key = f"asset{start_index}"
                start_index += 1
                try:
                    img_id = minio_service.upload_image(
                        image_data=image_bytes,
                        tenant_id=tenant_id,
                        dataset_id=dataset_id,
                        document_id=document_id,
                        chunk_key=chunk_key,
                        extension="jpg",
                    )
                except Exception as e:
                    logger.warning("Preview image upload to MinIO failed (skipped): %s", str(e)[:200])
                    continue
                digest_to_img_id[digest] = img_id

            local_id_to_img_id[local_id] = img_id

        if img_id and img_id not in referenced_img_ids:
            referenced_img_ids.append(img_id)

    if not referenced_img_ids:
        return text, [], start_index

    # Rewrite refs in a single pass.
    def _repl(match: re.Match) -> str:
        raw_id = match.group(1)
        if not raw_id:
            return match.group(0)
        try:
            local_id = uuid.UUID(raw_id).hex
        except ValueError:
            return match.group(0)
        img_id = local_id_to_img_id.get(local_id)
        if not img_id:
            return match.group(0)
        return f"/api/v1/documents/image-url/{img_id}"

    text = PREVIEW_IMAGE_REF_RE.sub(_repl, text)
    return text, referenced_img_ids, start_index


def _resolve_writable_dataset(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID | None,
) -> Dataset:
    """
    Resolve a dataset that the current user can write to.

    - If dataset_id is provided: enforce writable permission.
    - Otherwise: pick the earliest writable dataset in tenant, or auto-create a default one.
    """
    if dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_writable(db, dataset, account_id)
        return dataset

    # Ensure member exists and has edit role (assert_dataset_writable enforces it as well).
    member = DatasetService.ensure_member(db, tenant_id, account_id)

    datasets = db.query(Dataset).filter(Dataset.tenant_id == tenant_id).order_by(Dataset.created_at.asc()).all()
    for ds in datasets:
        try:
            DatasetService.assert_dataset_writable(db, ds, account_id)
            return ds
        except HTTPException:
            continue

    # Validate user permission to create a dataset.
    role = (getattr(member, 'role', None) or "").lower()
    if role not in EDIT_ROLES:
        raise HTTPException(
            status_code=403,
            detail="No permission to create dataset. Please contact an administrator."
        )

    # Auto-create a default dataset with restricted permission (ONLY_ME).
    return DatasetService.create_dataset(
        db=db,
        tenant_id=tenant_id,
        name="Default Dataset",
        description="Auto-created (no dataset_id specified)",
        permission=DatasetPermissionEnum.ONLY_ME,  # Restrict permission to avoid privilege escalation.
        owner_id=account_id,
        partial_members=[],
    )


def _assert_document_acl_readable(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document: DBDocument,
    dataset: Dataset | None = None,
) -> None:
    """
    Enforce document-level ACL ("security trimming") in addition to dataset permission.

    - Dataset permission is enforced by callers (or passed in via `dataset`).
    - Dataset owners can always access documents in their dataset.
    """
    if not account_id:
        return

    # Dataset owner bypass for management.
    if dataset is not None and str(getattr(dataset, "owner_id", "") or "") == account_id:
        return

    mode = (str(getattr(document, "access_mode", "") or "")).strip().lower()
    if not mode or mode in {"inherit", "all_team_members"}:
        return

    owner_id = (str(getattr(document, "owner_id", "") or "")).strip()
    if owner_id and owner_id == account_id:
        return

    if mode == "only_me":
        raise HTTPException(status_code=403, detail=NO_DOCUMENT_ACCESS_DETAIL)

    if mode == "partial_members":
        exists = (
            db.query(DocumentPermission)
            .filter(
                DocumentPermission.tenant_id == tenant_id,
                DocumentPermission.document_id == document.id,
                DocumentPermission.account_id == account_id,
            )
            .first()
        )
        if exists:
            return

        # Group allowlist (fail-closed): allow if the account is a member of any allowed group.
        group_ids = TenantGroupService.resolve_account_group_ids(db, tenant_id=tenant_id, account_id=account_id)
        if group_ids:
            allowlist_groups = DocumentGroupPermissionService.get_document_partial_group_list(
                db,
                tenant_id,
                document.id,
            )
            if allowlist_groups:
                allowed = set(allowlist_groups)
                if any(gid in allowed for gid in group_ids):
                    return

        raise HTTPException(status_code=403, detail=NO_DOCUMENT_ACCESS_DETAIL)

    # Unknown mode: fail closed.
    raise HTTPException(status_code=403, detail=NO_DOCUMENT_ACCESS_DETAIL)


def _get_document_for_lifecycle(db: Session, tenant_id: UUID, document_id: UUID) -> DBDocument | None:
    return (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )


def _assert_document_writable_for_lifecycle(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document: DBDocument,
) -> None:
    ds: Dataset | None = None
    if getattr(document, "dataset_id", None):
        ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)
    else:
        member = DatasetService.ensure_member(db, tenant_id, account_id)
        role = (getattr(member, "role", None) or "").lower()
        if role not in EDIT_ROLES:
            raise HTTPException(status_code=403, detail="No permission to manage unassigned documents")

    _assert_document_acl_readable(db, tenant_id=tenant_id, account_id=account_id, document=document, dataset=ds)


def _get_document_for_chunk_ops(db: Session, tenant_id: UUID, document_id: UUID) -> DBDocument | None:
    return (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )


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
    ds: Dataset | None = None
    if getattr(document, "dataset_id", None):
        ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)
    else:
        member = DatasetService.ensure_member(db, tenant_id, account_id)
        role = (getattr(member, "role", None) or "").lower()
        if role not in EDIT_ROLES:
            raise HTTPException(status_code=403, detail="No permission to manage unassigned documents")

    _assert_document_acl_readable(db, tenant_id=tenant_id, account_id=account_id, document=document, dataset=ds)


class UrlUploadRequest(BaseModel):
    """Upload a document by fetching a remote URL (connector skeleton)."""

    url: str = Field(..., max_length=2000)
    dataset_id: UUID | None = None
    filename: str | None = Field(default=None, max_length=500, description="Optional override filename (used for extension + display)")
    # Optional: authenticated fetch (cookie/bearer/basic) for private pages.
    fetch_headers: dict[str, str] | None = None
    user_agent: str | None = Field(default=None, max_length=200)
    parser_backend: str = Field(default=settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Field(default=settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: DocumentPipelineOptions | None = None


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
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    with contextlib.suppress(Exception):
        iso = value
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    return None


def _normalize_datetime_utc_iso(raw: str | None) -> str | None:
    dt = _parse_datetime_best_effort(raw)
    if dt is None:
        return None
    return dt.isoformat()


class LocalHtmlIngestRequest(BaseModel):
    """Ingest a local HTML payload as a document (internal connector helper)."""

    html: str = Field(..., description="HTML content (fragment or full document)")
    source_url: str | None = Field(default=None, max_length=2000, description="Best-effort source URL for citations/debug")
    dataset_id: UUID | None = None
    filename: str | None = Field(default=None, max_length=500, description="Optional override filename (used for extension + display)")
    parser_backend: str = Field(default=settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Field(default=settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: DocumentPipelineOptions | None = None


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
    if not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    url = await validate_url_for_ingest(str(body.url or ""))

    # 1) Resolve dataset permission.
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, body.dataset_id)

    # 2) Download to a temp path first, then decide extension (URL may not include it).
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4()
    temp_path = upload_dir / f"{file_id}.urltmp"

    downloaded = await download_url_to_path(
        url,
        temp_path,
        max_bytes=int(getattr(settings, "URL_INGEST_MAX_BYTES", 0) or settings.MAX_FILE_SIZE),
        timeout_sec=float(getattr(settings, "URL_INGEST_TIMEOUT_SEC", 30.0) or 30.0),
        follow_redirects=bool(getattr(settings, "URL_INGEST_FOLLOW_REDIRECTS", False)),
        user_agent=(body.user_agent or None),
        extra_headers=(body.fetch_headers or None),
    )

    fetched_at_iso = datetime.now(UTC).isoformat()
    last_modified_raw = str(getattr(downloaded, "last_modified", "") or "").strip() or None
    last_modified_norm = _normalize_datetime_utc_iso(last_modified_raw) if last_modified_raw else None
    etag_raw = str(getattr(downloaded, "etag", "") or "").strip() or None
    if etag_raw and len(etag_raw) > 500:
        etag_raw = etag_raw[:500]

    # Staleness signal: prefer origin last_modified; fallback to fetch timestamp when unknown.
    source_last_modified_at = last_modified_norm or fetched_at_iso
    source_last_modified_source = "http:last-modified" if last_modified_norm else "fallback:fetched_at"

    content_type = (downloaded.content_type or "").split(";", 1)[0].strip().lower()

    # 3) Determine file extension.
    def _ext_from_filename(name: str | None) -> str | None:
        if not name:
            return None
        ext = Path(str(name)).suffix.lower()
        return ext if ext else None

    def _ext_from_content_type(ct: str) -> str | None:
        if not ct:
            return None
        if ct in {"text/html"}:
            return HTML_FILE_EXTENSION
        if ct in {"text/plain"}:
            return ".txt"
        if ct in {"text/markdown", "text/x-markdown"}:
            return ".md"
        if ct in {"application/pdf"}:
            return ".pdf"
        if ct in {"application/json"}:
            return ".json"
        if ct in {"text/xml", "application/xml", "application/rss+xml", "application/atom+xml"}:
            return ".xml"
        return None

    # Prefer explicit filename override, then URL path, then content-type.
    file_ext = _ext_from_filename(body.filename)
    if not file_ext:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        file_ext = _ext_from_filename(Path(parsed.path).name)
    if not file_ext:
        file_ext = _ext_from_content_type(content_type)
    if not file_ext:
        # Best-effort: fall back to generic text if content looks text-ish.
        if content_type.startswith("text/"):
            file_ext = ".txt"
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported content-type: {content_type or 'unknown'}")

    file_ext = file_ext.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}")

    final_path = upload_dir / f"{file_id}{file_ext}"
    try:
        temp_path.replace(final_path)
    except Exception:
        try:
            shutil.move(str(temp_path), str(final_path))
        except Exception as exc:  # noqa: BLE001
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"failed to finalize downloaded file: {str(exc)[:120]}") from exc

    # Best-effort URL canonicalization metadata (for dedup/debug/analytics).
    url_final = str(getattr(downloaded, "final_url", "") or url).strip() or url
    url_normalized_requested = normalize_url_for_dedup(url)
    url_normalized_final = normalize_url_for_dedup(url_final)
    url_canonical: str | None = None
    url_normalized_canonical: str | None = None

    if content_type and "html" in content_type:
        def _read_html_prefix(path: Path) -> str:
            with path.open("rb") as f:
                return f.read(200_000).decode("utf-8", "ignore")

        try:
            html_prefix = await asyncio.to_thread(_read_html_prefix, final_path)
            url_canonical = extract_canonical_url(html_prefix, base_url=url_final)
            url_normalized_canonical = normalize_url_for_dedup(url_canonical) if url_canonical else None
        except Exception:
            url_canonical = None
            url_normalized_canonical = None

    # Prefer canonical if available; otherwise final URL.
    url_normalized = url_normalized_canonical or url_normalized_final or url_normalized_requested

    # 4) Resolve ingestion policy (optional) based on the inferred filename/ext.
    safe_name = _sanitize_filename(body.filename or Path(final_path).name)

    pipeline_options = PipelineOptions(**(body.pipeline.model_dump(exclude_none=True) if body.pipeline else {}))

    dataset_meta = (getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}
    policy = parse_ingestion_policy_from_metadata(dataset_meta if isinstance(dataset_meta, dict) else {})  # type: ignore[arg-type]
    matched_rule = match_ingestion_rule(policy, filename=safe_name, file_ext=file_ext)

    dataset_default_pb = None
    dataset_default_cs = None
    if dataset is not None:
        ds_meta = getattr(dataset, "dataset_metadata", None)
        if isinstance(ds_meta, dict):
            raw_pb = ds_meta.get("default_parser_backend")
            raw_cs = ds_meta.get("default_chunk_strategy")
            if isinstance(raw_pb, str) and raw_pb.strip():
                dataset_default_pb = raw_pb.strip().lower()
            if isinstance(raw_cs, str) and raw_cs.strip():
                dataset_default_cs = raw_cs.strip().lower()

    default_pb_eff = dataset_default_pb or str(getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto").strip().lower() or "auto"
    default_cs_eff = dataset_default_cs or str(getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive").strip().lower() or "langchain_recursive"

    parser_backend_choice = str(body.parser_backend or default_pb_eff)
    chunk_strategy_choice = str(body.chunk_strategy or default_cs_eff)
    policy_patch = PipelineOptions()
    ingestion_meta: dict[str, Any] | None = None

    if matched_rule is not None:
        default_pb = default_pb_eff
        req_pb = (parser_backend_choice or "").strip().lower()
        if req_pb in {"", "auto", default_pb} and matched_rule.parser_backend:
            parser_backend_choice = str(matched_rule.parser_backend)

        default_cs = default_cs_eff
        req_cs = (chunk_strategy_choice or "").strip().lower()
        if req_cs in {"", default_cs} and matched_rule.chunk_strategy:
            chunk_strategy_choice = str(matched_rule.chunk_strategy)

        preprocess_steps: list[dict[str, Any]] = []
        pp = getattr(matched_rule, "preprocess", None)
        steps = getattr(pp, "steps", None) if pp is not None and bool(getattr(pp, "enabled", True)) else None
        if isinstance(steps, list) and steps:
            preprocess_steps = [
                {
                    "id": str(getattr(s, "id", "") or "").strip(),
                    "params": dict(getattr(s, "params", {}) or {}),
                }
                for s in steps
            ]

        patch_dict: dict[str, Any] = {}
        profile_ref = getattr(matched_rule, "governance_profile_ref", None)
        if isinstance(profile_ref, str) and profile_ref.strip():
            try:
                resolved = resolve_governance_profile_ref(db=db, tenant_id=tenant_id, profile_ref=profile_ref.strip())
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid governance_profile_ref: {str(exc)[:120]}") from exc
            patch_dict.update(dict(resolved.pipeline_patch or {}))
            if resolved.regex_rules:
                patch_dict["governance_regex_rules"] = list(resolved.regex_rules)

        patch_dict.update(dict(getattr(matched_rule, "pipeline_patch", None) or {}))
        if patch_dict:
            policy_patch = PipelineOptions(**patch_dict)

        ingestion_meta = {
            "version": str(getattr(policy, "version", "1") if policy is not None else "1"),
            "rule": {"id": matched_rule.id, "name": matched_rule.name},
            "preprocess": {"enabled": bool(preprocess_steps), "steps": preprocess_steps},
            "governance_profile_ref": (profile_ref.strip() if isinstance(profile_ref, str) and profile_ref.strip() else None),
            "source_url": url,
        }

    pipeline_options = merge_pipeline_options(policy_patch, pipeline_options)

    # 5) Resolve backend/strategy after policy application.
    try:
        requested_parser_backend = (parser_backend_choice or "").strip().lower()
        if file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
            resolved_parser_backend = "auto"
        else:
            resolved_parser_backend = parser_factory.resolve_backend(file_ext, parser_backend_choice)
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy_choice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pipeline_effective = resolve_pipeline_effective(
        dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}),
        document_metadata={},
        request_overrides=pipeline_options,
    )
    if resolved_chunk_strategy not in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        _validate_chunk_params(pipeline_effective.chunk_size, pipeline_effective.chunk_overlap)

    # 6) Unified ingestion run manifest (best-effort; creates a run when missing).
    if ingestion_run_id is None:
        try:
            ingestion_kind_norm = str(ingestion_kind or "upload_url").strip() or "upload_url"
            run_cfg = {
                "source_url": url,
                "url_final_url": url_final or None,
                "url_canonical_url": url_canonical,
                "parser_backend_requested": str(body.parser_backend or "")[:80],
                "chunk_strategy_requested": str(body.chunk_strategy or "")[:80],
                "parser_backend": str(resolved_parser_backend or "")[:80],
                "chunk_strategy": str(resolved_chunk_strategy or "")[:80],
            }
            ingestion_run = IngestionRunService.create_run(
                db,
                tenant_id=tenant_id,
                dataset_id=getattr(dataset, "id", None),
                requested_by=account_id,
                kind=ingestion_kind_norm,
                config=run_cfg,
                expected_documents=1,
            )
            ingestion_run_id = ingestion_run.id
        except Exception:
            ingestion_run_id = None

    # 7) Create document record.
    doc_metadata = {
        "parser_backend": resolved_parser_backend,
        "parser_backend_requested": str(body.parser_backend or "").lower(),
        "chunk_strategy": resolved_chunk_strategy,
        "chunk_strategy_requested": str(body.chunk_strategy or "").lower(),
        "source_url": url,
        "source_fetched_at": fetched_at_iso,
        "source_last_modified_at": source_last_modified_at,
        "source_last_modified_source": source_last_modified_source,
        "source_last_modified_raw": last_modified_raw,
        "source_etag": etag_raw,
        "url_content_type": content_type or None,
        "url_final_url": url_final or None,
        "url_canonical_url": url_canonical,
        "url_normalized_url": url_normalized or None,
        "url_normalized_requested": url_normalized_requested or None,
        "url_normalized_final": url_normalized_final or None,
        "url_normalized_canonical": url_normalized_canonical,
    }
    upsert_pipeline_metadata(doc_metadata, options=pipeline_options)
    if ingestion_meta:
        doc_metadata["ingestion"] = ingestion_meta

    pipeline_hash = _compute_pipeline_hash(doc_metadata)
    doc_metadata["pipeline_hash"] = pipeline_hash
    # Versioning: the first processed pipeline is the active one by default.
    doc_metadata.setdefault("active_pipeline_hash", pipeline_hash)
    doc_metadata.setdefault("active_pipeline_ready", False)
    if ingestion_run_id is not None:
        doc_metadata.setdefault("created_by_run_id", str(ingestion_run_id))
        doc_metadata["last_ingestion_run_id"] = str(ingestion_run_id)
        doc_metadata["last_ingestion_kind"] = str(ingestion_kind or "upload_url")

    # Tenant quotas (Wave22-T094): enforce docs/storage limits once size is known.
    try:
        from app.services.tenant_quota_service import enforce_tenant_upload_quotas

        enforce_tenant_upload_quotas(
            db,
            tenant_id=tenant_id,
            additional_docs=1,
            additional_bytes=int(getattr(downloaded, "size_bytes", 0) or 0),
        )
    except HTTPException:
        with contextlib.suppress(OSError):
            final_path.unlink(missing_ok=True)
        raise

    db_document = DBDocument(
        id=file_id,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        filename=safe_name,
        file_type=file_ext.lstrip("."),
        file_size=int(downloaded.size_bytes),
        file_path=str(final_path),
        owner_id=account_id,
        access_mode=None,  # inherit dataset permission by default
        status="pending",
        processing_progress=0,
        doc_metadata=doc_metadata,
    )

    db.add(db_document)
    db.commit()
    db.refresh(db_document)
    if ingestion_run_id is not None:
        with contextlib.suppress(Exception):
            IngestionRunService.add_document(
                db,
                tenant_id=tenant_id,
                run_id=ingestion_run_id,
                document_id=db_document.id,
                source_ref=url,
                initial_status=str(getattr(db_document, "status", "") or "pending"),
                doc_meta=dict(doc_metadata),
            )

    # 8) Process document: enqueue if available; otherwise run/attach to background_tasks.
    job_id = f"doc:{tenant_id}:{file_id}:{pipeline_hash}"
    task_id = await enqueue_document_processing(
        tenant_id=tenant_id,
        document_id=file_id,
        requested_by=account_id,
        job_id=job_id,
    )
    if task_id:
        meta = dict(db_document.doc_metadata or {})
        meta["task_id"] = task_id
        db_document.doc_metadata = meta
        db.commit()
        db.refresh(db_document)
    else:
        if background_tasks is not None:
            background_tasks.add_task(
                document_processor.process_document,
                final_path,
                file_id,
                tenant_id,
                resolved_parser_backend,
                resolved_chunk_strategy,
            )
        else:
            # Connector runs may execute outside of a FastAPI request lifecycle; run inline.
            await document_processor.process_document(
                file_path=final_path,
                document_id=file_id,
                tenant_id=tenant_id,
                parser_backend=resolved_parser_backend,
                chunk_strategy=resolved_chunk_strategy,
                db=db,
            )

    return db_document


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


@router.post("/upload", response_model=DocumentDetail, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    form: Annotated[UploadDocumentFormFields, Depends()],
    overrides_form: Annotated[PipelineOverridesFormFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)]
):
    """
    Upload a document.

    Flow:
    1. Validate file type and size
    2. Save file locally
    3. Create database record
    4. Process document asynchronously (parse, chunk, embed)
    """

    # 0. Filename + optional directory-preserving upload hint (folder uploads).
    raw_filename = file.filename
    upload_key = _normalize_upload_key(raw_filename)
    source_path = upload_key if "/" in upload_key else None
    file.filename = _sanitize_filename(raw_filename)

    # 1. Validate file type.
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )

    parser_backend = form.parser_backend
    chunk_strategy = form.chunk_strategy
    pipeline = form.pipeline
    dataset_id = form.dataset_id
    user_metadata = form.user_metadata

    pipeline_parsed = _parse_pipeline_json(pipeline)
    pipeline_overrides = PipelineOptionOverrides(**asdict(overrides_form))
    pipeline_options = _to_pipeline_options(
        pipeline=pipeline_parsed,
        overrides=pipeline_overrides,
    )
    # Permission check.
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, dataset_id)

    # Dataset ingestion policy (file-level pre-processing + per-type overrides).
    dataset_meta = (getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}
    policy = parse_ingestion_policy_from_metadata(dataset_meta if isinstance(dataset_meta, dict) else {})  # type: ignore[arg-type]
    matched_rule = match_ingestion_rule(policy, filename=upload_key or file.filename, file_ext=file_ext)

    ingestion_meta: dict[str, Any] | None = None
    # Dataset-level ingestion defaults (parser/chunk strategy). These apply when the request uses
    # the global defaults, keeping explicit user choices untouched.
    dataset_default_pb = None
    dataset_default_cs = None
    if isinstance(dataset_meta, dict):
        raw_pb = dataset_meta.get("default_parser_backend")
        raw_cs = dataset_meta.get("default_chunk_strategy")
        if isinstance(raw_pb, str) and raw_pb.strip():
            dataset_default_pb = raw_pb.strip().lower()
        if isinstance(raw_cs, str) and raw_cs.strip():
            dataset_default_cs = raw_cs.strip().lower()

    global_default_pb = str(getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto").strip().lower() or "auto"
    global_default_cs = (
        str(getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive").strip().lower()
        or "langchain_recursive"
    )
    default_pb_eff = dataset_default_pb or global_default_pb
    default_cs_eff = dataset_default_cs or global_default_cs

    parser_backend_choice: str = parser_backend
    chunk_strategy_choice: str = chunk_strategy

    req_pb = (parser_backend or "").strip().lower()
    if dataset_default_pb and req_pb in {"", "auto", global_default_pb}:
        parser_backend_choice = dataset_default_pb

    req_cs = (chunk_strategy or "").strip().lower()
    if dataset_default_cs and req_cs in {"", global_default_cs}:
        chunk_strategy_choice = dataset_default_cs
    preprocess_steps: list[dict] = []
    policy_patch = PipelineOptions()

    if matched_rule is not None:
        # Only override when the request uses the global defaults (avoid surprising explicit choices).
        default_pb = default_pb_eff
        req_pb = (parser_backend_choice or "").strip().lower()
        if req_pb in {"", "auto", default_pb} and matched_rule.parser_backend:
            parser_backend_choice = str(matched_rule.parser_backend)

        default_cs = default_cs_eff
        req_cs = (chunk_strategy_choice or "").strip().lower()
        if req_cs in {"", default_cs} and matched_rule.chunk_strategy:
            chunk_strategy_choice = str(matched_rule.chunk_strategy)

        pp = getattr(matched_rule, "preprocess", None)
        steps = getattr(pp, "steps", None) if pp is not None and bool(getattr(pp, "enabled", True)) else None
        if isinstance(steps, list) and steps:
            preprocess_steps = [
                {
                    "id": str(getattr(s, "id", "") or "").strip(),
                    "params": dict(getattr(s, "params", {}) or {}),
                }
                for s in steps
            ]

        # Merge governance profile patch + rule patch into pipeline overrides.
        patch_dict: dict[str, Any] = {}
        profile_ref = getattr(matched_rule, "governance_profile_ref", None)
        if isinstance(profile_ref, str) and profile_ref.strip():
            try:
                resolved = resolve_governance_profile_ref(db=db, tenant_id=tenant_id, profile_ref=profile_ref.strip())
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid governance_profile_ref: {str(exc)[:120]}") from exc
            patch_dict.update(dict(resolved.pipeline_patch or {}))
            if resolved.regex_rules:
                patch_dict["governance_regex_rules"] = list(resolved.regex_rules)

        patch_dict.update(dict(getattr(matched_rule, "pipeline_patch", None) or {}))
        if patch_dict:
            policy_patch = PipelineOptions(**patch_dict)

        ingestion_meta = {
            "version": str(getattr(policy, "version", "1") if policy is not None else "1"),
            "rule": {"id": matched_rule.id, "name": matched_rule.name},
            "preprocess": {"enabled": bool(preprocess_steps), "steps": preprocess_steps},
            "governance_profile_ref": (profile_ref.strip() if isinstance(profile_ref, str) and profile_ref.strip() else None),
        }

    # Policy patches are merged before user overrides (user wins).
    pipeline_options = merge_pipeline_options(policy_patch, pipeline_options)

    # Resolve backend/strategy after policy application.
    try:
        requested_parser_backend = (parser_backend_choice or "").strip().lower()
        if file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
            # Keep "auto" for background routing (quality scoring happens in DocumentProcessor).
            resolved_parser_backend = "auto"
        else:
            resolved_parser_backend = parser_factory.resolve_backend(file_ext, parser_backend_choice)
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy_choice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pipeline_effective = resolve_pipeline_effective(
        dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}),
        document_metadata={},
        request_overrides=pipeline_options,
    )
    if resolved_chunk_strategy not in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        _validate_chunk_params(pipeline_effective.chunk_size, pipeline_effective.chunk_overlap)

    # 3. Save file.
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique filename.
    file_id = uuid.uuid4()
    file_path = upload_dir / f"{file_id}{file_ext}"

    file_size, file_sha256 = await save_upload_file_with_hash(file, file_path, max_bytes=settings.MAX_FILE_SIZE)

    # Tenant quotas (Wave22-T094): enforce cheap docs/storage limits at upload time.
    # This is best-effort and fail-open by default when quotas are disabled.
    try:
        from app.services.tenant_quota_service import enforce_tenant_upload_quotas

        enforce_tenant_upload_quotas(
            db,
            tenant_id=tenant_id,
            additional_docs=1,
            additional_bytes=int(file_size or 0),
        )
    except HTTPException:
        with contextlib.suppress(OSError):
            file_path.unlink(missing_ok=True)
        raise

    # 4. Create database record.
    doc_metadata = {
        "parser_backend": resolved_parser_backend,
        "parser_backend_requested": (parser_backend or "").lower(),
        "chunk_strategy": resolved_chunk_strategy,
        "chunk_strategy_requested": (chunk_strategy or "").lower(),
    }
    if source_path:
        doc_metadata["source_path"] = source_path
    if isinstance(file_sha256, str) and file_sha256:
        doc_metadata["file_sha256"] = file_sha256
    upsert_pipeline_metadata(doc_metadata, options=pipeline_options)
    if ingestion_meta:
        doc_metadata["ingestion"] = ingestion_meta

    # Optional: user metadata (tags/notes/...) attached at upload time.
    if isinstance(user_metadata, str) and user_metadata.strip():
        raw = user_metadata.strip()
        max_len = int(getattr(settings, "USER_METADATA_FORM_JSON_MAX_CHARS", 20_000) or 20_000)
        if max_len > 0 and len(raw) > max_len:
            raise HTTPException(status_code=400, detail="user_metadata is too large")
        try:
            obj = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Invalid user_metadata JSON (expect UTF-8)") from exc
        if not isinstance(obj, dict):
            raise HTTPException(status_code=400, detail="user_metadata must be a JSON object")
        doc_metadata["user"] = _apply_user_metadata_patch(current={}, patch=obj, replace=True)
    pipeline_hash = _compute_pipeline_hash(doc_metadata)
    doc_metadata["pipeline_hash"] = pipeline_hash
    # Versioning: the first processed pipeline is the active one by default.
    doc_metadata.setdefault("active_pipeline_hash", pipeline_hash)
    doc_metadata.setdefault("active_pipeline_ready", False)

    # Ingest idempotency lock (best-effort):
    # Prevent duplicate concurrent uploads of the same file+pipeline into the same dataset.
    #
    # Key must bind:
    # - tenant_id (multi-tenant safety)
    # - dataset_id (same file can exist in different datasets)
    # - file_sha256 (same content)
    # - pipeline_hash (same preprocessing/chunking/indexing semantics)
    ingest_lock_key: str | None = None
    ingest_lock_value: str | None = None
    if isinstance(file_sha256, str) and file_sha256 and pipeline_hash and dataset is not None:
        try:
            from app.tasks.locks import acquire_lock, make_lock_value
            from app.tasks.queue import get_queue
            redis = await get_queue()
        except Exception:  # noqa: BLE001
            redis = None

        if redis is not None:
            ingest_lock_key = f"lock:ingest:{tenant_id}:{dataset.id}:{file_sha256}:{pipeline_hash}"
            ingest_lock_value = make_lock_value(account_id)
            lock_ttl = 60 * 40  # 40 min (slightly above worker job_timeout)
            acquired = await acquire_lock(redis, key=ingest_lock_key, value=ingest_lock_value, ttl_sec=lock_ttl)
            if not acquired:
                # Remove the just-uploaded file to save disk.
                with contextlib.suppress(OSError):
                    file_path.unlink(missing_ok=True)
                raise HTTPException(status_code=409, detail="Duplicate ingest in progress")

            doc_metadata["ingest_lock_key"] = ingest_lock_key
            doc_metadata["ingest_lock_value"] = ingest_lock_value

    # Unified ingestion run manifest (best-effort; never blocks uploads).
    ingestion_run = None
    try:
        ingestion_run = IngestionRunService.create_run(
            db,
            tenant_id=tenant_id,
            dataset_id=getattr(dataset, "id", None),
            requested_by=account_id,
            kind="upload",
            config={
                "filename": str(file.filename or "")[:255],
                "source_path": (str(source_path)[:1000] if source_path else None),
                "file_ext": str(file_ext or "")[:16],
                "parser_backend_requested": str(parser_backend or "")[:80],
                "chunk_strategy_requested": str(chunk_strategy or "")[:80],
                "parser_backend": str(resolved_parser_backend or "")[:80],
                "chunk_strategy": str(resolved_chunk_strategy or "")[:80],
                "pipeline_hash": str(pipeline_hash or "")[:64],
                "ingestion_meta": dict(ingestion_meta or {}),
                "pipeline": (pipeline_parsed.model_dump(exclude_none=True) if pipeline_parsed is not None else None),
            },
            expected_documents=1,
        )
    except Exception:
        ingestion_run = None

    def _attach_doc_to_ingestion_run(doc: DBDocument, *, created: bool) -> None:
        if ingestion_run is None or doc is None:
            return
        try:
            meta0 = dict(getattr(doc, "doc_metadata", None) or {})
            if created and not meta0.get("created_by_run_id"):
                meta0["created_by_run_id"] = str(ingestion_run.id)
            meta0["last_ingestion_run_id"] = str(ingestion_run.id)
            meta0["last_ingestion_kind"] = "upload"
            doc.doc_metadata = meta0
            db.commit()
            db.refresh(doc)
        except Exception:
            meta0 = dict(getattr(doc, "doc_metadata", None) or {})

        try:
            IngestionRunService.add_document(
                db,
                tenant_id=tenant_id,
                run_id=ingestion_run.id,
                document_id=doc.id,
                source_ref=(source_path or doc.filename),
                initial_status=str(getattr(doc, "status", "") or "created"),
                doc_meta=meta0 if isinstance(meta0, dict) else None,
            )
        except Exception:
            return

    # Optional: upload deduplication (same file_sha256 + same pipeline_hash within the same dataset).
    if bool(getattr(settings, "UPLOAD_DEDUP_ENABLED", False)) and isinstance(file_sha256, str) and file_sha256:
        dup = _find_duplicate_document(
            db,
            tenant_id=tenant_id,
            dataset_id=getattr(dataset, "id", None),
            file_sha256=file_sha256,
            pipeline_hash=pipeline_hash,
        )
        if dup is not None and str(getattr(dup, "status", "") or "").lower() not in {"failed"}:
            logger.info(
                "Upload dedup hit tenant_id=%s dataset_id=%s document_id=%s",
                str(tenant_id),
                str(getattr(dataset, "id", None)),
                str(getattr(dup, "id", "")),
            )
            # Remove the just-uploaded file to save disk.
            with contextlib.suppress(OSError):
                file_path.unlink(missing_ok=True)
            with contextlib.suppress(Exception):
                _attach_doc_to_ingestion_run(dup, created=False)
            return dup

        # Cross-version dedup: same file_sha256 exists in dataset but under a different pipeline_hash.
        #
        # Instead of creating a new document_id, reuse the existing document and create a new pipeline version
        # by patching its pipeline metadata and triggering a retry (preserving the active version until success).
        dup_any = _find_duplicate_document_by_sha(
            db,
            tenant_id=tenant_id,
            dataset_id=getattr(dataset, "id", None),
            file_sha256=file_sha256,
        )
        if dup_any is not None:
            status0 = str(getattr(dup_any, "status", "") or "").lower()
            if status0 in {"pending", "processing"}:
                raise HTTPException(status_code=409, detail=DUPLICATE_DOCUMENT_PROCESSING_DETAIL)

            # Remove the just-uploaded file to save disk.
            with contextlib.suppress(OSError):
                file_path.unlink(missing_ok=True)

            meta_any = dict(getattr(dup_any, "doc_metadata", None) or {})
            meta_any["parser_backend"] = resolved_parser_backend
            meta_any["parser_backend_requested"] = (parser_backend or "").lower()
            meta_any["chunk_strategy"] = resolved_chunk_strategy
            meta_any["chunk_strategy_requested"] = (chunk_strategy or "").lower()
            if source_path and not meta_any.get("source_path"):
                meta_any["source_path"] = source_path
            meta_any["file_sha256"] = str(file_sha256).strip().lower()
            upsert_pipeline_metadata(meta_any, options=pipeline_options)
            if ingestion_meta:
                meta_any["ingestion"] = ingestion_meta

            # Optional: attach/merge user metadata on the reused document.
            if isinstance(user_metadata, str) and user_metadata.strip():
                raw = user_metadata.strip()
                max_len = int(getattr(settings, "USER_METADATA_FORM_JSON_MAX_CHARS", 20_000) or 20_000)
                if max_len > 0 and len(raw) > max_len:
                    raise HTTPException(status_code=400, detail="user_metadata is too large")
                try:
                    obj = json.loads(raw)
                except Exception as exc:  # noqa: BLE001
                    raise HTTPException(status_code=400, detail="Invalid user_metadata JSON (expect UTF-8)") from exc
                if not isinstance(obj, dict):
                    raise HTTPException(status_code=400, detail="user_metadata must be a JSON object")
                current_user = meta_any.get("user") if isinstance(meta_any.get("user"), dict) else {}
                meta_any["user"] = _apply_user_metadata_patch(current=current_user, patch=obj, replace=False)

            # Preserve active version fields when missing (backward compatible for legacy docs).
            if "active_pipeline_hash" not in meta_any:
                meta_any["active_pipeline_hash"] = str(meta_any.get("pipeline_hash") or "").strip() or None
            if "active_pipeline_ready" not in meta_any:
                meta_any["active_pipeline_ready"] = bool(status0 == "completed")

            dup_any.doc_metadata = meta_any
            db.commit()
            db.refresh(dup_any)

            # Trigger reprocessing as a new pipeline version (best-effort; may no-op if unchanged).
            await retry_document_processing(
                document_id=dup_any.id,
                background_tasks=background_tasks,
                force=True,
                skip_if_unchanged=True,
                tenant_id=tenant_id,
                account_id=account_id,
                db=db,
            )
            db.refresh(dup_any)
            with contextlib.suppress(Exception):
                _attach_doc_to_ingestion_run(dup_any, created=False)
            return dup_any

    db_document = DBDocument(
        id=file_id,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        filename=file.filename,
        file_type=file_ext.lstrip('.'),
        file_size=file_size,
        file_path=str(file_path),
        owner_id=account_id,
        access_mode=None,  # inherit dataset permission by default
        status='pending',
        processing_progress=0,
        doc_metadata=doc_metadata,
    )

    db.add(db_document)
    db.commit()
    db.refresh(db_document)
    with contextlib.suppress(Exception):
        _attach_doc_to_ingestion_run(db_document, created=True)

    # 5. Process document in background: enqueue if available (fallback to BackgroundTasks).
    job_id = f"doc:{tenant_id}:{file_id}:{pipeline_hash}"
    task_id = await enqueue_document_processing(
        tenant_id=tenant_id,
        document_id=file_id,
        requested_by=account_id,
        job_id=job_id,
    )
    if task_id:
        meta = dict(db_document.doc_metadata or {})
        meta["task_id"] = task_id
        db_document.doc_metadata = meta
        db.commit()
        db.refresh(db_document)
    else:
        background_tasks.add_task(
            document_processor.process_document,
            file_path,
            file_id,
            tenant_id,
            resolved_parser_backend,
            resolved_chunk_strategy,
        )

    return db_document


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
    if not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    # 1) Resolve dataset permission.
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, body.dataset_id)

    # 2) Validate + write file.
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    raw_html = str(body.html or "")
    data = raw_html.encode("utf-8", "ignore")
    if int(getattr(settings, "MAX_FILE_SIZE", 0) or 0) > 0 and len(data) > int(settings.MAX_FILE_SIZE):
        raise HTTPException(status_code=400, detail="File too large")

    safe_name = _sanitize_filename(body.filename or "confluence-page.html")
    file_ext = Path(safe_name).suffix.lower() or HTML_FILE_EXTENSION
    if file_ext == ".htm":
        file_ext = HTML_FILE_EXTENSION
    if not file_ext.startswith("."):
        file_ext = "." + file_ext
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}")

    file_id = uuid.uuid4()
    file_path = upload_dir / f"{file_id}{file_ext}"
    try:
        file_path.write_bytes(data)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to write html file: {str(exc)[:120]}") from exc

    file_size = int(len(data))
    content_type = "text/html"
    source_url = (str(body.source_url or "").strip() or None)
    url_normalized = normalize_url_for_dedup(source_url) if source_url else None
    fetched_at_iso = datetime.now(UTC).isoformat()

    # 3) Resolve ingestion policy (best-effort) based on filename/ext.
    pipeline_options = PipelineOptions(**(body.pipeline.model_dump(exclude_none=True) if body.pipeline else {}))

    dataset_meta = (getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}
    policy = parse_ingestion_policy_from_metadata(dataset_meta if isinstance(dataset_meta, dict) else {})  # type: ignore[arg-type]
    matched_rule = match_ingestion_rule(policy, filename=safe_name, file_ext=file_ext)

    dataset_default_pb = None
    dataset_default_cs = None
    if dataset is not None:
        ds_meta = getattr(dataset, "dataset_metadata", None)
        if isinstance(ds_meta, dict):
            raw_pb = ds_meta.get("default_parser_backend")
            raw_cs = ds_meta.get("default_chunk_strategy")
            if isinstance(raw_pb, str) and raw_pb.strip():
                dataset_default_pb = raw_pb.strip().lower()
            if isinstance(raw_cs, str) and raw_cs.strip():
                dataset_default_cs = raw_cs.strip().lower()

    default_pb_eff = dataset_default_pb or str(getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto").strip().lower() or "auto"
    default_cs_eff = (
        dataset_default_cs
        or str(getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive").strip().lower()
        or "langchain_recursive"
    )

    parser_backend_choice = str(body.parser_backend or default_pb_eff)
    chunk_strategy_choice = str(body.chunk_strategy or default_cs_eff)
    policy_patch = PipelineOptions()
    ingestion_meta: dict[str, Any] | None = None

    if matched_rule is not None:
        default_pb = default_pb_eff
        req_pb = (parser_backend_choice or "").strip().lower()
        if req_pb in {"", "auto", default_pb} and matched_rule.parser_backend:
            parser_backend_choice = str(matched_rule.parser_backend)

        default_cs = default_cs_eff
        req_cs = (chunk_strategy_choice or "").strip().lower()
        if req_cs in {"", default_cs} and matched_rule.chunk_strategy:
            chunk_strategy_choice = str(matched_rule.chunk_strategy)

        preprocess_steps: list[dict[str, Any]] = []
        pp = getattr(matched_rule, "preprocess", None)
        steps = getattr(pp, "steps", None) if pp is not None and bool(getattr(pp, "enabled", True)) else None
        if isinstance(steps, list) and steps:
            preprocess_steps = [
                {
                    "id": str(getattr(s, "id", "") or "").strip(),
                    "params": dict(getattr(s, "params", {}) or {}),
                }
                for s in steps
            ]

        patch_dict: dict[str, Any] = {}
        profile_ref = getattr(matched_rule, "governance_profile_ref", None)
        if isinstance(profile_ref, str) and profile_ref.strip():
            try:
                resolved = resolve_governance_profile_ref(db=db, tenant_id=tenant_id, profile_ref=profile_ref.strip())
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid governance_profile_ref: {str(exc)[:120]}") from exc
            patch_dict.update(dict(resolved.pipeline_patch or {}))
            if resolved.regex_rules:
                patch_dict["governance_regex_rules"] = list(resolved.regex_rules)

        patch_dict.update(dict(getattr(matched_rule, "pipeline_patch", None) or {}))
        if patch_dict:
            policy_patch = PipelineOptions(**patch_dict)

        ingestion_meta = {
            "version": str(getattr(policy, "version", "1") if policy is not None else "1"),
            "rule": {"id": matched_rule.id, "name": matched_rule.name},
            "preprocess": {"enabled": bool(preprocess_steps), "steps": preprocess_steps},
            "governance_profile_ref": (profile_ref.strip() if isinstance(profile_ref, str) and profile_ref.strip() else None),
            "source_url": source_url,
        }

    pipeline_options = merge_pipeline_options(policy_patch, pipeline_options)

    # 4) Resolve backend/strategy after policy application.
    try:
        resolved_parser_backend = parser_factory.resolve_backend(file_ext, parser_backend_choice)
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy_choice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pipeline_effective = resolve_pipeline_effective(
        dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}),
        document_metadata={},
        request_overrides=pipeline_options,
    )
    if resolved_chunk_strategy not in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        _validate_chunk_params(pipeline_effective.chunk_size, pipeline_effective.chunk_overlap)

    # 5) Unified ingestion run manifest (best-effort; creates a run when missing).
    if ingestion_run_id is None:
        try:
            ingestion_kind_norm = str(ingestion_kind or "connector_html").strip() or "connector_html"
            run_cfg = {
                "source_url": source_url,
                "content_type": content_type,
                "parser_backend_requested": str(body.parser_backend or "")[:80],
                "chunk_strategy_requested": str(body.chunk_strategy or "")[:80],
                "parser_backend": str(resolved_parser_backend or "")[:80],
                "chunk_strategy": str(resolved_chunk_strategy or "")[:80],
            }
            ingestion_run = IngestionRunService.create_run(
                db,
                tenant_id=tenant_id,
                dataset_id=getattr(dataset, "id", None),
                requested_by=account_id,
                kind=ingestion_kind_norm,
                config=run_cfg,
                expected_documents=1,
            )
            ingestion_run_id = ingestion_run.id
        except Exception:
            ingestion_run_id = None

    # 6) Create document record.
    doc_metadata = {
        "parser_backend": resolved_parser_backend,
        "parser_backend_requested": str(body.parser_backend or "").lower(),
        "chunk_strategy": resolved_chunk_strategy,
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
    upsert_pipeline_metadata(doc_metadata, options=pipeline_options)
    if ingestion_meta:
        doc_metadata["ingestion"] = ingestion_meta

    pipeline_hash = _compute_pipeline_hash(doc_metadata)
    doc_metadata["pipeline_hash"] = pipeline_hash
    doc_metadata.setdefault("active_pipeline_hash", pipeline_hash)
    doc_metadata.setdefault("active_pipeline_ready", False)
    if ingestion_run_id is not None:
        doc_metadata.setdefault("created_by_run_id", str(ingestion_run_id))
        doc_metadata["last_ingestion_run_id"] = str(ingestion_run_id)
        doc_metadata["last_ingestion_kind"] = str(ingestion_kind or "connector_html")

    db_document = DBDocument(
        id=file_id,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        filename=safe_name,
        file_type=file_ext.lstrip("."),
        file_size=file_size,
        file_path=str(file_path),
        owner_id=account_id,
        access_mode=None,  # inherit dataset permission by default
        status="pending",
        processing_progress=0,
        doc_metadata=doc_metadata,
    )

    db.add(db_document)
    db.commit()
    db.refresh(db_document)
    if ingestion_run_id is not None:
        with contextlib.suppress(Exception):
            IngestionRunService.add_document(
                db,
                tenant_id=tenant_id,
                run_id=ingestion_run_id,
                document_id=db_document.id,
                source_ref=(source_url or safe_name)[:1000] if (source_url or safe_name) else None,
                initial_status=str(getattr(db_document, "status", "") or "pending"),
                doc_meta=dict(doc_metadata),
            )

    # 7) Process document: enqueue if available; otherwise run/attach to background_tasks.
    job_id = f"doc:{tenant_id}:{file_id}:{pipeline_hash}"
    task_id = await enqueue_document_processing(
        tenant_id=tenant_id,
        document_id=file_id,
        requested_by=account_id,
        job_id=job_id,
    )
    if task_id:
        meta = dict(db_document.doc_metadata or {})
        meta["task_id"] = task_id
        db_document.doc_metadata = meta
        db.commit()
        db.refresh(db_document)
    else:
        if background_tasks is not None:
            background_tasks.add_task(
                document_processor.process_document,
                file_path,
                file_id,
                tenant_id,
                resolved_parser_backend,
                resolved_chunk_strategy,
            )
        else:
            await document_processor.process_document(
                file_path=file_path,
                document_id=file_id,
                tenant_id=tenant_id,
                parser_backend=resolved_parser_backend,
                chunk_strategy=resolved_chunk_strategy,
                db=db,
            )

    return db_document


@router.post("/upload-url", response_model=DocumentDetail, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def upload_document_from_url(
    background_tasks: BackgroundTasks,
    body: UrlUploadRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Fetch a remote URL and ingest it as a document.

    Notes:
    - Disabled by default: set URL_INGEST_ENABLED=true to enable.
    - SSRF guard: blocks private/loopback/link-local hosts by default.
    """
    return await _ingest_url_upload_request(
        background_tasks=background_tasks,
        body=body,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        ingestion_kind="upload_url",
    )


@router.post("/upload-batch", response_model=DocumentBatchUploadResponse, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def upload_documents_batch(
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File(...)],
    form: Annotated[UploadDocumentsBatchFormFields, Depends()],
    overrides_form: Annotated[PipelineOverridesFormFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Batch upload documents (concurrency-optimized).

    Supports uploading multiple documents concurrently to improve performance.

    Args:
        files: Document file list.
        max_concurrent: Max concurrent processing, default 5.
        Other params match the single-file upload endpoint.

    Returns:
        {
            "total": total files,
            "successful": list of successful documents,
            "failed": list of failed files (with errors)
        }
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    if len(files) > 50:
        raise HTTPException(status_code=400, detail="Too many files. Maximum 50 files per batch.")

    # Tenant quotas (Wave22-T094): fail fast on doc-count limits. Storage limits are enforced once
    # file sizes are known (after staging each file).
    from app.services.tenant_quota_service import enforce_tenant_upload_quotas

    enforce_tenant_upload_quotas(
        db,
        tenant_id=tenant_id,
        additional_docs=int(len(files or [])),
        additional_bytes=0,
    )
    
    parser_backend = form.parser_backend
    chunk_strategy = form.chunk_strategy
    pipeline = form.pipeline
    dataset_id = form.dataset_id
    precheck_first = form.precheck_first
    user_metadata_map = form.user_metadata_map

    pipeline_overrides = PipelineOptionOverrides(**asdict(overrides_form))

    # Cap concurrency.
    max_concurrent = min(int(form.max_concurrent or 0), 10)  # Max 10 concurrent.
    semaphore = asyncio.Semaphore(max_concurrent)

    pipeline_parsed = _parse_pipeline_json(pipeline)

    # Optional: per-file user metadata patches keyed by upload path (e.g. "folder/a.pdf" or "a.pdf").
    user_meta_by_key: dict[str, dict] = {}
    if isinstance(user_metadata_map, str) and user_metadata_map.strip():
        raw = user_metadata_map.strip()
        max_len = int(getattr(settings, "USER_METADATA_MAP_FORM_JSON_MAX_CHARS", 200_000) or 200_000)
        if max_len > 0 and len(raw) > max_len:
            raise HTTPException(status_code=400, detail="user_metadata_map is too large")
        try:
            obj = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Invalid user_metadata_map JSON (expect UTF-8)") from exc
        if not isinstance(obj, dict):
            raise HTTPException(status_code=400, detail="user_metadata_map must be a JSON object")
        for k, v in obj.items():
            if not isinstance(k, str) or not isinstance(v, dict):
                continue
            key = _normalize_upload_key(k)
            if key:
                user_meta_by_key[key] = v

    # Permission check (done once).
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, dataset_id)
    dataset_meta = (getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}
    policy = parse_ingestion_policy_from_metadata(dataset_meta if isinstance(dataset_meta, dict) else {})  # type: ignore[arg-type]

    # Unified ingestion run manifest for the batch (best-effort).
    ingestion_run = None
    try:
        ingestion_run = IngestionRunService.create_run(
            db,
            tenant_id=tenant_id,
            dataset_id=getattr(dataset, "id", None),
            requested_by=account_id,
            kind="upload_batch",
            config={
                "files": int(len(files or [])),
                "parser_backend_requested": str(parser_backend or "")[:80],
                "chunk_strategy_requested": str(chunk_strategy or "")[:80],
                "pipeline": (pipeline_parsed.model_dump(exclude_none=True) if pipeline_parsed is not None else None),
            },
            expected_documents=int(len(files or [])),
        )
    except Exception:
        ingestion_run = None
    # Dataset-level ingestion defaults: apply once for the batch (still allow per-file ingestion-policy overrides).
    dataset_default_pb = None
    dataset_default_cs = None
    if isinstance(dataset_meta, dict):
        raw_pb = dataset_meta.get("default_parser_backend")
        raw_cs = dataset_meta.get("default_chunk_strategy")
        if isinstance(raw_pb, str) and raw_pb.strip():
            dataset_default_pb = raw_pb.strip().lower()
        if isinstance(raw_cs, str) and raw_cs.strip():
            dataset_default_cs = raw_cs.strip().lower()

    global_default_pb = str(getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto").strip().lower() or "auto"
    global_default_cs = (
        str(getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive").strip().lower()
        or "langchain_recursive"
    )
    default_pb = dataset_default_pb or global_default_pb
    default_cs = dataset_default_cs or global_default_cs

    parser_backend_base = parser_backend
    chunk_strategy_base = chunk_strategy
    req_pb = (parser_backend or "").strip().lower()
    if dataset_default_pb and req_pb in {"", "auto", global_default_pb}:
        parser_backend_base = dataset_default_pb
    req_cs = (chunk_strategy or "").strip().lower()
    if dataset_default_cs and req_cs in {"", global_default_cs}:
        chunk_strategy_base = dataset_default_cs

    if precheck_first:
        if dataset is None:
            raise HTTPException(status_code=400, detail="dataset_id is required for precheck_first")

        async def _save_upload_only(file: UploadFile) -> dict:
            """Stage files to disk first so we can precheck before ingesting."""
            async with semaphore:
                source_path: str | None = None
                upload_key: str | None = None
                try:
                    raw_filename = file.filename
                    upload_key = _normalize_upload_key(raw_filename)
                    source_path = upload_key if "/" in upload_key else None
                    file.filename = _sanitize_filename(raw_filename)

                    file_ext = Path(file.filename).suffix.lower()
                    if file_ext not in settings.allowed_extensions_list:
                        return {
                            "success": False,
                            "filename": file.filename,
                            "source_path": source_path,
                            "error": f"Unsupported file type: {file_ext}",
                        }

                    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
                    upload_dir.mkdir(parents=True, exist_ok=True)

                    file_id = uuid.uuid4()
                    file_path = upload_dir / f"{file_id}{file_ext}"
                    file_size, file_sha256 = await save_upload_file_with_hash(file, file_path, max_bytes=settings.MAX_FILE_SIZE)

                    return {
                        "success": True,
                        "filename": file.filename,
                        "source_path": source_path,
                        "upload_key": upload_key,
                        "file_ext": file_ext,
                        "file_id": file_id,
                        "file_path": str(file_path),
                        "file_size": int(file_size or 0),
                        "file_sha256": str(file_sha256 or "").strip().lower() or None,
                    }
                except HTTPException as exc:
                    return {
                        "success": False,
                        "filename": str(getattr(file, "filename", "") or "unknown"),
                        "source_path": source_path,
                        "error": str(getattr(exc, "detail", "") or str(exc) or "upload_failed"),
                    }
                except Exception as exc:  # noqa: BLE001
                    return {
                        "success": False,
                        "filename": str(getattr(file, "filename", "") or "unknown"),
                        "source_path": source_path,
                        "error": str(exc)[:200],
                    }

        save_tasks = [_save_upload_only(file) for file in files]
        save_results = await asyncio.gather(*save_tasks, return_exceptions=True)

        staged_results: list[dict[str, Any]] = []
        for r in save_results:
            if isinstance(r, Exception):
                staged_results.append({"success": False, "filename": "unknown", "source_path": None, "error": str(r)[:200]})
            elif isinstance(r, dict):
                staged_results.append(r)
            else:
                staged_results.append({"success": False, "filename": "unknown", "source_path": None, "error": "upload_failed"})

        staged_successful = [r for r in staged_results if r.get("success")]
        staged_failed = [r for r in staged_results if not r.get("success")]

        # Tenant quotas: enforce storage/docs limits using actual staged sizes (and clean up staged files on failure).
        try:
            total_bytes = sum(int(r.get("file_size") or 0) for r in staged_successful)
            enforce_tenant_upload_quotas(
                db,
                tenant_id=tenant_id,
                additional_docs=int(len(staged_successful)),
                additional_bytes=int(total_bytes),
            )
        except HTTPException:
            for r in staged_successful:
                with contextlib.suppress(OSError):
                    Path(str(r.get("file_path") or "")).unlink(missing_ok=True)
            raise

        # Precheck-first: run a best-effort precheck scan on a staging folder with the uploaded files.
        # This lets us apply suggested ingestion policy before creating documents/queueing jobs.
        if staged_successful:
            scan_run: DBDatasetPrecheckScanRun | None = None
            staging_root: Path | None = None
            try:
                upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
                staging_root = (upload_dir / ".tmp" / "precheck_ingest" / uuid.uuid4().hex).resolve(strict=False)
                staging_root.mkdir(parents=True, exist_ok=True)
                staging_root_resolved = staging_root.resolve(strict=False)

                def _safe_staging_relpath(item: dict, *, idx: int) -> Path:
                    raw = str(item.get("upload_key") or item.get("filename") or f"FILE_{idx:06d}").strip()
                    parts = _normalize_upload_path_parts(raw)
                    if not parts:
                        parts = [str(item.get("filename") or f"FILE_{idx:06d}")]

                    safe_parts: list[str] = []
                    for seg in parts:
                        seg0 = str(seg or "").replace("\\", "/").strip()
                        seg0 = seg0.rsplit("/", 1)[-1]
                        seg0 = "".join(ch for ch in seg0 if ord(ch) >= 32 and ch != "\x7f")
                        if not seg0 or seg0 in {".", ".."}:
                            seg0 = "item"
                        if len(seg0) > 120:
                            seg0 = seg0[:120]
                        safe_parts.append(seg0)

                    file_ext0 = str(item.get("file_ext") or "").strip().lower()
                    if safe_parts:
                        last = safe_parts[-1]
                        if file_ext0 and not last.lower().endswith(file_ext0):
                            safe_parts[-1] = f"{last}{file_ext0}"

                    rel = Path(*safe_parts) if safe_parts else Path(f"FILE_{idx:06d}{file_ext0}")
                    # Defensive: strip any accidental traversal.
                    rel = Path(*[p for p in rel.parts if p not in {"", ".."}])
                    return rel

                linked_any = False
                for idx, item in enumerate(staged_successful):
                    src_raw = str(item.get("file_path") or "").strip()
                    if not src_raw:
                        continue
                    src = Path(src_raw).resolve(strict=False)
                    if not src.exists() or not src.is_file():
                        continue

                    rel = _safe_staging_relpath(item, idx=idx)
                    dst = (staging_root / rel).resolve(strict=False)
                    try:
                        dst.relative_to(staging_root_resolved)
                    except Exception:
                        ext0 = str(item.get("file_ext") or "").strip().lower()
                        dst = (staging_root / f"FILE_{idx:06d}{ext0}").resolve(strict=False)

                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if dst.exists():
                        fid = item.get("file_id")
                        suffix = getattr(fid, "hex", None) if fid is not None else uuid.uuid4().hex
                        dst = dst.with_name(f"{dst.stem}.{suffix}{dst.suffix}")
                    try:
                        os.link(src, dst)
                        linked_any = True
                    except Exception:
                        try:
                            shutil.copy2(src, dst)
                            linked_any = True
                        except Exception:
                            continue

                if linked_any:
                    scan_run = DBDatasetPrecheckScanRun(
                        tenant_id=tenant_id,
                        dataset_id=dataset.id,
                        requested_by=account_id,
                        kind="path",
                        status="pending",
                        progress=0,
                        config={
                            "root_path": str(staging_root),
                            "max_files": int(len(staged_successful)),
                            "enable_pdf_quality": True,
                            "enable_text_extract": True,
                            "enable_pii": False,
                            "enable_secrets": False,
                            "compute_file_hash": False,
                            "redact_paths": False,
                            "enable_sampling": False,
                            "sample_size": 0,
                            "enable_near_dup": False,
                            # Internal-only flag: allow scans under UPLOAD_DIR without LOCAL_SCAN_ENABLED.
                            "internal_allow_upload_scan": True,
                        },
                        summary={},
                        artifacts={},
                    )
                    db.add(scan_run)
                    db.commit()
                    db.refresh(scan_run)

                    tid0 = tenant_id
                    dsid0 = dataset.id
                    rid0 = scan_run.id

                    def _run_scan_job() -> None:
                        db2 = SessionLocal()
                        try:
                            run_dataset_precheck_scan(db2, tenant_id=tid0, dataset_id=dsid0, scan_run_id=rid0)
                        except Exception as exc:  # noqa: BLE001
                            # Mirror worker behavior: mark failed instead of leaving "running".
                            try:
                                row = (
                                    db2.query(DBDatasetPrecheckScanRun)
                                    .filter(
                                        DBDatasetPrecheckScanRun.id == rid0,
                                        DBDatasetPrecheckScanRun.tenant_id == tid0,
                                        DBDatasetPrecheckScanRun.dataset_id == dsid0,
                                    )
                                    .first()
                                )
                                if row is not None:
                                    row.status = 'failed'
                                    row.error_message = str(exc)[:200]
                                    row.finished_at = datetime.now(UTC)
                                    db2.commit()
                            except Exception as mark_exc:  # noqa: BLE001
                                logger.warning('Failed to mark precheck scan run as failed: %s', str(mark_exc)[:200])
                            raise
                        finally:
                            db2.close()

                    try:
                        await asyncio.to_thread(_run_scan_job)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Precheck-first scan failed: %s", str(exc)[:200])
                    finally:
                        with contextlib.suppress(Exception):
                            shutil.rmtree(staging_root)

                    with contextlib.suppress(Exception):
                        db.refresh(scan_run)

                    try:
                        apply_ingestion_policy_suggestion(
                            db,
                            dataset=dataset,
                            scan_run=scan_run,
                            tenant_id=tenant_id,
                            replace=False,
                        )
                    except HTTPException as exc:
                        # 409 means policy already exists; keep it.
                        if int(getattr(exc, "status_code", 0) or 0) != 409:
                            logger.warning("Precheck-first policy apply failed: %s", str(getattr(exc, "detail", exc))[:200])
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Precheck-first policy apply failed: %s", str(exc)[:200])

                    with contextlib.suppress(Exception):
                        db.refresh(dataset)
                    dataset_meta2 = (getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}
                    policy = parse_ingestion_policy_from_metadata(dataset_meta2 if isinstance(dataset_meta2, dict) else {})  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                logger.warning("Precheck-first ingest failed; continuing without precheck: %s", str(exc)[:200])
            finally:
                if staging_root is not None:
                    with contextlib.suppress(Exception):
                        shutil.rmtree(staging_root)

        # Now proceed with normal ingestion using (potentially) updated policy.
        governance_profile_cache: dict[str, Any] = {}

        async def _finalize_staged_file(staged: dict) -> dict:
            """Create DB record + enqueue processing for an already-staged file on disk."""
            async with semaphore:
                source_path = staged.get("source_path")
                upload_key = staged.get("upload_key")
                filename0 = str(staged.get("filename") or "unknown")
                try:
                    file_ext = str(staged.get("file_ext") or "").strip().lower() or Path(filename0).suffix.lower()
                    file_id = staged.get("file_id")
                    file_path = Path(str(staged.get("file_path") or ""))
                    file_size = int(staged.get("file_size") or 0)
                    file_sha256 = staged.get("file_sha256")

                    if not file_ext:
                        raise HTTPException(status_code=400, detail="Missing file extension")
                    if file_ext not in settings.allowed_extensions_list:
                        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_ext}")

                    pipeline_options = _to_pipeline_options(pipeline=pipeline_parsed, overrides=pipeline_overrides)

                    matched_rule = match_ingestion_rule(policy, filename=str(upload_key or filename0), file_ext=file_ext)
                    ingestion_meta: dict[str, Any] | None = None
                    parser_backend_choice: str = parser_backend_base
                    chunk_strategy_choice: str = chunk_strategy_base
                    preprocess_steps: list[dict] = []
                    policy_patch = PipelineOptions()

                    if matched_rule is not None:
                        req_pb0 = (parser_backend_choice or "").strip().lower()
                        if req_pb0 in {"", "auto", default_pb} and matched_rule.parser_backend:
                            parser_backend_choice = str(matched_rule.parser_backend)

                        req_cs0 = (chunk_strategy_choice or "").strip().lower()
                        if req_cs0 in {"", default_cs} and matched_rule.chunk_strategy:
                            chunk_strategy_choice = str(matched_rule.chunk_strategy)

                        pp = getattr(matched_rule, "preprocess", None)
                        steps = getattr(pp, "steps", None) if pp is not None and bool(getattr(pp, "enabled", True)) else None
                        if isinstance(steps, list) and steps:
                            preprocess_steps = [
                                {
                                    "id": str(getattr(s, "id", "") or "").strip(),
                                    "params": dict(getattr(s, "params", {}) or {}),
                                }
                                for s in steps
                            ]

                        patch_dict: dict[str, Any] = {}
                        profile_ref = getattr(matched_rule, "governance_profile_ref", None)
                        if isinstance(profile_ref, str) and profile_ref.strip():
                            ref = profile_ref.strip()
                            cached = governance_profile_cache.get(ref)
                            if cached is None:
                                try:
                                    cached = resolve_governance_profile_ref(db=db, tenant_id=tenant_id, profile_ref=ref)
                                except ValueError as exc:
                                    raise HTTPException(status_code=400, detail=f"Invalid governance_profile_ref: {str(exc)[:120]}") from exc
                                governance_profile_cache[ref] = cached
                            patch_dict.update(dict(getattr(cached, "pipeline_patch", None) or {}))
                            rules = getattr(cached, "regex_rules", None) or []
                            if rules:
                                patch_dict["governance_regex_rules"] = list(rules)

                        patch_dict.update(dict(getattr(matched_rule, "pipeline_patch", None) or {}))
                        if patch_dict:
                            policy_patch = PipelineOptions(**patch_dict)

                        ingestion_meta = {
                            "version": str(getattr(policy, "version", "1") if policy is not None else "1"),
                            "rule": {"id": matched_rule.id, "name": matched_rule.name},
                            "preprocess": {"enabled": bool(preprocess_steps), "steps": preprocess_steps},
                            "governance_profile_ref": (profile_ref.strip() if isinstance(profile_ref, str) and profile_ref.strip() else None),
                        }

                    pipeline_options = merge_pipeline_options(policy_patch, pipeline_options)

                    requested_parser_backend = (parser_backend_choice or "").strip().lower()
                    if file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
                        resolved_parser_backend = "auto"
                    else:
                        resolved_parser_backend = parser_factory.resolve_backend(file_ext, parser_backend_choice)
                    resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy_choice)

                    pipeline_effective = resolve_pipeline_effective(
                        dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}) if dataset else {},
                        document_metadata={},
                        request_overrides=pipeline_options,
                    )
                    if resolved_chunk_strategy not in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
                        _validate_chunk_params(pipeline_effective.chunk_size, pipeline_effective.chunk_overlap)

                    doc_metadata = {
                        "parser_backend": resolved_parser_backend,
                        "parser_backend_requested": (parser_backend or "").lower(),
                        "chunk_strategy": resolved_chunk_strategy,
                        "chunk_strategy_requested": (chunk_strategy or "").lower(),
                    }
                    if source_path:
                        doc_metadata["source_path"] = source_path
                    if isinstance(file_sha256, str) and file_sha256:
                        doc_metadata["file_sha256"] = file_sha256
                    upsert_pipeline_metadata(doc_metadata, options=pipeline_options)
                    if ingestion_meta:
                        doc_metadata["ingestion"] = ingestion_meta

                    user_patch = None
                    if isinstance(upload_key, str) and upload_key:
                        user_patch = user_meta_by_key.get(upload_key)
                        if user_patch is None and "/" in upload_key:
                            user_patch = user_meta_by_key.get(upload_key.rsplit("/", 1)[-1])
                    if user_patch is None:
                        user_patch = user_meta_by_key.get(filename0)
                    if isinstance(user_patch, dict) and user_patch:
                        doc_metadata["user"] = _apply_user_metadata_patch(current={}, patch=user_patch, replace=True)
                    pipeline_hash = _compute_pipeline_hash(doc_metadata)
                    doc_metadata["pipeline_hash"] = pipeline_hash
                    doc_metadata.setdefault("active_pipeline_hash", pipeline_hash)
                    doc_metadata.setdefault("active_pipeline_ready", False)

                    if bool(getattr(settings, "UPLOAD_DEDUP_ENABLED", False)) and isinstance(file_sha256, str) and file_sha256:
                        dup = _find_duplicate_document(
                            db,
                            tenant_id=tenant_id,
                            dataset_id=getattr(dataset, "id", None) if dataset is not None else None,
                            file_sha256=file_sha256,
                            pipeline_hash=pipeline_hash,
                        )
                        if dup is not None and str(getattr(dup, "status", "") or "").lower() not in {"failed"}:
                            with contextlib.suppress(OSError):
                                file_path.unlink(missing_ok=True)
                            return {
                                "success": True,
                                "filename": filename0,
                                "source_path": source_path,
                                "document_id": str(getattr(dup, "id", "")),
                                "document": dup,
                            }

                        dup_any = _find_duplicate_document_by_sha(
                            db,
                            tenant_id=tenant_id,
                            dataset_id=getattr(dataset, "id", None) if dataset is not None else None,
                            file_sha256=file_sha256,
                        )
                        if dup_any is not None:
                            status0 = str(getattr(dup_any, "status", "") or "").lower()
                            if status0 in {"pending", "processing"}:
                                raise HTTPException(status_code=409, detail=DUPLICATE_DOCUMENT_PROCESSING_DETAIL)

                            with contextlib.suppress(OSError):
                                file_path.unlink(missing_ok=True)

                            meta_any = dict(getattr(dup_any, "doc_metadata", None) or {})
                            meta_any["parser_backend"] = resolved_parser_backend
                            meta_any["parser_backend_requested"] = (parser_backend or "").lower()
                            meta_any["chunk_strategy"] = resolved_chunk_strategy
                            meta_any["chunk_strategy_requested"] = (chunk_strategy or "").lower()
                            if source_path and not meta_any.get("source_path"):
                                meta_any["source_path"] = source_path
                            meta_any["file_sha256"] = str(file_sha256).strip().lower()
                            upsert_pipeline_metadata(meta_any, options=pipeline_options)
                            if ingestion_meta:
                                meta_any["ingestion"] = ingestion_meta

                            if isinstance(user_patch, dict) and user_patch:
                                current_user = meta_any.get("user") if isinstance(meta_any.get("user"), dict) else {}
                                meta_any["user"] = _apply_user_metadata_patch(current=current_user, patch=user_patch, replace=False)

                            if "active_pipeline_hash" not in meta_any:
                                meta_any["active_pipeline_hash"] = str(meta_any.get("pipeline_hash") or "").strip() or None
                            if "active_pipeline_ready" not in meta_any:
                                meta_any["active_pipeline_ready"] = bool(status0 == "completed")

                            dup_any.doc_metadata = meta_any
                            db.commit()
                            db.refresh(dup_any)

                            await retry_document_processing(
                                document_id=dup_any.id,
                                background_tasks=background_tasks,
                                force=True,
                                skip_if_unchanged=True,
                                tenant_id=tenant_id,
                                account_id=account_id,
                                db=db,
                            )
                            db.refresh(dup_any)
                            return {
                                "success": True,
                                "filename": filename0,
                                "source_path": source_path,
                                "document_id": str(getattr(dup_any, "id", "")),
                                "document": dup_any,
                            }

                    db_document = DBDocument(
                        id=file_id,
                        tenant_id=tenant_id,
                        dataset_id=dataset.id if dataset else None,
                        filename=filename0,
                        file_type=file_ext.lstrip("."),
                        file_size=file_size,
                        file_path=str(file_path),
                        owner_id=account_id,
                        access_mode=None,
                        status="pending",
                        processing_progress=0,
                        doc_metadata=doc_metadata,
                    )

                    db.add(db_document)
                    db.commit()
                    db.refresh(db_document)

                    job_id = f"doc:{tenant_id}:{file_id}:{pipeline_hash}"
                    task_id = await enqueue_document_processing(
                        tenant_id=tenant_id,
                        document_id=file_id,
                        requested_by=account_id,
                        job_id=job_id,
                    )
                    if task_id:
                        meta = dict(db_document.doc_metadata or {})
                        meta["task_id"] = task_id
                        db_document.doc_metadata = meta
                        db.commit()
                        db.refresh(db_document)
                    else:
                        background_tasks.add_task(
                            document_processor.process_document,
                            file_path,
                            file_id,
                            tenant_id,
                            resolved_parser_backend,
                            resolved_chunk_strategy,
                        )

                    return {
                        "success": True,
                        "filename": filename0,
                        "source_path": source_path,
                        "document_id": str(file_id),
                        "document": db_document,
                    }
                except Exception as exc:  # noqa: BLE001
                    logger.error("Error processing staged file %s: %s", filename0, str(exc)[:200])
                    return {
                        "success": False,
                        "filename": filename0,
                        "source_path": source_path,
                        "error": str(exc)[:200],
                    }

        finalize_tasks = [_finalize_staged_file(item) for item in staged_successful]
        finalize_results = await asyncio.gather(*finalize_tasks, return_exceptions=True)

        processed: list[dict[str, Any]] = []
        for r in finalize_results:
            if isinstance(r, Exception):
                processed.append({"success": False, "filename": "unknown", "source_path": None, "error": str(r)[:200]})
            elif isinstance(r, dict):
                processed.append(r)
            else:
                processed.append({"success": False, "filename": "unknown", "source_path": None, "error": "upload_failed"})

        successful = [r for r in processed if r.get("success")]
        failed = staged_failed + [r for r in processed if not r.get("success")]

        if ingestion_run is not None:
            for r in successful:
                doc = r.get("document")
                if doc is None:
                    continue
                try:
                    meta0 = dict(getattr(doc, "doc_metadata", None) or {})
                    meta0["last_ingestion_run_id"] = str(ingestion_run.id)
                    meta0["last_ingestion_kind"] = "upload_batch"
                    doc.doc_metadata = meta0
                    db.commit()
                    db.refresh(doc)
                except Exception:
                    meta0 = dict(getattr(doc, "doc_metadata", None) or {})

                with contextlib.suppress(Exception):
                    IngestionRunService.add_document(
                        db,
                        tenant_id=tenant_id,
                        run_id=ingestion_run.id,
                        document_id=doc.id,
                        source_ref=(r.get("source_path") or getattr(doc, "filename", None)),
                        initial_status=str(getattr(doc, "status", "") or "created"),
                        doc_meta=meta0 if isinstance(meta0, dict) else None,
                    )

        return {
            "total": len(files),
            "successful_count": len(successful),
            "failed_count": len(failed),
            "successful": [
                {
                    "document_id": r["document_id"],
                    "filename": r["filename"],
                    "source_path": r.get("source_path"),
                    "status": r["document"].status,
                }
                for r in successful
            ],
            "failed": [
                {
                    "filename": r.get("filename") or "unknown",
                    "source_path": r.get("source_path"),
                    "error": r.get("error") or "upload_failed",
                }
                for r in failed
            ],
        }

    governance_profile_cache: dict[str, Any] = {}
    
    async def process_single_file(file: UploadFile) -> dict:
        """Handle upload for a single file."""
        async with semaphore:
            source_path: str | None = None
            upload_key: str | None = None
            try:
                # Filename + optional directory-preserving upload hint (folder uploads).
                raw_filename = file.filename
                upload_key = _normalize_upload_key(raw_filename)
                source_path = upload_key if "/" in upload_key else None
                file.filename = _sanitize_filename(raw_filename)
                
                # Validate file type.
                file_ext = Path(file.filename).suffix.lower()
                if file_ext not in settings.allowed_extensions_list:
                    return {
                        "success": False,
                        "filename": file.filename,
                        "source_path": source_path,
                        "error": f"Unsupported file type: {file_ext}"
                    }
                
                pipeline_options = _to_pipeline_options(pipeline=pipeline_parsed, overrides=pipeline_overrides)

                # Ingestion policy overrides (per file).
                matched_rule = match_ingestion_rule(policy, filename=upload_key or file.filename, file_ext=file_ext)
                ingestion_meta: dict[str, Any] | None = None
                parser_backend_choice: str = parser_backend_base
                chunk_strategy_choice: str = chunk_strategy_base
                preprocess_steps: list[dict] = []
                policy_patch = PipelineOptions()

                if matched_rule is not None:
                    req_pb = (parser_backend_choice or "").strip().lower()
                    if req_pb in {"", "auto", default_pb} and matched_rule.parser_backend:
                        parser_backend_choice = str(matched_rule.parser_backend)

                    req_cs = (chunk_strategy_choice or "").strip().lower()
                    if req_cs in {"", default_cs} and matched_rule.chunk_strategy:
                        chunk_strategy_choice = str(matched_rule.chunk_strategy)

                    pp = getattr(matched_rule, "preprocess", None)
                    steps = getattr(pp, "steps", None) if pp is not None and bool(getattr(pp, "enabled", True)) else None
                    if isinstance(steps, list) and steps:
                        preprocess_steps = [
                            {
                                "id": str(getattr(s, "id", "") or "").strip(),
                                "params": dict(getattr(s, "params", {}) or {}),
                            }
                            for s in steps
                        ]

                    patch_dict: dict[str, Any] = {}
                    profile_ref = getattr(matched_rule, "governance_profile_ref", None)
                    if isinstance(profile_ref, str) and profile_ref.strip():
                        ref = profile_ref.strip()
                        cached = governance_profile_cache.get(ref)
                        if cached is None:
                            try:
                                cached = resolve_governance_profile_ref(db=db, tenant_id=tenant_id, profile_ref=ref)
                            except ValueError as exc:
                                raise HTTPException(status_code=400, detail=f"Invalid governance_profile_ref: {str(exc)[:120]}") from exc
                            governance_profile_cache[ref] = cached
                        patch_dict.update(dict(getattr(cached, "pipeline_patch", None) or {}))
                        rules = getattr(cached, "regex_rules", None) or []
                        if rules:
                            patch_dict["governance_regex_rules"] = list(rules)

                    patch_dict.update(dict(getattr(matched_rule, "pipeline_patch", None) or {}))
                    if patch_dict:
                        policy_patch = PipelineOptions(**patch_dict)

                    ingestion_meta = {
                        "version": str(getattr(policy, "version", "1") if policy is not None else "1"),
                        "rule": {"id": matched_rule.id, "name": matched_rule.name},
                        "preprocess": {"enabled": bool(preprocess_steps), "steps": preprocess_steps},
                        "governance_profile_ref": (profile_ref.strip() if isinstance(profile_ref, str) and profile_ref.strip() else None),
                    }

                pipeline_options = merge_pipeline_options(policy_patch, pipeline_options)

                # Resolve backend/strategy after policy application.
                requested_parser_backend = (parser_backend_choice or "").strip().lower()
                if file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
                    resolved_parser_backend = "auto"
                else:
                    resolved_parser_backend = parser_factory.resolve_backend(file_ext, parser_backend_choice)
                resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy_choice)

                pipeline_effective = resolve_pipeline_effective(
                    dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}) if dataset else {},
                    document_metadata={},
                    request_overrides=pipeline_options,
                )
                if resolved_chunk_strategy not in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
                    _validate_chunk_params(pipeline_effective.chunk_size, pipeline_effective.chunk_overlap)
                
                # Permission check (already done outside semaphore).
                # Save file.
                upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
                upload_dir.mkdir(parents=True, exist_ok=True)
                
                file_id = uuid.uuid4()
                file_path = upload_dir / f"{file_id}{file_ext}"
                
                file_size, file_sha256 = await save_upload_file_with_hash(file, file_path, max_bytes=settings.MAX_FILE_SIZE)

                # Tenant quotas: enforce docs/storage limits per successful upload and clean up the staged file.
                try:
                    enforce_tenant_upload_quotas(
                        db,
                        tenant_id=tenant_id,
                        additional_docs=1,
                        additional_bytes=int(file_size or 0),
                    )
                except HTTPException as exc:
                    with contextlib.suppress(OSError):
                        file_path.unlink(missing_ok=True)
                    return {
                        "success": False,
                        "filename": file.filename,
                        "source_path": source_path,
                        "error": str(getattr(exc, "detail", "") or "tenant_quota_exceeded"),
                    }
                
                # Create database record.
                doc_metadata = {
                    "parser_backend": resolved_parser_backend,
                    "parser_backend_requested": (parser_backend or "").lower(),
                    "chunk_strategy": resolved_chunk_strategy,
                    "chunk_strategy_requested": (chunk_strategy or "").lower(),
                }
                if source_path:
                    doc_metadata["source_path"] = source_path
                if isinstance(file_sha256, str) and file_sha256:
                    doc_metadata["file_sha256"] = file_sha256
                upsert_pipeline_metadata(doc_metadata, options=pipeline_options)
                if ingestion_meta:
                    doc_metadata["ingestion"] = ingestion_meta

                user_patch = None
                if isinstance(upload_key, str) and upload_key:
                    user_patch = user_meta_by_key.get(upload_key)
                    # Optional fallback: allow mapping by basename for non-folder uploads.
                    if user_patch is None and "/" in upload_key:
                        user_patch = user_meta_by_key.get(upload_key.rsplit("/", 1)[-1])
                if user_patch is None:
                    user_patch = user_meta_by_key.get(file.filename)
                if isinstance(user_patch, dict) and user_patch:
                    doc_metadata["user"] = _apply_user_metadata_patch(current={}, patch=user_patch, replace=True)
                pipeline_hash = _compute_pipeline_hash(doc_metadata)
                doc_metadata["pipeline_hash"] = pipeline_hash
                # Versioning: the first processed pipeline is the active one by default.
                doc_metadata.setdefault("active_pipeline_hash", pipeline_hash)
                doc_metadata.setdefault("active_pipeline_ready", False)

                # Optional: upload deduplication (same file_sha256 + pipeline_hash within the dataset).
                if bool(getattr(settings, "UPLOAD_DEDUP_ENABLED", False)) and isinstance(file_sha256, str) and file_sha256:
                    dup = _find_duplicate_document(
                        db,
                        tenant_id=tenant_id,
                        dataset_id=getattr(dataset, "id", None) if dataset is not None else None,
                        file_sha256=file_sha256,
                        pipeline_hash=pipeline_hash,
                    )
                    if dup is not None and str(getattr(dup, "status", "") or "").lower() not in {"failed"}:
                        with contextlib.suppress(OSError):
                            file_path.unlink(missing_ok=True)
                        return {
                            "success": True,
                            "filename": file.filename,
                            "source_path": source_path,
                            "document_id": str(getattr(dup, "id", "")),
                            "document": dup,
                        }

                    # Cross-version dedup: reuse existing document_id for the same file_sha256 by creating a new version.
                    dup_any = _find_duplicate_document_by_sha(
                        db,
                        tenant_id=tenant_id,
                        dataset_id=getattr(dataset, "id", None) if dataset is not None else None,
                        file_sha256=file_sha256,
                    )
                    if dup_any is not None:
                        status0 = str(getattr(dup_any, "status", "") or "").lower()
                        if status0 in {"pending", "processing"}:
                            raise HTTPException(status_code=409, detail=DUPLICATE_DOCUMENT_PROCESSING_DETAIL)

                        with contextlib.suppress(OSError):
                            file_path.unlink(missing_ok=True)

                        meta_any = dict(getattr(dup_any, "doc_metadata", None) or {})
                        meta_any["parser_backend"] = resolved_parser_backend
                        meta_any["parser_backend_requested"] = (parser_backend or "").lower()
                        meta_any["chunk_strategy"] = resolved_chunk_strategy
                        meta_any["chunk_strategy_requested"] = (chunk_strategy or "").lower()
                        if source_path and not meta_any.get("source_path"):
                            meta_any["source_path"] = source_path
                        meta_any["file_sha256"] = str(file_sha256).strip().lower()
                        upsert_pipeline_metadata(meta_any, options=pipeline_options)
                        if ingestion_meta:
                            meta_any["ingestion"] = ingestion_meta

                        if isinstance(user_patch, dict) and user_patch:
                            current_user = meta_any.get("user") if isinstance(meta_any.get("user"), dict) else {}
                            meta_any["user"] = _apply_user_metadata_patch(current=current_user, patch=user_patch, replace=False)

                        if "active_pipeline_hash" not in meta_any:
                            meta_any["active_pipeline_hash"] = str(meta_any.get("pipeline_hash") or "").strip() or None
                        if "active_pipeline_ready" not in meta_any:
                            meta_any["active_pipeline_ready"] = bool(status0 == "completed")

                        dup_any.doc_metadata = meta_any
                        db.commit()
                        db.refresh(dup_any)

                        await retry_document_processing(
                            document_id=dup_any.id,
                            background_tasks=background_tasks,
                            force=True,
                            skip_if_unchanged=True,
                            tenant_id=tenant_id,
                            account_id=account_id,
                            db=db,
                        )
                        db.refresh(dup_any)
                        return {
                            "success": True,
                            "filename": file.filename,
                            "source_path": source_path,
                            "document_id": str(getattr(dup_any, "id", "")),
                            "document": dup_any,
                        }
                
                db_document = DBDocument(
                    id=file_id,
                    tenant_id=tenant_id,
                    dataset_id=dataset.id if dataset else None,
                    filename=file.filename,
                    file_type=file_ext.lstrip('.'),
                    file_size=file_size,
                    file_path=str(file_path),
                    owner_id=account_id,
                    access_mode=None,  # inherit dataset permission by default
                    status='pending',
                    processing_progress=0,
                    doc_metadata=doc_metadata,
                )
                
                db.add(db_document)
                db.commit()
                db.refresh(db_document)
                
                # Process document in background: enqueue if available (fallback to BackgroundTasks).
                job_id = f"doc:{tenant_id}:{file_id}:{pipeline_hash}"
                task_id = await enqueue_document_processing(
                    tenant_id=tenant_id,
                    document_id=file_id,
                    requested_by=account_id,
                    job_id=job_id,
                )
                if task_id:
                    meta = dict(db_document.doc_metadata or {})
                    meta["task_id"] = task_id
                    db_document.doc_metadata = meta
                    db.commit()
                    db.refresh(db_document)
                else:
                    background_tasks.add_task(
                        document_processor.process_document,
                        file_path,
                        file_id,
                        tenant_id,
                        resolved_parser_backend,
                        resolved_chunk_strategy,
                    )
                
                return {
                    "success": True,
                    "filename": file.filename,
                    "source_path": source_path,
                    "document_id": str(file_id),
                    "document": db_document
                }
                
            except Exception as e:
                logger.error(f"Error processing file {file.filename}: {str(e)}")
                return {
                    "success": False,
                    "filename": file.filename,
                    "source_path": source_path,
                    "error": str(e)
                }
    
    # Process all files concurrently.
    tasks = [process_single_file(file) for file in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Handle error results.
    processed_results = []
    for result in results:
        if isinstance(result, Exception):
            processed_results.append({
                "success": False,
                "filename": "unknown",
                "source_path": None,
                "error": str(result)
            })
        else:
            processed_results.append(result)
    
    successful = [r for r in processed_results if r.get("success")]
    failed = [r for r in processed_results if not r.get("success")]

    # Best-effort: attach successful documents to the batch ingestion run.
    if ingestion_run is not None:
        for r in successful:
            doc = r.get("document")
            if doc is None:
                continue
            try:
                meta0 = dict(getattr(doc, "doc_metadata", None) or {})
                meta0["last_ingestion_run_id"] = str(ingestion_run.id)
                meta0["last_ingestion_kind"] = "upload_batch"
                doc.doc_metadata = meta0
                db.commit()
                db.refresh(doc)
            except Exception:
                meta0 = dict(getattr(doc, "doc_metadata", None) or {})

            with contextlib.suppress(Exception):
                IngestionRunService.add_document(
                    db,
                    tenant_id=tenant_id,
                    run_id=ingestion_run.id,
                    document_id=doc.id,
                    source_ref=(r.get("source_path") or getattr(doc, "filename", None)),
                    initial_status=str(getattr(doc, "status", "") or "created"),
                    doc_meta=meta0 if isinstance(meta0, dict) else None,
                )
    
    return {
        "total": len(files),
        "successful_count": len(successful),
        "failed_count": len(failed),
        "successful": [
            {
                "document_id": r["document_id"],
                "filename": r["filename"],
                "source_path": r.get("source_path"),
                "status": r["document"].status
            }
            for r in successful
        ],
        "failed": [
            {
                "filename": r["filename"],
                "source_path": r.get("source_path"),
                "error": r.get("error", "Unknown error")
            }
            for r in failed
        ]
    }

def _resolve_active_doc_pipeline_key(document_id: UUID, doc_metadata: dict) -> str:
    active_hash = str((doc_metadata or {}).get("active_pipeline_hash") or (doc_metadata or {}).get("pipeline_hash") or "").strip()
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
    strictness = str(getattr(settings, "INDEX_CONSISTENCY_STRICTNESS", "off") or "off").strip().lower()
    if strictness not in {"off", "warn", "strict"}:
        strictness = "off"
    enabled = bool(getattr(settings, "INDEX_CONSISTENCY_ENABLED", False))
    patch_strict = bool(getattr(settings, "INDEX_CONSISTENCY_PATCH_CHUNK_STRICT", False))
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


def _build_chunk_index_operation_result(
    *,
    operation: str,
    strictness: str,
    vector: dict[str, Any],
    bm25: dict[str, Any],
    kg: dict[str, Any] | None = None,
    drift_markers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    vector_status = str((vector or {}).get("status") or "skipped").strip().lower()
    bm25_status = str((bm25 or {}).get("status") or "skipped").strip().lower()
    kg_status = str((kg or {}).get("status") or "skipped").strip().lower() if isinstance(kg, dict) else "skipped"
    success = all(st in {"ok", "skipped"} for st in (vector_status, bm25_status, kg_status))
    return {
        "schema": "mimirq.index_operation_result.v1",
        "operation": str(operation or "").strip()[:80] or CHUNK_PATCH_OPERATION,
        "strictness": str(strictness or "off").strip().lower(),
        "success": bool(success),
        "vector": dict(vector or {}),
        "bm25": dict(bm25 or {}),
        "kg": (dict(kg or {}) if isinstance(kg, dict) else None),
        "drift_markers": [dict(m) for m in (drift_markers or []) if isinstance(m, dict)][:20],
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
    if not bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
        return None

    try:
        from app.tasks.queue import enqueue_rebuild_indexes

        return await enqueue_rebuild_indexes(
            tenant_id=tenant_id,
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

    emit_drift_markers = bool(getattr(settings, "INDEX_CONSISTENCY_EMIT_DRIFT_MARKERS", True))
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
    if drift_markers:
        reconcile_task_id = await _enqueue_index_drift_reconcile(
            tenant_id=tenant_id,
            document_id=document.id,
            requested_by=account_id,
        )
        for marker in drift_markers:
            with contextlib.suppress(Exception):
                record_index_drift_item(
                    db=db,
                    dataset_id=getattr(document, "dataset_id", None),
                    marker=marker,
                    reconcile_task_id=reconcile_task_id,
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


async def _delete_document_lifecycle(
    *,
    document_id: uuid.UUID,
    tenant_id: UUID,
    account_id: str,
    db: Session,
    enforce_permissions: bool = True,
    enforce_membership: bool = True,
) -> None:
    """
    Internal document delete lifecycle.

    - `enforce_permissions=True` matches the public endpoint behavior.
    - `enforce_permissions=False` is intended for admin-only lifecycle operations (e.g. dataset purge),
      where the caller already performed the necessary RBAC checks.
    """
    if bool(enforce_membership):
        DatasetService.ensure_member(db, tenant_id, account_id)
    document = (
        db.query(DBDocument)
        .filter(
            DBDocument.id == document_id,
            DBDocument.tenant_id == tenant_id,
        )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    if enforce_permissions and document.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    # If the document is still being processed, mark it cancelled first so any
    # running worker can observe it and stop as soon as possible.
    if str(document.status or "").lower() in {"pending", "processing"}:
        doc_meta = dict(document.doc_metadata or {})
        doc_meta["cancel_requested"] = True
        document.doc_metadata = doc_meta
        document.status = "cancelled"
        document.processing_progress = 0
        document.current_stage = "cancelled"
        document.error_message = "cancelled"
        db.commit()
        db.refresh(document)

    # Best-effort: abort any queued/running jobs for this document before deleting.
    doc_meta = document.doc_metadata or {}
    task_ids: list[str] = []
    for key in ("task_id", "kg_task_id"):
        v = doc_meta.get(key) if isinstance(doc_meta, dict) else None
        if isinstance(v, str) and v.strip():
            task_ids.append(v.strip())

    if bool(getattr(settings, "TASK_QUEUE_ENABLED", False)) and task_ids:
        try:
            from arq.jobs import Job

            from app.tasks.queue import get_queue

            q = await get_queue()
            if q is not None:
                queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
                for task_id in task_ids:
                    job = Job(task_id, q, _queue_name=queue_name)
                    with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                        await job.abort(timeout=0.2)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to abort document tasks before delete: doc=%s tasks=%s err=%s",
                document_id,
                task_ids,
                str(exc)[:200],
            )

    # 1. Delete images in MinIO (if enabled).
    if settings.MINIO_ENABLED:
        img_ids: set[str] = set()

        # Prefer document-level aggregated list (avoid missing ZIP/embedded images, etc.).
        doc_meta = document.doc_metadata or {}
        doc_img_ids = doc_meta.get("img_ids")
        if isinstance(doc_img_ids, list):
            for v in doc_img_ids:
                if isinstance(v, str) and v.strip():
                    img_ids.add(v)

        # Compatibility: delete per chunk (older data may lack documents.metadata.img_ids).
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id, DocumentChunk.tenant_id == tenant_id)
            .all()
        )
        for chunk in chunks:
            img_id = chunk.doc_metadata.get("img_id") if chunk.doc_metadata else None
            if isinstance(img_id, str) and img_id.strip():
                img_ids.add(img_id)

        for img_id in sorted(img_ids):
            try:
                minio_service.delete_image(img_id, extension="jpg")
            except Exception as e:
                logger.warning("Failed to delete image %s from object storage: %s", img_id, e)

    # 2. Delete vectors from vector store (backend-dependent).
    Indexer(db).delete_chunk_indexes(tenant_id=tenant_id, document_id=document_id)

    # 2.5 Delete structured table store (TAG) sqlite file (best-effort).
    #
    # Storage layout is deterministic and tenant/dataset scoped:
    #   {TABLE_STORE_DIR}/{tenant_id}/{dataset_id}/{document_id}.sqlite3
    if document.dataset_id is not None and str(document.file_type or "").lower() in {"csv", "xls", "xlsx"}:
        try:
            from app.services.table_store import table_store_path

            db_path = table_store_path(tenant_id=tenant_id, dataset_id=document.dataset_id, document_id=document.id)
            if db_path.exists():
                db_path.unlink(missing_ok=True)
            # Best-effort: remove empty parent dirs.
            with contextlib.suppress(Exception):
                db_path.parent.rmdir()
            with contextlib.suppress(Exception):
                db_path.parent.parent.rmdir()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to delete table store file for document %s: %s", document_id, str(exc)[:200])

    # 3. Delete local file.
    try:
        raw_path = str(document.file_path or "").strip()
        if raw_path and not raw_path.startswith(MANUAL_FILE_PATH_PREFIX):
            if is_minio_uri(raw_path):
                if bool(getattr(settings, "MINIO_ENABLED", False)):
                    try:
                        ref = parse_minio_uri(raw_path)
                        if ref.bucket == str(getattr(settings, "MINIO_BUCKET_NAME", "")):
                            dataset_id = str(document.dataset_id) if document.dataset_id else str(tenant_id)
                            expected_object = minio_service.build_document_object_name(
                                tenant_id=str(tenant_id),
                                dataset_id=dataset_id,
                                document_id=str(document.id),
                                extension=f".{(document.file_type or '').lower()}",
                            )
                            if ref.object_name == expected_object:
                                minio_service.delete_object(object_name=ref.object_name)
                    except Exception as e:
                        logger.warning("Failed to delete document from object storage: %s", e)
            else:
                file_path = Path(raw_path)
                if file_path.exists() and file_path.is_file():
                    # Prevent path traversal / unsafe paths in DB: only allow deletes under uploads/{tenant_id}/
                    upload_root = Path(settings.UPLOAD_DIR)
                    tenant_root = upload_root / str(tenant_id)
                    from app.services.path_safety import resolve_under_base

                    safe = resolve_under_base(file_path, base=tenant_root)
                    if safe is None:
                        logger.warning("Skipping unsafe document file delete: %s", raw_path)
                    else:
                        safe.unlink(missing_ok=True)
    except Exception as e:
        logger.warning("Failed to delete file: %s", e)

    # 4. Delete DB record (cascade chunks).
    # Touch dataset.updated_at so API instances can invalidate dataset-scoped retrieval caches
    # (BM25/sparse/ColBERT in-memory + persisted indexes) after deletes.
    #
    # This is important for correctness: without it, stale in-memory indices can keep returning
    # deleted chunks until the next ingestion run touches the dataset.
    if getattr(document, "dataset_id", None) is not None:
        try:
            from datetime import datetime

            from app.models.dataset import Dataset as DBDataset  # noqa: WPS433

            ds = (
                db.query(DBDataset)
                .filter(
                    DBDataset.tenant_id == tenant_id,
                    DBDataset.id == document.dataset_id,
                )
                .first()
            )
            if ds is not None:
                ds.updated_at = datetime.now(UTC)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed touching dataset.updated_at after delete: %s", str(exc)[:200])

    db.delete(document)
    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.delete",
        resource_type="document",
        resource_id=str(document_id),
        details={
            "dataset_id": str(document.dataset_id) if getattr(document, "dataset_id", None) else None,
            "file_type": str(getattr(document, "file_type", "") or ""),
            "file_size": int(getattr(document, "file_size", 0) or 0),
        },
    )
    db.commit()

    # Best-effort: cleanup KG artifacts derived from this document.
    #
    # Notes:
    # - KG tables are not FK-linked to `documents`, so we must delete them explicitly.
    # - Do this after committing the primary delete so KG cleanup failures cannot roll back the main lifecycle op.
    try:
        from app.rag.kg.models import KgRelation

        db.query(KgRelation).filter(
            KgRelation.tenant_id == tenant_id,
            KgRelation.document_id == document_id,
        ).delete(synchronize_session=False)

        Indexer(db).delete_event_indexes(
            tenant_id=tenant_id,
            document_id=document_id,
            commit=False,
            prune_orphan_entities=True,
        )
        db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()

    # 5. Remove chunks from BM25 index (in-memory).
    return None

@dataclass
class PreviewDocumentFormFields:
    parser_backend: str = Form(settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Form(settings.DEFAULT_CHUNK_STRATEGY)
    dataset_id: str | None = Form(None)
    pipeline: str | None = Form(None)


@dataclass
class PreviewDocumentGovernanceOverridesFormFields:
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


@router.post("/preview", response_model=DocumentParsePreview, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def preview_document(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    form: Annotated[PreviewDocumentFormFields, Depends()],
    gov_overrides_form: Annotated[PreviewDocumentGovernanceOverridesFormFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Document parse preview endpoint.

    Only parses the document and returns structured segments; does not create
    a document record or persist data. Useful for frontend custom chunking.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    file.filename = _sanitize_filename(file.filename)

    parser_backend = form.parser_backend
    dataset_id = form.dataset_id
    pipeline = form.pipeline

    pipeline_overrides = PipelineOptionOverrides(**asdict(gov_overrides_form))
    # Validate file type.
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )

    # Save file to a temp path for parsing.
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    upload_dir.mkdir(parents=True, exist_ok=True)

    run_dir = upload_dir / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=True)
    temp_path = run_dir / f"input{file_ext}"
    artifact_dirs: set[str] = set()

    try:
        file_size = await save_upload_file(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)

        parsed = await run_subprocess_worker(
            tenant_id=tenant_id,
            payload={
                "action": "parse_documents",
                "tenant_id": str(tenant_id),
                "file_path": str(temp_path),
                "parser_backend": parser_backend,
                "mode": "preview",
            },
            disconnect_check=request.is_disconnected,
            timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
        )
        documents = [
            Document(
                page_content=str(item.get("page_content") or ""),
                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                id=item.get("id") if isinstance(item.get("id"), str) else None,
            )
            for item in (parsed.get("documents") or [])
            if isinstance(item, dict)
        ]
        resolved_backend = str(parsed.get("resolved_backend") or parser_backend)
        pdf_quality = parsed.get("pdf_quality") if isinstance(parsed.get("pdf_quality"), dict) else None
        for doc in documents:
            artifact_dir = (doc.metadata or {}).get("artifact_dir")
            if isinstance(artifact_dir, str) and artifact_dir.strip():
                artifact_dirs.add(artifact_dir.strip())

        # Optional: incorporate dataset-level pipeline defaults for consistent preview behavior.
        dataset_meta: dict = {}
        if dataset_id:
            try:
                ds = DatasetService.get_dataset(db, tenant_id, UUID(str(dataset_id)))
                DatasetService.assert_dataset_readable(db, ds, account_id)
                dataset_meta = dict(getattr(ds, "dataset_metadata", None) or {})
            except HTTPException:
                raise
            except Exception:
                # If dataset_id is invalid, keep legacy behavior (no dataset override).
                dataset_meta = {}

        pipeline_options = _to_pipeline_options(pipeline=_parse_pipeline_json(pipeline), overrides=pipeline_overrides)
        pipeline_effective = resolve_pipeline_effective(
            dataset_metadata=dataset_meta,
            document_metadata={},
            request_overrides=pipeline_options,
        )

        raw_markdown = "\n\n".join([(d.page_content or "") for d in documents])
        raw_analytics = compute_document_analytics(
            markdown=raw_markdown,
            documents=documents,
            pdf_quality=pdf_quality,
            detect_language=bool(pipeline_effective.governance_detect_language),
            language_min_chars=int(pipeline_effective.governance_language_min_chars or 0),
        ).to_dict()

        if pipeline_effective.governance_enabled:
            extra_rules = list(getattr(pipeline_effective, "governance_regex_rules", None) or [])
            combined_rules = build_governance_rules(extra_rules) if extra_rules else None
            governance_kwargs = {
                **({"rules": combined_rules} if combined_rules else {}),
                "remove_toc_lines": pipeline_effective.governance_remove_toc_lines,
                "remove_noise_lines": pipeline_effective.governance_remove_noise_lines,
                "unwrap_lines": pipeline_effective.governance_unwrap_lines,
                "remove_common_lines": pipeline_effective.governance_remove_common_lines,
                "remove_boilerplate": pipeline_effective.governance_remove_boilerplate,
                "remove_images": pipeline_effective.governance_remove_images,
                "extract_frontmatter": pipeline_effective.governance_extract_frontmatter,
                "strip_frontmatter": pipeline_effective.governance_strip_frontmatter,
                "detect_language": pipeline_effective.governance_detect_language,
                "language_min_chars": pipeline_effective.governance_language_min_chars,
                "normalize_urls": pipeline_effective.governance_normalize_urls,
                "normalize_urls_strip_tracking": pipeline_effective.governance_normalize_urls_strip_tracking,
                "drop_duplicate_paragraphs": pipeline_effective.governance_drop_duplicate_paragraphs,
                "drop_duplicate_paragraphs_min_occurrences": pipeline_effective.governance_drop_duplicate_paragraphs_min_occurrences,
                "drop_duplicate_paragraphs_min_chars": pipeline_effective.governance_drop_duplicate_paragraphs_min_chars,
                "drop_duplicate_paragraphs_max_chars": pipeline_effective.governance_drop_duplicate_paragraphs_max_chars,
                "trim_references": pipeline_effective.governance_trim_references,
                "extract_keywords": pipeline_effective.governance_extract_keywords,
                "keywords_provider": pipeline_effective.governance_keywords_provider,
                "keywords_top_k": pipeline_effective.governance_keywords_top_k,
                "keywords_max_chars": pipeline_effective.governance_keywords_max_chars,
                "normalize_tables": pipeline_effective.governance_normalize_tables,
                "strip_code_line_numbers": pipeline_effective.governance_strip_code_line_numbers,
                "pii_anonymize": pipeline_effective.governance_pii_anonymize,
                "pii_mode": pipeline_effective.governance_pii_mode,
                "pii_mask": pipeline_effective.governance_pii_mask,
                "secrets_redact": pipeline_effective.governance_secrets_redact,
                "secrets_mode": pipeline_effective.governance_secrets_mode,
                "secrets_mask": pipeline_effective.governance_secrets_mask,
                "max_blank_lines": pipeline_effective.governance_max_blank_lines,
                "drop_outline_only": pipeline_effective.governance_drop_outline_only,
                "drop_outline_min_content_chars": pipeline_effective.governance_drop_outline_min_content_chars,
                "drop_outline_max_heading_ratio": pipeline_effective.governance_drop_outline_max_heading_ratio,
                "drop_low_density": pipeline_effective.governance_drop_low_density,
                "drop_low_density_threshold": pipeline_effective.governance_drop_low_density_threshold,
                "unwrap_max_line_length": pipeline_effective.governance_unwrap_max_line_length,
                "noise_min_chars": pipeline_effective.governance_noise_min_chars,
                "noise_ratio_threshold": pipeline_effective.governance_noise_ratio_threshold,
                "common_lines_min_docs": pipeline_effective.governance_common_lines_min_docs,
                "common_lines_min_ratio": pipeline_effective.governance_common_lines_min_ratio,
            }
            documents, _stats = governance_processor.clean_documents(
                documents,
                **governance_kwargs,
            )

        cleaned_markdown = "\n\n".join([(d.page_content or "") for d in documents])
        cleaned_analytics = compute_document_analytics(
            markdown=cleaned_markdown,
            documents=documents,
            pdf_quality=pdf_quality,
            detect_language=bool(pipeline_effective.governance_detect_language),
            language_min_chars=int(pipeline_effective.governance_language_min_chars or 0),
        ).to_dict()

        segments: list[ParsedSegment] = []
        for idx, doc in enumerate(documents):
            segments.append(ParsedSegment(
                index=idx,
                content=doc.page_content,
                page_number=doc.metadata.get('page'),
                metadata=doc.metadata or {}
            ))

        return DocumentParsePreview(
            filename=file.filename,
            file_type=file_ext.lstrip('.'),
            file_size=file_size,
            segments=segments,
            parser_backend=resolved_backend,
            analytics={"raw": raw_analytics, "cleaned": cleaned_analytics},
        )
    except SubprocessCancelled:
        # Client disconnected; stop work early.
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as e:
        # Map input validation errors to 400 to preserve historical behavior.
        err_type = (e.details or {}).get("type")
        if err_type == "ValueError":
            raise HTTPException(status_code=400, detail=f"Invalid input: {str(e)[:100]}") from e
        logger.error("Subprocess worker failed during preview: %s", str(e)[:200])
        msg = (str(e) or "").strip()
        if not msg:
            details = e.details or {}
            msg = str(details.get("message") or details.get("type") or e.__class__.__name__).strip()
        msg = msg[:200]
        detail = "Failed to parse document" if is_production_env() else f"Failed to parse document: {msg}"
        raise HTTPException(status_code=500, detail=detail) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid input: {str(e)[:100]}") from e
    except IOError as e:
        logger.error("File read error during preview: %s", str(e)[:200])
        raise HTTPException(status_code=500, detail="File read error") from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error during document preview: %s", str(e)[:200])
        msg = (str(e) or "").strip()
        if not msg:
            msg = e.__class__.__name__
        msg = msg[:200]
        detail = "Failed to parse document" if is_production_env() else f"Failed to parse document: {msg}"
        raise HTTPException(status_code=500, detail=detail) from e
    finally:
        try:
            if run_dir.exists():
                shutil.rmtree(run_dir, ignore_errors=True)
        except OSError as e:
            logger.warning("Failed to clean up preview directory %s: %s", run_dir, e)

        # Best-effort cleanup for preview parser artifacts (e.g., MagicPDF output).
        if artifact_dirs and not bool(getattr(settings, "MAGIC_PDF_KEEP_ARTIFACTS", False)):
            upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
            tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
            for raw in sorted(artifact_dirs):
                try:
                    path = Path(raw).resolve(strict=False)
                    if not path.exists():
                        continue
                    if not any(p in path.parts for p in {".magicpdf", ".deepseek_ocr", ".qianfan_ocr", ".etl4llm", ".marker", ".paddlevl", ".olmocr"}):
                        continue
                    path.relative_to(tenant_root)
                except Exception:
                    continue
                with contextlib.suppress(Exception):
                    shutil.rmtree(path, ignore_errors=True)

@dataclass
class ChunkPreviewRequestFields:
    # Query params (default FastAPI behaviour for simple types)
    chunk_size: int = 1000
    chunk_overlap: int = 200
    include_original_text: bool = True
    include_review_signals: bool = Query(False)
    include_chunks: bool = Query(True)
    original_text_max_chars: int = 100000
    max_chunks: int = 0
    use_parse_cache: bool = Query(True)

    # Form fields (multipart tuning options)
    parser_backend: str = Form(settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Form(settings.DEFAULT_CHUNK_STRATEGY)

    # Strategy-specific options (enterprise tuning). Currently used by parent_child.
    child_ratio: float | None = Form(None)
    min_child_size: int | None = Form(None)
    separator_preset: str | None = Form(None)
    separator: str | None = Form(None)
    keep_separator: bool | None = Form(None)
    separator_max_chunk_size: int | None = Form(None)

    # Pipeline / governance tuning
    dataset_id: str | None = Form(None)
    pipeline: str | None = Form(None)
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


@dataclass
class ChunkPreviewByShaFileFields:
    file_sha256: str = Form(...)
    file_type: str | None = Form(None)
    filename: str | None = Form(None)
    file_size: int | None = Form(None)


def _should_inline_preview_parse(file_ext: str) -> bool:
    """Use in-process parsing for already-textual preview files to avoid worker cold-start."""
    if not bool(getattr(settings, "PREVIEW_INLINE_TEXT_PARSE_ENABLED", True)):
        return False
    ext = str(file_ext or "").strip().lower()
    return ext == ".md" or ext in parser_factory.PLAIN_TEXT_EXTENSIONS


def _serialize_preview_parse_documents(documents: list[Document]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for doc in documents or []:
        metadata = getattr(doc, "metadata", None) or {}
        try:
            safe_metadata = json.loads(json.dumps(metadata, ensure_ascii=False, default=str))
        except Exception:
            safe_metadata = {}
        out.append(
            {
                "page_content": str(getattr(doc, "page_content", "") or ""),
                "metadata": safe_metadata if isinstance(safe_metadata, dict) else {},
                "id": str(getattr(doc, "id", "") or "") or None,
            }
        )
    return out


@router.post("/chunk-preview", response_model=ChunkPreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def preview_chunking(
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File(...)],
    params: Annotated[ChunkPreviewRequestFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Chunk preview endpoint.

    Upload a file and preview chunking with the given parameters (no DB writes).
    Returns chunk results with positions for frontend highlighting.

    Args:
        file: Uploaded file.
        chunk_size: Chunk size (100-4000).
        chunk_overlap: Overlap size (0-1000).

    Returns:
        Chunk preview result including content and position info.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    file.filename = _sanitize_filename(file.filename)

    chunk_size = params.chunk_size
    chunk_overlap = params.chunk_overlap
    include_original_text = params.include_original_text
    include_review_signals = params.include_review_signals
    include_chunks = params.include_chunks
    original_text_max_chars = params.original_text_max_chars
    max_chunks = params.max_chunks
    use_parse_cache = params.use_parse_cache
    parser_backend = params.parser_backend
    chunk_strategy = params.chunk_strategy
    child_ratio = params.child_ratio
    min_child_size = params.min_child_size
    separator_preset = params.separator_preset
    separator = params.separator
    keep_separator = params.keep_separator
    separator_max_chunk_size = params.separator_max_chunk_size
    dataset_id = params.dataset_id
    pipeline = params.pipeline
    governance_enabled = params.governance_enabled
    governance_remove_toc_lines = params.governance_remove_toc_lines
    governance_remove_noise_lines = params.governance_remove_noise_lines
    governance_unwrap_lines = params.governance_unwrap_lines
    governance_remove_common_lines = params.governance_remove_common_lines
    governance_unwrap_max_line_length = params.governance_unwrap_max_line_length
    governance_noise_min_chars = params.governance_noise_min_chars
    governance_noise_ratio_threshold = params.governance_noise_ratio_threshold
    governance_common_lines_min_docs = params.governance_common_lines_min_docs
    governance_common_lines_min_ratio = params.governance_common_lines_min_ratio
    preview_started = time.perf_counter()
    parse_cache_hit = False
    parse_cache_age_ms: int | None = None
    file_sha256: str | None = None
    upload_duration_ms: int | None = None
    parse_duration_ms: int | None = 0
    governance_duration_ms: int = 0
    chunking_duration_ms: int = 0
    stats_duration_ms: int = 0

    # Resolve strategy early so validation can be strategy-aware.
    try:
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Parameter validation.
    min_chunk_size = 50 if resolved_chunk_strategy == "langchain_token" else 100
    if chunk_size < min_chunk_size or chunk_size > 4000:
        raise HTTPException(status_code=400, detail=f"chunk_size must be between {min_chunk_size} and 4000")
    if chunk_overlap < 0 or chunk_overlap > 1000:
        raise HTTPException(status_code=400, detail="chunk_overlap must be between 0 and 1000")
    if resolved_chunk_strategy != "separator" and chunk_overlap >= chunk_size:
        raise HTTPException(status_code=400, detail=CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL)

    # separator strategy does not use overlap; normalize for downstream consistency.
    effective_chunk_overlap = 0 if resolved_chunk_strategy == "separator" else chunk_overlap

    warnings_out: list[str] = []
    if resolved_chunk_strategy == "separator" and chunk_overlap != effective_chunk_overlap:
        warnings_out.append("separator strategy ignores chunk_overlap; using 0")

    # Strategy params can come from explicit form fields or pipeline.chunk_strategy_params.
    # Precedence: explicit form fields > pipeline params > chunker defaults.
    if (child_ratio is not None or min_child_size is not None) and resolved_chunk_strategy != "parent_child":
        warnings_out.append(
            f"strategy params child_ratio/min_child_size ignored for chunk_strategy={resolved_chunk_strategy}"
        )
    chunker_kwargs: dict[str, Any] = {}
    separator_config: dict[str, Any] | None = None
    strategy_params_out: dict[str, Any] = {}

    # Control whether we return original_text for highlighting (large payload guardrail).
    if original_text_max_chars < 0 or original_text_max_chars > 2_000_000:
        raise HTTPException(status_code=400, detail="original_text_max_chars must be between 0 and 2000000")
    include_original = bool(include_original_text) and int(original_text_max_chars or 0) > 0

    if max_chunks < 0 or max_chunks > 20000:
        raise HTTPException(status_code=400, detail="max_chunks must be between 0 and 20000")

    # Validate file type.
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )

    # Save to a temp path.
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    upload_dir.mkdir(parents=True, exist_ok=True)
    run_dir = upload_dir / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=True)
    temp_path = run_dir / f"input{file_ext}"

    # Defensive default: avoid NameError if any branch exits early.
    file_size: int = 0

    try:
        _upload_started = time.perf_counter()
        file_size, file_sha256 = await save_upload_file_with_hash(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)
        upload_duration_ms = int(max(0.0, (time.perf_counter() - _upload_started) * 1000.0))
        file_size = int(file_size or 0)
        if file_size <= 0:
            with contextlib.suppress(OSError):
                file_size = int(temp_path.stat().st_size)

        dataset_meta: dict = {}
        if dataset_id:
            try:
                ds = DatasetService.get_dataset(db, tenant_id, UUID(str(dataset_id)))
                DatasetService.assert_dataset_readable(db, ds, account_id)
                dataset_meta = dict(getattr(ds, "dataset_metadata", None) or {})
            except HTTPException:
                raise
            except Exception:
                dataset_meta = {}
        pipeline_options = _to_pipeline_options(
            pipeline=_parse_pipeline_json(pipeline),
            governance_enabled=governance_enabled,
            governance_remove_toc_lines=governance_remove_toc_lines,
            governance_remove_noise_lines=governance_remove_noise_lines,
            governance_unwrap_lines=governance_unwrap_lines,
            governance_remove_common_lines=governance_remove_common_lines,
            governance_unwrap_max_line_length=governance_unwrap_max_line_length,
            governance_noise_min_chars=governance_noise_min_chars,
            governance_noise_ratio_threshold=governance_noise_ratio_threshold,
            governance_common_lines_min_docs=governance_common_lines_min_docs,
            governance_common_lines_min_ratio=governance_common_lines_min_ratio,
        )
        pipeline_effective = resolve_pipeline_effective(
            dataset_metadata=dataset_meta,
            document_metadata={},
            request_overrides=pipeline_options,
        )
        pipeline_strategy_params: dict[str, Any] = dict(getattr(pipeline_effective, "chunk_strategy_params", {}) or {})
        if resolved_chunk_strategy == "parent_child":
            merged = dict(pipeline_strategy_params or {})
            if child_ratio is not None:
                merged["child_ratio"] = child_ratio
            if min_child_size is not None:
                merged["min_child_size"] = min_child_size

            if "child_ratio" in merged:
                r = _coerce_float_preview(merged.get("child_ratio"))
                if r is None:
                    raise HTTPException(status_code=400, detail="child_ratio must be a float")
                if r < 0.05 or r > 1.0:
                    raise HTTPException(status_code=400, detail="child_ratio must be between 0.05 and 1.0")
                chunker_kwargs["child_ratio"] = float(r)

            if "min_child_size" in merged:
                m = _coerce_int_preview(merged.get("min_child_size"))
                if m is None:
                    raise HTTPException(status_code=400, detail="min_child_size must be an int")
                if m < 50 or m > 4000:
                    raise HTTPException(status_code=400, detail="min_child_size must be between 50 and 4000")
                if m > int(chunk_size or 0):
                    warnings_out.append("min_child_size > chunk_size; clamping to chunk_size")
                    m = int(chunk_size or 0)
                chunker_kwargs["min_child_size"] = int(m)
        elif resolved_chunk_strategy == "separator":
            merged = dict(pipeline_strategy_params or {})
            if separator_preset is not None:
                merged["separator_preset"] = separator_preset
            if separator is not None:
                merged["separator"] = separator
            if keep_separator is not None:
                merged["keep_separator"] = keep_separator
            if separator_max_chunk_size is not None:
                merged["separator_max_chunk_size"] = separator_max_chunk_size

            preset = str(merged.get("separator_preset") or "").strip() or "paragraph"
            if preset != "custom":
                sep_value = SeparatorChunker.PRESET_SEPARATORS.get(preset)
                if sep_value is None:
                    raise HTTPException(status_code=400, detail=f"Invalid separator_preset: {preset}")
            else:
                raw = merged.get("separator")
                if raw is None:
                    raw = merged.get("separator_custom")
                sep_value = str(raw or "")
                if not sep_value:
                    sep_value = "\n\n"
                sep_value = _decode_escaped_input_preview(sep_value)

            keep_sep = merged.get("keep_separator")
            keep_sep_norm = _coerce_bool_preview(keep_sep)
            keep_sep_bool = True if keep_sep_norm is None else bool(keep_sep_norm)

            max_chunk_size = merged.get("separator_max_chunk_size")
            if max_chunk_size is None:
                max_chunk_size = merged.get("max_chunk_size")
            max_chunk_size_int = int(_coerce_int_preview(max_chunk_size) or 0)

            separator_config = {
                "preset": preset,
                "separator": sep_value,
                "keep_separator": keep_sep_bool,
                "separator_max_chunk_size": max_chunk_size_int,
            }
        else:
            chunker_kwargs = _filter_chunker_kwargs_for_strategy(resolved_chunk_strategy, pipeline_strategy_params)
        extra_rules = list(getattr(pipeline_effective, "governance_regex_rules", None) or [])
        combined_rules = build_governance_rules(extra_rules) if extra_rules else None
        governance_kwargs = {
            **({"rules": combined_rules} if combined_rules else {}),
            "remove_toc_lines": pipeline_effective.governance_remove_toc_lines,
            "remove_noise_lines": pipeline_effective.governance_remove_noise_lines,
            "unwrap_lines": pipeline_effective.governance_unwrap_lines,
            # Preview runs operate on a single uploaded document (often multiple pages/segments
            # from the same source). Treating repeated page text as cross-document boilerplate
            # makes offset rebasing and duplicate/overlap diagnostics unstable, so keep
            # common-line dropping disabled in preview mode.
            "remove_common_lines": False,
            "remove_boilerplate": pipeline_effective.governance_remove_boilerplate,
            "remove_images": pipeline_effective.governance_remove_images,
            "extract_frontmatter": pipeline_effective.governance_extract_frontmatter,
            "strip_frontmatter": pipeline_effective.governance_strip_frontmatter,
            "detect_language": pipeline_effective.governance_detect_language,
            "language_min_chars": pipeline_effective.governance_language_min_chars,
            "normalize_urls": pipeline_effective.governance_normalize_urls,
            "normalize_urls_strip_tracking": pipeline_effective.governance_normalize_urls_strip_tracking,
            "drop_duplicate_paragraphs": pipeline_effective.governance_drop_duplicate_paragraphs,
            "drop_duplicate_paragraphs_min_occurrences": pipeline_effective.governance_drop_duplicate_paragraphs_min_occurrences,
            "drop_duplicate_paragraphs_min_chars": pipeline_effective.governance_drop_duplicate_paragraphs_min_chars,
            "drop_duplicate_paragraphs_max_chars": pipeline_effective.governance_drop_duplicate_paragraphs_max_chars,
            "trim_references": pipeline_effective.governance_trim_references,
            "extract_keywords": pipeline_effective.governance_extract_keywords,
            "keywords_provider": pipeline_effective.governance_keywords_provider,
            "keywords_top_k": pipeline_effective.governance_keywords_top_k,
            "keywords_max_chars": pipeline_effective.governance_keywords_max_chars,
            "normalize_tables": pipeline_effective.governance_normalize_tables,
            "strip_code_line_numbers": pipeline_effective.governance_strip_code_line_numbers,
            "pii_anonymize": pipeline_effective.governance_pii_anonymize,
            "pii_mode": pipeline_effective.governance_pii_mode,
            "pii_mask": pipeline_effective.governance_pii_mask,
            "secrets_redact": pipeline_effective.governance_secrets_redact,
            "secrets_mode": pipeline_effective.governance_secrets_mode,
            "secrets_mask": pipeline_effective.governance_secrets_mask,
            "max_blank_lines": pipeline_effective.governance_max_blank_lines,
            "drop_outline_only": pipeline_effective.governance_drop_outline_only,
            "drop_outline_min_content_chars": pipeline_effective.governance_drop_outline_min_content_chars,
            "drop_outline_max_heading_ratio": pipeline_effective.governance_drop_outline_max_heading_ratio,
            "drop_low_density": pipeline_effective.governance_drop_low_density,
            "drop_low_density_threshold": pipeline_effective.governance_drop_low_density_threshold,
            "unwrap_max_line_length": pipeline_effective.governance_unwrap_max_line_length,
            "noise_min_chars": pipeline_effective.governance_noise_min_chars,
            "noise_ratio_threshold": pipeline_effective.governance_noise_ratio_threshold,
            "common_lines_min_docs": pipeline_effective.governance_common_lines_min_docs,
            "common_lines_min_ratio": pipeline_effective.governance_common_lines_min_ratio,
        }

        # Integrated pipeline strategies use a separate branch (self-parse + chunk).
        if resolved_chunk_strategy in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
            parse_duration_ms = None
            _integrated_started = time.perf_counter()
            result = await run_subprocess_worker(
                tenant_id=tenant_id,
                payload={
                    "action": "integrated_chunk",
                    "tenant_id": str(tenant_id),
                    "file_path": str(temp_path),
                    "strategy": resolved_chunk_strategy,
                    "mode": "preview",
                },
                disconnect_check=request.is_disconnected,
                timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
            )
            chunking_duration_ms = int(max(0.0, (time.perf_counter() - _integrated_started) * 1000.0))
            chunks = [
                Document(
                    page_content=str(item.get("page_content") or ""),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    id=item.get("id") if isinstance(item.get("id"), str) else None,
                )
                for item in (result.get("documents") or [])
                if isinstance(item, dict)
            ]
            resolved_backend = "integrated"
            documents = []  # Integrated pipeline already handled.
            if pipeline_effective.governance_enabled:
                _gov_started = time.perf_counter()
                chunks, _stats = governance_processor.clean_documents(
                    chunks,
                    **governance_kwargs,
                )
                governance_duration_ms += int(max(0.0, (time.perf_counter() - _gov_started) * 1000.0))
        else:
            parsed_docs_payload: list[dict[str, Any]] | None = None
            resolved_backend = str(parser_backend)

            cache_enabled = bool(getattr(settings, "PREVIEW_PARSE_CACHE_ENABLED", False))
            cache_ttl_sec = int(getattr(settings, "PREVIEW_PARSE_CACHE_TTL_SEC", 0) or 0)
            cache_max_entries = int(getattr(settings, "PREVIEW_PARSE_CACHE_MAX_ENTRIES", 0) or 0)
            cache_max_doc_chars = int(getattr(settings, "PREVIEW_PARSE_CACHE_MAX_DOC_CHARS", 0) or 0)
            cache_version = str(getattr(settings, "PREVIEW_PARSE_CACHE_VERSION", "v1") or "v1").strip() or "v1"

            async def _parse_uncached_preview_documents() -> tuple[list[dict[str, Any]], str]:
                nonlocal parse_duration_ms
                _parse_started = time.perf_counter()
                if _should_inline_preview_parse(file_ext):
                    parsed_documents, backend, _provenance = parser_factory.parse_with_provenance(
                        temp_path,
                        parser_backend=parser_backend,
                        tenant_id=str(tenant_id),
                    )
                    parsed_documents = _materialize_extracted_images_for_preview(parsed_documents, tenant_id=tenant_id)
                    parsed_documents = _materialize_local_images_for_preview(parsed_documents, tenant_id=tenant_id)
                    parse_duration_ms = int(max(0.0, (time.perf_counter() - _parse_started) * 1000.0))
                    return _serialize_preview_parse_documents(parsed_documents), str(backend or parser_backend)

                parsed = await run_subprocess_worker(
                    tenant_id=tenant_id,
                    payload={
                        "action": "parse_documents",
                        "tenant_id": str(tenant_id),
                        "file_path": str(temp_path),
                        "parser_backend": parser_backend,
                        "mode": "preview",
                    },
                    disconnect_check=request.is_disconnected,
                    timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
                )
                parse_duration_ms = int(max(0.0, (time.perf_counter() - _parse_started) * 1000.0))
                return [
                    item for item in (parsed.get("documents") or []) if isinstance(item, dict)
                ], str(parsed.get("resolved_backend") or parser_backend)

            cache_key: str | None = None
            if (
                cache_enabled
                and bool(use_parse_cache)
                and bool(file_sha256)
                and cache_ttl_sec > 0
                and cache_max_entries > 0
            ):
                cache_key = (
                    # Scope to tenant + account to avoid cross-user cache leakage in multi-user tenants.
                    f"parse:{str(tenant_id)}:{str(account_id)}:{str(file_sha256)}:{str(file_ext)}:"
                    f"{str(parser_backend or '').strip().lower()}:{cache_version}"
                )
                cached, age_ms = preview_parse_cache.get(cache_key, ttl_sec=cache_ttl_sec)
                if cached is not None:
                    parse_cache_hit = True
                    parse_cache_age_ms = age_ms
                    parsed_docs_payload = list(cached.documents or [])
                    resolved_backend = str(cached.resolved_backend or parser_backend)

            if parsed_docs_payload is None:
                lock = preview_parse_locks.get(cache_key) if cache_key else None
                if lock is not None:
                    async with lock:
                        # Double-check cache after acquiring the lock.
                        cached, age_ms = preview_parse_cache.get(cache_key, ttl_sec=cache_ttl_sec)
                        if cached is not None:
                            parse_cache_hit = True
                            parse_cache_age_ms = age_ms
                            parsed_docs_payload = list(cached.documents or [])
                            resolved_backend = str(cached.resolved_backend or parser_backend)
                            parse_duration_ms = 0

                        if parsed_docs_payload is None:
                            parsed_docs_payload, resolved_backend = await _parse_uncached_preview_documents()

                            if cache_key and cache_enabled and bool(use_parse_cache) and cache_ttl_sec > 0 and cache_max_entries > 0:
                                total_chars = sum(len(str(it.get("page_content") or "")) for it in (parsed_docs_payload or []))
                                if cache_max_doc_chars <= 0 or total_chars <= cache_max_doc_chars:
                                    preview_parse_cache.set(
                                        cache_key,
                                        ParseCacheEntry(
                                            created_at_monotonic=time.monotonic(),
                                            created_at_wall=time.time(),
                                            file_sha256=str(file_sha256 or ""),
                                            parser_backend=str(parser_backend or ""),
                                            resolved_backend=str(resolved_backend or ""),
                                            documents=list(parsed_docs_payload or []),
                                            total_chars=int(total_chars),
                                        ),
                                        ttl_sec=cache_ttl_sec,
                                        max_entries=cache_max_entries,
                                    )
                else:
                    parsed_docs_payload, resolved_backend = await _parse_uncached_preview_documents()

                    if cache_key and cache_enabled and bool(use_parse_cache) and cache_ttl_sec > 0 and cache_max_entries > 0:
                        total_chars = sum(len(str(it.get("page_content") or "")) for it in (parsed_docs_payload or []))
                        if cache_max_doc_chars <= 0 or total_chars <= cache_max_doc_chars:
                            preview_parse_cache.set(
                                cache_key,
                                ParseCacheEntry(
                                    created_at_monotonic=time.monotonic(),
                                    created_at_wall=time.time(),
                                    file_sha256=str(file_sha256 or ""),
                                    parser_backend=str(parser_backend or ""),
                                    resolved_backend=str(resolved_backend or ""),
                                    documents=list(parsed_docs_payload or []),
                                    total_chars=int(total_chars),
                                ),
                                ttl_sec=cache_ttl_sec,
                                max_entries=cache_max_entries,
                            )

            documents = [
                Document(
                    page_content=str(item.get("page_content") or ""),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    id=item.get("id") if isinstance(item.get("id"), str) else None,
                )
                for item in (parsed_docs_payload or [])
                if isinstance(item, dict)
            ]
            if pipeline_effective.governance_enabled:
                _gov_started = time.perf_counter()
                documents, _stats = governance_processor.clean_documents(
                    documents,
                    **governance_kwargs,
                )
                governance_duration_ms += int(max(0.0, (time.perf_counter() - _gov_started) * 1000.0))

            # Ensure stable per-doc indices for offset rebasing (handles missing/duplicate page numbers).
            _ensure_preview_page_indices(documents)

            if resolved_chunk_strategy == "separator":
                assert separator_config is not None
                preset = str(separator_config.get("preset") or "paragraph")
                sep_value = str(separator_config.get("separator") or "\n\n")
                keep_sep_bool = bool(separator_config.get("keep_separator"))
                max_chunk_size_int = int(separator_config.get("separator_max_chunk_size") or 0)
                chunker = SeparatorChunker(
                    chunk_size=chunk_size,
                    chunk_overlap=effective_chunk_overlap,
                    separator=sep_value,
                    keep_separator=keep_sep_bool,
                    max_chunk_size=max_chunk_size_int,
                )
                strategy_params_out = {
                    "separator_preset": preset,
                    "separator": sep_value,
                    "keep_separator": keep_sep_bool,
                    "separator_max_chunk_size": max_chunk_size_int,
                }
            else:
                chunker = chunker_factory.get_chunker(
                    resolved_chunk_strategy,
                    chunk_size=chunk_size,
                    chunk_overlap=effective_chunk_overlap,
                    **chunker_kwargs,
                )
                strategy_params_out = dict(chunker_kwargs)
                if resolved_chunk_strategy == "parent_child":
                    with contextlib.suppress(Exception):
                        strategy_params_out = {
                            "child_ratio": float(chunker.child_ratio),
                            "min_child_size": int(chunker.min_child_size),
                            "child_size": int(chunker.child_size),
                            "child_overlap": int(chunker.child_overlap),
                        }
            _chunk_started = time.perf_counter()
            chunks = chunker.split_documents(documents)
            chunking_duration_ms = int(max(0.0, (time.perf_counter() - _chunk_started) * 1000.0))

        # Optional: merge extremely short chunks with neighbors (preview-time).
        merge_min = max(0, int(getattr(pipeline_effective, "chunk_merge_small_min_chars", 0) or 0))
        if merge_min > 0 and documents and chunks:
            chunks = _merge_small_chunks_preview(documents=documents, chunks=chunks, min_chars=merge_min)

        # Align with ingestion: drop extremely short chunks (keep image-bearing chunks).
        min_chars = max(0, int(getattr(settings, "CHUNK_MIN_CHARS", 0) or 0))
        if min_chars > 0 and chunks:
            before = len(chunks)
            original_chunks = chunks
            filtered = []
            for c in original_chunks:
                content = (c.page_content or "").strip()
                if len(content) >= min_chars:
                    filtered.append(c)
                    continue
                meta = c.metadata or {}
                if (
                    meta.get("img_id")
                    or meta.get("image_id")
                    or meta.get("image_url")
                    or PREVIEW_IMAGE_REF_RE.search(content)
                    or MINIO_IMAGE_REF_RE.search(content)
                    or (DATA_IMAGE_PREFIX in content.lower())
                ):
                    filtered.append(c)
            kept_short_fallback = False
            if not filtered and original_chunks:
                # Keep the longest chunk so preview stays consistent with ingestion.
                longest = max(original_chunks, key=lambda d: len((d.page_content or "").strip()))
                filtered = [longest]
                kept_short_fallback = True
            chunks = filtered
            dropped = before - len(chunks)
            if kept_short_fallback:
                kept_len = len((chunks[0].page_content or "").strip()) if chunks else 0
                logger.info(
                    "Chunk preview kept 1 short chunk (%s chars) because all chunks were shorter than %s chars",
                    kept_len,
                    min_chars,
                )
            elif dropped:
                logger.info("Chunk preview dropped %s short chunks (<%s chars)", dropped, min_chars)

        # Optional response truncation for huge documents (UI safety / payload guardrail).
        total_chunks_full = len(chunks)
        chunks_truncated = False
        if int(max_chunks or 0) > 0 and len(chunks) > int(max_chunks):
            chunks_truncated = True
            warnings_out.append(f"chunks truncated to max_chunks={int(max_chunks)} (full={total_chunks_full})")
            chunks = chunks[: int(max_chunks)]

        # Merge original text: use parsed pages for non-integrated, chunks for integrated,
        # to keep original_text aligned with chunks for frontend highlighting.
        page_texts: list[dict[str, object]] = []
        integrated_chunk_start_map: dict[int, int] = {}
        page_start_map: dict[object, int] = {}
        page_index_start_map: dict[int, int] = {}
        total_characters = 0
        original_text_value: str | None = None

        if documents:
            current_pos = 0
            for doc in documents:
                text = doc.page_content or ""
                meta = doc.metadata or {}
                page_num = meta.get("page") or meta.get("page_number")
                page_index = meta.get("page_index")
                page_texts.append(
                    {
                        "text": text,
                        "page": page_num,
                        "page_index": page_index,
                        "start": current_pos,
                        "end": current_pos + len(text),
                    }
                )
                current_pos += len(text) + 1  # +1 for "\n" join separator

            total_characters = sum(len(str(p.get("text") or "")) for p in page_texts) + max(0, len(page_texts) - 1)
            # Prefer page_index mapping (unique) and keep first page-number occurrence as a best-effort fallback.
            page_index_start_map = {
                int(item.get("page_index")): int(item.get("start") or 0)
                for item in page_texts
                if item.get("page_index") is not None
            }
            for item in page_texts:
                p = item.get("page")
                if p is None:
                    continue
                if p not in page_start_map:
                    page_start_map[p] = int(item.get("start") or 0)
            if include_original and total_characters <= int(original_text_max_chars or 0):
                original_text_value = "\n".join([str(p.get("text") or "") for p in page_texts]) if page_texts else ""
        else:
            # Integrated pipeline preset: documents is empty; build "locatable" text from chunks.
            # Note: not a strict original full text, but keeps highlighting stable.
            total_characters = sum(len(c.page_content or "") for c in chunks) + (2 * (len(chunks) - 1) if chunks else 0)

            parts: list[str] | None = None
            if include_original and total_characters <= int(original_text_max_chars or 0):
                parts = []

            current_pos = 0
            for idx, chunk in enumerate(chunks):
                text = chunk.page_content or ""
                if parts is not None:
                    parts.append(text)
                integrated_chunk_start_map[idx] = current_pos
                current_pos += len(text) + 2  # +2 for "\n\n" join separator

            if parts is not None:
                original_text_value = "\n\n".join(parts) if parts else ""

        # Build response.
        _stats_started = time.perf_counter()
        from app.rag.chunking.quality_scorer import score_chunk_semantic_quality

        unit: Literal["chars", "tokens"] = "tokens" if resolved_chunk_strategy == "langchain_token" else "chars"
        chunk_items: list[ChunkPreviewItem] = []
        chunk_ranges: list[tuple[int, int]] = []
        length_samples: list[int] = []
        token_lengths: list[int] = []
        total_len = 0
        total_tokens_est = 0
        short_threshold = 40 if unit == "tokens" else 120
        short_count = 0
        seen_hashes: set[str] = set()
        duplicate_count = 0
        auto_counts: Counter[str] = Counter()
        semantic_quality_enabled = bool(include_chunks) or bool(include_review_signals)
        semantic_quality_max_chunks = 512
        prev_token_set: set[str] | None = None
        needs_review_count = 0

        for idx, chunk in enumerate(chunks):
            content = chunk.page_content or ""
            meta = chunk.metadata if isinstance(chunk.metadata, dict) else {}
            if not isinstance(chunk.metadata, dict):
                chunk.metadata = meta
            page_num = meta.get("page") or meta.get("page_number")
            page_index = meta.get("page_index")
            local_start = meta.get("start_char")
            local_end = meta.get("end_char")

            doc_base: int | None = None
            if idx in integrated_chunk_start_map:
                start_idx = integrated_chunk_start_map[idx]
            else:
                if page_index is not None:
                    try:
                        doc_base = page_index_start_map.get(int(page_index))
                    except Exception:
                        doc_base = None
                if doc_base is None and page_num is not None:
                    doc_base = page_start_map.get(page_num)

                if doc_base is None:
                    # Last resort: treat start_char as already-global (best-effort).
                    if meta.get("start_char") is not None:
                        start_idx = int(meta.get("start_char"))
                    else:
                        start_idx = 0
                else:
                    try:
                        local = int(local_start) if local_start is not None else 0
                    except Exception:
                        local = 0
                    start_idx = int(doc_base) + local

            # Prefer explicit end offsets when chunkers provide them; this is important for
            # PDF position-tag workflows where chunk text may be tag-stripped but highlight
            # ranges must remain in the original (tagged) coordinate space.
            end_idx = start_idx + len(content)
            if local_end is not None and idx not in integrated_chunk_start_map:
                try:
                    end_local = int(local_end)
                except Exception:
                    end_local = None
                if end_local is not None:
                    end_idx = end_local if doc_base is None else int(doc_base) + end_local
            if end_idx < start_idx:
                end_idx = start_idx + len(content)
            if end_idx > start_idx:
                chunk_ranges.append((start_idx, end_idx))
            tokens_est = 0
            if content:
                # Token mode uses tiktoken when available; otherwise falls back to rough 4 chars/token.
                # For non-token strategies, prefer fast estimation to keep preview snappy for large corpora.
                tokens_est = (
                    num_tokens_from_string(content)
                    if resolved_chunk_strategy == "langchain_token"
                    else estimate_tokens(content)
                )

            if semantic_quality_enabled and idx < semantic_quality_max_chunks:
                with contextlib.suppress(Exception):
                    scores, cur_token_set = score_chunk_semantic_quality(
                        content,
                        tokens_est=int(tokens_est or 0),
                        prev_token_set=prev_token_set,
                    )
                    meta["semantic_quality"] = scores
                    if bool(scores.get("needs_review")):
                        meta["needs_review"] = True
                        needs_review_count += 1
                    prev_token_set = cur_token_set

            total_tokens_est += int(tokens_est or 0)
            if int(tokens_est or 0) > 0:
                token_lengths.append(int(tokens_est or 0))
            unit_len = int(tokens_est or 0) if unit == "tokens" else len(content)
            length_samples.append(unit_len)
            total_len += unit_len
            if unit_len > 0 and unit_len < short_threshold:
                short_count += 1

            stripped = content.strip()
            if stripped:
                digest = hashlib.sha256(stripped.encode("utf-8", "ignore")).hexdigest()
                if digest in seen_hashes:
                    duplicate_count += 1
                else:
                    seen_hashes.add(digest)

            if resolved_chunk_strategy == "auto":
                selected = meta.get("chunk_strategy_selected")
                if isinstance(selected, str) and selected.strip():
                    auto_counts[selected.strip().lower()] += 1

            if bool(include_chunks) or bool(include_review_signals):
                chunk_items.append(ChunkPreviewItem(
                    index=idx,
                    content=content,
                    length=len(content),
                    hierarchy_basis=(str(meta.get("hierarchy_basis")).strip() if meta.get("hierarchy_basis") is not None else None),
                    tokens_est=tokens_est,
                    start_index=start_idx,
                    end_index=end_idx,
                    page_number=page_num,
                    metadata=chunk.metadata
                ))

        if semantic_quality_enabled and needs_review_count > 0:
            warnings_out.append(f"{int(needs_review_count)} chunks flagged needs_review (semantic heuristics)")

        sorted_lengths = sorted(length_samples)
        # Token stats (always derived from per-chunk `tokens_est`, independent of `unit`).
        token_stats: dict[str, Any] | None = None
        with contextlib.suppress(Exception):
            from app.services.chunking_stats_utils import compute_chunking_stats_from_lengths
            from app.services.dataset_profile_utils import CHUNK_TOKEN_BINS

            token_stats = compute_chunking_stats_from_lengths(
                token_lengths,
                short_threshold=40,
                duplicate_count=int(duplicate_count),
                unit="tokens",
                bins=CHUNK_TOKEN_BINS,
            )
        if sorted_lengths:
            def _pct(p: int) -> int:
                if not sorted_lengths:
                    return 0
                pp = max(0, min(100, int(p)))
                pos = int((pp / 100.0) * (len(sorted_lengths) - 1))
                pos = max(0, min(len(sorted_lengths) - 1, pos))
                return int(sorted_lengths[pos] or 0)

            coverage = _compute_chunk_coverage_metrics_from_ranges(chunk_ranges, total_characters=total_characters)
            histogram = _compute_chunk_length_histogram(sorted_lengths, unit=unit, target_bins=8)
            stats = ChunkPreviewStats(
                unit=unit,
                count=len(sorted_lengths),
                total=int(total_len),
                min=int(sorted_lengths[0]),
                max=int(sorted_lengths[-1]),
                avg=int(round(total_len / len(sorted_lengths))) if sorted_lengths else 0,
                median=_pct(50),
                p10=_pct(10),
                p90=_pct(90),
                p95=_pct(95),
                total_tokens_est=int(total_tokens_est),
                short_count=int(short_count),
                duplicate_count=int(duplicate_count),
                histogram=histogram,
                **coverage,
            )
        else:
            coverage = _compute_chunk_coverage_metrics_from_ranges(chunk_ranges, total_characters=total_characters)
            stats = ChunkPreviewStats(unit=unit, **coverage)
        stats_duration_ms = int(max(0.0, (time.perf_counter() - _stats_started) * 1000.0))

        auto_selected_strategy: str | None = None
        if resolved_chunk_strategy == "auto" and auto_counts:
            auto_selected_strategy = auto_counts.most_common(1)[0][0]

        original_text_truncated_val = bool(
            include_original
            and original_text_value is None
            and total_characters > int(original_text_max_chars or 0)
        )
        original_text_cleaned_value: str | None = None
        if original_text_value is not None and "@@" in original_text_value and "##" in original_text_value:
            if POSITION_TAG_RE.search(original_text_value):
                original_text_cleaned_value = POSITION_TAG_RE.sub("", original_text_value)
        quality_gate, recommendations, recommendation_patches = _compute_chunk_preview_quality(
            stats=stats,
            total_chunks=len(chunks),
            total_characters=int(total_characters or 0),
            chunk_size=int(chunk_size or 0),
            chunk_overlap=int(effective_chunk_overlap or 0),
            original_text_included=original_text_value is not None,
            original_text_truncated=original_text_truncated_val,
            original_text_max_chars=int(original_text_max_chars or 0),
        )

        review_signals: ChunkPreviewReviewSignals | None = None
        if bool(include_review_signals):
            # For auto strategy, use the dominant selected strategy for overlap semantics.
            signals_strategy = auto_selected_strategy or resolved_chunk_strategy
            with contextlib.suppress(Exception):
                review_signals = _compute_chunk_preview_review_signals(
                    chunk_items=chunk_items,
                    unit="tokens" if resolved_chunk_strategy == "langchain_token" else "chars",
                    strategy=str(signals_strategy or ""),
                )

        preview_duration_ms_val = int(max(0.0, (time.perf_counter() - preview_started) * 1000.0))
        # Best-effort Server-Timing for quick profiling in browser devtools.
        with contextlib.suppress(Exception):
            timing_parts: list[str] = []
            if upload_duration_ms is not None:
                timing_parts.append(f"upload;dur={int(upload_duration_ms)}")
            if parse_duration_ms is not None:
                timing_parts.append(f"parse;dur={int(parse_duration_ms)}")
            timing_parts.append(f"govern;dur={int(governance_duration_ms)}")
            timing_parts.append(f"chunk;dur={int(chunking_duration_ms)}")
            timing_parts.append(f"stats;dur={int(stats_duration_ms)}")
            timing_parts.append(f"total;dur={int(preview_duration_ms_val)}")
            if timing_parts:
                response.headers["Server-Timing"] = ", ".join(timing_parts)

        return ChunkPreviewResponse(
            filename=file.filename,
            file_type=file_ext.lstrip('.'),
            file_size=file_size,
            file_sha256=file_sha256,
            parse_cache_hit=bool(parse_cache_hit),
            parse_cache_age_ms=parse_cache_age_ms,
            preview_duration_ms=preview_duration_ms_val,
            upload_duration_ms=upload_duration_ms,
            parse_duration_ms=parse_duration_ms,
            governance_duration_ms=int(governance_duration_ms),
            chunking_duration_ms=int(chunking_duration_ms),
            stats_duration_ms=int(stats_duration_ms),
            total_chunks=len(chunks),
            total_chunks_full=int(total_chunks_full),
            chunks_truncated=bool(chunks_truncated),
            chunks_max_count=int(max_chunks or 0),
            total_characters=total_characters,
            params=ChunkPreviewParams(
                chunk_size=chunk_size,
                chunk_overlap=effective_chunk_overlap,
                unit="tokens" if resolved_chunk_strategy == "langchain_token" else "chars",
                strategy_params=strategy_params_out,
            ),
            chunks=(chunk_items if bool(include_chunks) else []),
            stats=stats,
            chunking_stats_tokens=token_stats,
            auto_selected_strategy=auto_selected_strategy,
            warnings=warnings_out,
            review_signals=review_signals,
            quality_gate=quality_gate,
            recommendations=recommendations,
            recommendation_patches=recommendation_patches,
            # Skip original text when too large (highlight offsets require full text).
            original_text=original_text_value,
            original_text_cleaned=original_text_cleaned_value,
            original_text_included=original_text_value is not None,
            original_text_truncated=original_text_truncated_val,
            original_text_max_chars=int(original_text_max_chars or 0),
            parser_backend=resolved_backend,
            chunk_strategy=resolved_chunk_strategy
        )

    except SubprocessCancelled:
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as e:
        err_type = (e.details or {}).get("type")
        if err_type == "ValueError":
            raise HTTPException(status_code=400, detail=str(e)) from e
        logger.error("Subprocess worker failed during chunk preview: %s", str(e)[:200])
        msg = (str(e) or "").strip()
        if not msg:
            details = e.details or {}
            msg = str(details.get("message") or details.get("type") or e.__class__.__name__).strip()
        msg = msg[:200]
        detail = "Failed to preview chunking" if is_production_env() else f"Failed to preview chunking: {msg}"
        raise HTTPException(status_code=500, detail=detail) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error during chunk preview: %s", str(e)[:200])
        msg = (str(e) or "").strip()
        if not msg:
            msg = e.__class__.__name__
        msg = msg[:200]
        detail = "Failed to preview chunking" if is_production_env() else f"Failed to preview chunking: {msg}"
        raise HTTPException(status_code=500, detail=detail) from e
    finally:
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


# ==================== Chunk preview reuse API (no upload) ====================

@router.post("/chunk-preview/by-sha", response_model=ChunkPreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def preview_chunking_by_sha(
    request: Request,
    response: Response,
    file_fields: Annotated[ChunkPreviewByShaFileFields, Depends()],
    params: Annotated[ChunkPreviewRequestFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Chunk preview endpoint (reuse parse cache; no file upload).

    Intended for fast A/B tuning after a file has been previewed once and the server-side
    parse cache is warm. If cache is missing/expired, client should fall back to uploading.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    file_sha256 = file_fields.file_sha256
    file_type = file_fields.file_type
    filename = file_fields.filename
    file_size = file_fields.file_size
    chunk_size = params.chunk_size
    chunk_overlap = params.chunk_overlap
    include_original_text = params.include_original_text
    include_review_signals = params.include_review_signals
    include_chunks = params.include_chunks
    original_text_max_chars = params.original_text_max_chars
    max_chunks = params.max_chunks
    use_parse_cache = params.use_parse_cache
    parser_backend = params.parser_backend
    chunk_strategy = params.chunk_strategy
    child_ratio = params.child_ratio
    min_child_size = params.min_child_size
    separator_preset = params.separator_preset
    separator = params.separator
    keep_separator = params.keep_separator
    separator_max_chunk_size = params.separator_max_chunk_size
    dataset_id = params.dataset_id
    pipeline = params.pipeline
    governance_enabled = params.governance_enabled
    governance_remove_toc_lines = params.governance_remove_toc_lines
    governance_remove_noise_lines = params.governance_remove_noise_lines
    governance_unwrap_lines = params.governance_unwrap_lines
    governance_remove_common_lines = params.governance_remove_common_lines
    governance_unwrap_max_line_length = params.governance_unwrap_max_line_length
    governance_noise_min_chars = params.governance_noise_min_chars
    governance_noise_ratio_threshold = params.governance_noise_ratio_threshold
    governance_common_lines_min_docs = params.governance_common_lines_min_docs
    governance_common_lines_min_ratio = params.governance_common_lines_min_ratio

    preview_started = time.perf_counter()
    parse_cache_hit = False
    parse_cache_age_ms: int | None = None
    upload_duration_ms: int = 0
    parse_duration_ms: int = 0
    governance_duration_ms: int = 0
    chunking_duration_ms: int = 0
    stats_duration_ms: int = 0
    warnings_out: list[str] = []

    sha = (file_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise HTTPException(status_code=400, detail="file_sha256 must be a 64-char hex string")

    raw_type = (file_type or "").strip().lower().lstrip(".")
    if not raw_type and filename:
        raw_type = Path(str(filename)).suffix.lower().lstrip(".")
    if not raw_type:
        raise HTTPException(status_code=400, detail="file_type is required")
    file_ext = f".{raw_type}"
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}")

    safe_name = _sanitize_filename(filename or f"{sha[:8]}{file_ext}")

    # Resolve strategy early so validation can be strategy-aware.
    try:
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Parameter validation (keep aligned with /chunk-preview).
    min_chunk_size = 50 if resolved_chunk_strategy == "langchain_token" else 100
    if chunk_size < min_chunk_size or chunk_size > 4000:
        raise HTTPException(status_code=400, detail=f"chunk_size must be between {min_chunk_size} and 4000")
    if chunk_overlap < 0 or chunk_overlap > 1000:
        raise HTTPException(status_code=400, detail="chunk_overlap must be between 0 and 1000")
    if resolved_chunk_strategy != "separator" and chunk_overlap >= chunk_size:
        raise HTTPException(status_code=400, detail=CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL)

    effective_chunk_overlap = 0 if resolved_chunk_strategy == "separator" else chunk_overlap
    if resolved_chunk_strategy == "separator" and chunk_overlap != effective_chunk_overlap:
        warnings_out.append("separator strategy ignores chunk_overlap; using 0")

    # Strategy params can come from explicit form fields or pipeline.chunk_strategy_params.
    # Precedence: explicit form fields > pipeline params > chunker defaults.
    if (child_ratio is not None or min_child_size is not None) and resolved_chunk_strategy != "parent_child":
        warnings_out.append(
            f"strategy params child_ratio/min_child_size ignored for chunk_strategy={resolved_chunk_strategy}"
        )
    chunker_kwargs: dict[str, Any] = {}
    separator_config: dict[str, Any] | None = None
    strategy_params_out: dict[str, Any] = {}

    # Control whether we return original_text for highlighting (large payload guardrail).
    if original_text_max_chars < 0 or original_text_max_chars > 2_000_000:
        raise HTTPException(status_code=400, detail="original_text_max_chars must be between 0 and 2000000")
    include_original = bool(include_original_text)

    if resolved_chunk_strategy in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        raise HTTPException(status_code=400, detail="Integrated pipeline strategies do not support by-sha preview; please upload the file")

    cache_enabled = bool(getattr(settings, "PREVIEW_PARSE_CACHE_ENABLED", False))
    cache_ttl_sec = int(getattr(settings, "PREVIEW_PARSE_CACHE_TTL_SEC", 0) or 0)
    cache_max_entries = int(getattr(settings, "PREVIEW_PARSE_CACHE_MAX_ENTRIES", 0) or 0)
    cache_version = str(getattr(settings, "PREVIEW_PARSE_CACHE_VERSION", "v1") or "v1").strip() or "v1"
    if not (cache_enabled and bool(use_parse_cache) and cache_ttl_sec > 0 and cache_max_entries > 0):
        raise HTTPException(status_code=400, detail="parse cache disabled; please upload the file")

    cache_key = (
        f"parse:{str(tenant_id)}:{str(account_id)}:{sha}:{str(file_ext)}:"
        f"{str(parser_backend or '').strip().lower()}:{cache_version}"
    )

    cached, age_ms = preview_parse_cache.get(cache_key, ttl_sec=cache_ttl_sec)
    if cached is None:
        raise HTTPException(status_code=404, detail="Parse cache miss. Upload the file once to warm the cache.")

    parse_cache_hit = True
    parse_cache_age_ms = age_ms
    parsed_docs_payload = list(cached.documents or [])
    resolved_backend = str(cached.resolved_backend or parser_backend)

    # Dataset metadata (optional; affects effective pipeline rules).
    dataset_meta: dict = {}
    if dataset_id:
        try:
            ds = DatasetService.get_dataset(db, tenant_id, UUID(str(dataset_id)))
            DatasetService.assert_dataset_readable(db, ds, account_id)
            dataset_meta = dict(getattr(ds, "dataset_metadata", None) or {})
        except HTTPException:
            raise
        except Exception:
            dataset_meta = {}

    pipeline_options = _to_pipeline_options(
        pipeline=_parse_pipeline_json(pipeline),
        governance_enabled=governance_enabled,
        governance_remove_toc_lines=governance_remove_toc_lines,
        governance_remove_noise_lines=governance_remove_noise_lines,
        governance_unwrap_lines=governance_unwrap_lines,
        governance_remove_common_lines=governance_remove_common_lines,
        governance_unwrap_max_line_length=governance_unwrap_max_line_length,
        governance_noise_min_chars=governance_noise_min_chars,
        governance_noise_ratio_threshold=governance_noise_ratio_threshold,
        governance_common_lines_min_docs=governance_common_lines_min_docs,
        governance_common_lines_min_ratio=governance_common_lines_min_ratio,
    )
    pipeline_effective = resolve_pipeline_effective(
        dataset_metadata=dataset_meta,
        document_metadata={},
        request_overrides=pipeline_options,
    )
    pipeline_strategy_params: dict[str, Any] = dict(getattr(pipeline_effective, "chunk_strategy_params", {}) or {})
    if resolved_chunk_strategy == "parent_child":
        merged = dict(pipeline_strategy_params or {})
        if child_ratio is not None:
            merged["child_ratio"] = child_ratio
        if min_child_size is not None:
            merged["min_child_size"] = min_child_size

        if "child_ratio" in merged:
            r = _coerce_float_preview(merged.get("child_ratio"))
            if r is None:
                raise HTTPException(status_code=400, detail="child_ratio must be a float")
            if r < 0.05 or r > 1.0:
                raise HTTPException(status_code=400, detail="child_ratio must be between 0.05 and 1.0")
            chunker_kwargs["child_ratio"] = float(r)

        if "min_child_size" in merged:
            m = _coerce_int_preview(merged.get("min_child_size"))
            if m is None:
                raise HTTPException(status_code=400, detail="min_child_size must be an int")
            if m < 50 or m > 4000:
                raise HTTPException(status_code=400, detail="min_child_size must be between 50 and 4000")
            if m > int(chunk_size or 0):
                warnings_out.append("min_child_size > chunk_size; clamping to chunk_size")
                m = int(chunk_size or 0)
            chunker_kwargs["min_child_size"] = int(m)
    elif resolved_chunk_strategy == "separator":
        merged = dict(pipeline_strategy_params or {})
        if separator_preset is not None:
            merged["separator_preset"] = separator_preset
        if separator is not None:
            merged["separator"] = separator
        if keep_separator is not None:
            merged["keep_separator"] = keep_separator
        if separator_max_chunk_size is not None:
            merged["separator_max_chunk_size"] = separator_max_chunk_size

        preset = str(merged.get("separator_preset") or "").strip() or "paragraph"
        if preset != "custom":
            sep_value = SeparatorChunker.PRESET_SEPARATORS.get(preset)
            if sep_value is None:
                raise HTTPException(status_code=400, detail=f"Invalid separator_preset: {preset}")
        else:
            raw = merged.get("separator")
            if raw is None:
                raw = merged.get("separator_custom")
            sep_value = str(raw or "")
            if not sep_value:
                sep_value = "\n\n"
            sep_value = _decode_escaped_input_preview(sep_value)

        keep_sep = merged.get("keep_separator")
        keep_sep_norm = _coerce_bool_preview(keep_sep)
        keep_sep_bool = True if keep_sep_norm is None else bool(keep_sep_norm)

        max_chunk_size = merged.get("separator_max_chunk_size")
        if max_chunk_size is None:
            max_chunk_size = merged.get("max_chunk_size")
        max_chunk_size_int = int(_coerce_int_preview(max_chunk_size) or 0)

        separator_config = {
            "preset": preset,
            "separator": sep_value,
            "keep_separator": keep_sep_bool,
            "separator_max_chunk_size": max_chunk_size_int,
        }
    else:
        chunker_kwargs = _filter_chunker_kwargs_for_strategy(resolved_chunk_strategy, pipeline_strategy_params)
    extra_rules = list(getattr(pipeline_effective, "governance_regex_rules", None) or [])
    combined_rules = build_governance_rules(extra_rules) if extra_rules else None
    governance_kwargs = {
        **({"rules": combined_rules} if combined_rules else {}),
        "remove_toc_lines": pipeline_effective.governance_remove_toc_lines,
        "remove_noise_lines": pipeline_effective.governance_remove_noise_lines,
        "unwrap_lines": pipeline_effective.governance_unwrap_lines,
        # See /chunk-preview: disable common-line dropping in preview mode so
        # per-page duplicates remain visible to the tuning diagnostics.
        "remove_common_lines": False,
        "remove_boilerplate": pipeline_effective.governance_remove_boilerplate,
        "remove_images": pipeline_effective.governance_remove_images,
        "extract_frontmatter": pipeline_effective.governance_extract_frontmatter,
        "strip_frontmatter": pipeline_effective.governance_strip_frontmatter,
        "detect_language": pipeline_effective.governance_detect_language,
        "language_min_chars": pipeline_effective.governance_language_min_chars,
        "normalize_urls": pipeline_effective.governance_normalize_urls,
        "normalize_urls_strip_tracking": pipeline_effective.governance_normalize_urls_strip_tracking,
        "drop_duplicate_paragraphs": pipeline_effective.governance_drop_duplicate_paragraphs,
        "drop_duplicate_paragraphs_min_occurrences": pipeline_effective.governance_drop_duplicate_paragraphs_min_occurrences,
        "drop_duplicate_paragraphs_min_chars": pipeline_effective.governance_drop_duplicate_paragraphs_min_chars,
        "drop_duplicate_paragraphs_max_chars": pipeline_effective.governance_drop_duplicate_paragraphs_max_chars,
        "trim_references": pipeline_effective.governance_trim_references,
        "extract_keywords": pipeline_effective.governance_extract_keywords,
        "keywords_provider": pipeline_effective.governance_keywords_provider,
        "keywords_top_k": pipeline_effective.governance_keywords_top_k,
        "keywords_max_chars": pipeline_effective.governance_keywords_max_chars,
        "normalize_tables": pipeline_effective.governance_normalize_tables,
        "strip_code_line_numbers": pipeline_effective.governance_strip_code_line_numbers,
        "pii_anonymize": pipeline_effective.governance_pii_anonymize,
        "pii_mode": pipeline_effective.governance_pii_mode,
        "pii_mask": pipeline_effective.governance_pii_mask,
        "secrets_redact": pipeline_effective.governance_secrets_redact,
        "secrets_mode": pipeline_effective.governance_secrets_mode,
        "secrets_mask": pipeline_effective.governance_secrets_mask,
        "max_blank_lines": pipeline_effective.governance_max_blank_lines,
        "drop_outline_only": pipeline_effective.governance_drop_outline_only,
        "drop_outline_min_content_chars": pipeline_effective.governance_drop_outline_min_content_chars,
        "drop_outline_max_heading_ratio": pipeline_effective.governance_drop_outline_max_heading_ratio,
        "drop_low_density": pipeline_effective.governance_drop_low_density,
        "drop_low_density_threshold": pipeline_effective.governance_drop_low_density_threshold,
        "unwrap_max_line_length": pipeline_effective.governance_unwrap_max_line_length,
        "noise_min_chars": pipeline_effective.governance_noise_min_chars,
        "noise_ratio_threshold": pipeline_effective.governance_noise_ratio_threshold,
        "common_lines_min_docs": pipeline_effective.governance_common_lines_min_docs,
        "common_lines_min_ratio": pipeline_effective.governance_common_lines_min_ratio,
    }

    documents = [
        Document(
            page_content=str(item.get("page_content") or ""),
            metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            id=item.get("id") if isinstance(item.get("id"), str) else None,
        )
        for item in (parsed_docs_payload or [])
        if isinstance(item, dict)
    ]

    if pipeline_effective.governance_enabled:
        _gov_started = time.perf_counter()
        documents, _stats = governance_processor.clean_documents(
            documents,
            **governance_kwargs,
        )
        governance_duration_ms += int(max(0.0, (time.perf_counter() - _gov_started) * 1000.0))

    # Ensure stable per-doc indices for offset rebasing (handles missing/duplicate page numbers).
    _ensure_preview_page_indices(documents)

    if resolved_chunk_strategy == "separator":
        assert separator_config is not None
        preset = str(separator_config.get("preset") or "paragraph")
        sep_value = str(separator_config.get("separator") or "\n\n")
        keep_sep_bool = bool(separator_config.get("keep_separator"))
        max_chunk_size_int = int(separator_config.get("separator_max_chunk_size") or 0)
        chunker = SeparatorChunker(
            chunk_size=chunk_size,
            chunk_overlap=effective_chunk_overlap,
            separator=sep_value,
            keep_separator=keep_sep_bool,
            max_chunk_size=max_chunk_size_int,
        )
        strategy_params_out = {
            "separator_preset": preset,
            "separator": sep_value,
            "keep_separator": keep_sep_bool,
            "separator_max_chunk_size": max_chunk_size_int,
        }
    else:
        chunker = chunker_factory.get_chunker(
            resolved_chunk_strategy,
            chunk_size=chunk_size,
            chunk_overlap=effective_chunk_overlap,
            **chunker_kwargs,
        )
        strategy_params_out = dict(chunker_kwargs)
        if resolved_chunk_strategy == "parent_child":
            with contextlib.suppress(Exception):
                strategy_params_out = {
                    "child_ratio": float(chunker.child_ratio),
                    "min_child_size": int(chunker.min_child_size),
                    "child_size": int(chunker.child_size),
                    "child_overlap": int(chunker.child_overlap),
                }

    _chunk_started = time.perf_counter()
    chunks = chunker.split_documents(documents)
    chunking_duration_ms = int(max(0.0, (time.perf_counter() - _chunk_started) * 1000.0))

    # Optional: merge extremely short chunks with neighbors (preview-time).
    merge_min = max(0, int(getattr(pipeline_effective, "chunk_merge_small_min_chars", 0) or 0))
    if merge_min > 0 and documents and chunks:
        chunks = _merge_small_chunks_preview(documents=documents, chunks=chunks, min_chars=merge_min)

    # Align with ingestion: drop extremely short chunks (keep image-bearing chunks).
    min_chars = max(0, int(getattr(settings, "CHUNK_MIN_CHARS", 0) or 0))
    if min_chars > 0 and chunks:
        before = len(chunks)
        original_chunks = chunks
        filtered = []
        for c in original_chunks:
            content = (c.page_content or "").strip()
            if len(content) >= min_chars:
                filtered.append(c)
                continue
            meta = c.metadata or {}
            if (
                meta.get("img_id")
                or meta.get("image_id")
                or meta.get("image_url")
                or PREVIEW_IMAGE_REF_RE.search(content)
                or MINIO_IMAGE_REF_RE.search(content)
                or (DATA_IMAGE_PREFIX in content.lower())
            ):
                filtered.append(c)
        if not filtered and original_chunks:
            # Keep the longest chunk so preview stays consistent with ingestion.
            longest = max(original_chunks, key=lambda d: len((d.page_content or "").strip()))
            filtered = [longest]
        chunks = filtered
        dropped = before - len(chunks)
        if dropped:
            logger.info("Chunk preview(by-sha) dropped %s short chunks (<%s chars)", dropped, min_chars)

    # Optional response truncation for huge documents (UI safety / payload guardrail).
    total_chunks_full = len(chunks)
    chunks_truncated = False
    if int(max_chunks or 0) > 0 and len(chunks) > int(max_chunks):
        chunks_truncated = True
        warnings_out.append(f"chunks truncated to max_chunks={int(max_chunks)} (full={total_chunks_full})")
        chunks = chunks[: int(max_chunks)]

    # Merge original text: join parsed pages to keep start_index stable.
    page_texts: list[dict[str, object]] = []
    page_start_map: dict[object, int] = {}
    page_index_start_map: dict[int, int] = {}
    total_characters = 0
    original_text_value: str | None = None

    current_pos = 0
    for doc in documents:
        text = doc.page_content or ""
        meta = doc.metadata or {}
        page_num = meta.get("page") or meta.get("page_number")
        page_index = meta.get("page_index")
        page_texts.append(
            {
                "text": text,
                "page": page_num,
                "page_index": page_index,
                "start": current_pos,
                "end": current_pos + len(text),
            }
        )
        current_pos += len(text) + 1  # +1 for "\n" join separator

    total_characters = sum(len(str(p.get("text") or "")) for p in page_texts) + max(0, len(page_texts) - 1)
    page_index_start_map = {
        int(item.get("page_index")): int(item.get("start") or 0)
        for item in page_texts
        if item.get("page_index") is not None
    }
    for item in page_texts:
        p = item.get("page")
        if p is None:
            continue
        if p not in page_start_map:
            page_start_map[p] = int(item.get("start") or 0)
    if include_original and total_characters <= int(original_text_max_chars or 0):
        original_text_value = "\n".join([str(p.get("text") or "") for p in page_texts]) if page_texts else ""

    # Build response.
    _stats_started = time.perf_counter()
    from app.rag.chunking.quality_scorer import score_chunk_semantic_quality

    unit: Literal["chars", "tokens"] = "tokens" if resolved_chunk_strategy == "langchain_token" else "chars"
    chunk_items: list[ChunkPreviewItem] = []
    chunk_ranges: list[tuple[int, int]] = []
    length_samples: list[int] = []
    token_lengths: list[int] = []
    total_len = 0
    total_tokens_est = 0
    short_threshold = 40 if unit == "tokens" else 120
    short_count = 0
    seen_hashes: set[str] = set()
    duplicate_count = 0
    auto_counts: Counter[str] = Counter()
    semantic_quality_enabled = bool(include_chunks) or bool(include_review_signals)
    semantic_quality_max_chunks = 512
    prev_token_set: set[str] | None = None
    needs_review_count = 0

    for idx, chunk in enumerate(chunks):
        content = chunk.page_content or ""
        meta = chunk.metadata if isinstance(chunk.metadata, dict) else {}
        if not isinstance(chunk.metadata, dict):
            chunk.metadata = meta
        page_num = meta.get("page") or meta.get("page_number")
        page_index = meta.get("page_index")
        local_start = meta.get("start_char")
        local_end = meta.get("end_char")

        doc_base: int | None = None
        if page_index is not None:
            try:
                doc_base = page_index_start_map.get(int(page_index))
            except Exception:
                doc_base = None
        if doc_base is None and page_num is not None:
            doc_base = page_start_map.get(page_num)

        if doc_base is None:
            if meta.get("start_char") is not None:
                start_idx = int(meta.get("start_char"))
            else:
                start_idx = 0
        else:
            try:
                local = int(local_start) if local_start is not None else 0
            except Exception:
                local = 0
            start_idx = int(doc_base) + local

        end_idx = start_idx + len(content)
        if local_end is not None:
            try:
                end_local = int(local_end)
            except Exception:
                end_local = None
            if end_local is not None:
                end_idx = end_local if doc_base is None else int(doc_base) + end_local
        if end_idx < start_idx:
            end_idx = start_idx + len(content)
        if end_idx > start_idx:
            chunk_ranges.append((start_idx, end_idx))
        tokens_est = 0
        if content:
            tokens_est = (
                num_tokens_from_string(content)
                if resolved_chunk_strategy == "langchain_token"
                else estimate_tokens(content)
            )

        if semantic_quality_enabled and idx < semantic_quality_max_chunks:
            with contextlib.suppress(Exception):
                scores, cur_token_set = score_chunk_semantic_quality(
                    content,
                    tokens_est=int(tokens_est or 0),
                    prev_token_set=prev_token_set,
                )
                meta["semantic_quality"] = scores
                if bool(scores.get("needs_review")):
                    meta["needs_review"] = True
                    needs_review_count += 1
                prev_token_set = cur_token_set

        total_tokens_est += int(tokens_est or 0)
        if int(tokens_est or 0) > 0:
            token_lengths.append(int(tokens_est or 0))
        unit_len = int(tokens_est or 0) if unit == "tokens" else len(content)
        length_samples.append(unit_len)
        total_len += unit_len
        if unit_len > 0 and unit_len < short_threshold:
            short_count += 1

        stripped = content.strip()
        if stripped:
            digest = hashlib.sha256(stripped.encode("utf-8", "ignore")).hexdigest()
            if digest in seen_hashes:
                duplicate_count += 1
            else:
                seen_hashes.add(digest)

        if resolved_chunk_strategy == "auto":
            selected = meta.get("chunk_strategy_selected")
            if isinstance(selected, str) and selected.strip():
                auto_counts[selected.strip().lower()] += 1

        if bool(include_chunks) or bool(include_review_signals):
            chunk_items.append(ChunkPreviewItem(
                index=idx,
                content=content,
                length=len(content),
                hierarchy_basis=(str(meta.get("hierarchy_basis")).strip() if meta.get("hierarchy_basis") is not None else None),
                tokens_est=tokens_est,
                start_index=start_idx,
                end_index=end_idx,
                page_number=page_num,
                metadata=chunk.metadata
            ))

    if semantic_quality_enabled and needs_review_count > 0:
        warnings_out.append(f"{int(needs_review_count)} chunks flagged needs_review (semantic heuristics)")

    sorted_lengths = sorted(length_samples)
    # Token stats (always derived from per-chunk `tokens_est`, independent of `unit`).
    token_stats: dict[str, Any] | None = None
    with contextlib.suppress(Exception):
        from app.services.chunking_stats_utils import compute_chunking_stats_from_lengths
        from app.services.dataset_profile_utils import CHUNK_TOKEN_BINS

        token_stats = compute_chunking_stats_from_lengths(
            token_lengths,
            short_threshold=40,
            duplicate_count=int(duplicate_count),
            unit="tokens",
            bins=CHUNK_TOKEN_BINS,
        )
    if sorted_lengths:
        def _pct(p: int) -> int:
            if not sorted_lengths:
                return 0
            pp = max(0, min(100, int(p)))
            pos = int((pp / 100.0) * (len(sorted_lengths) - 1))
            pos = max(0, min(len(sorted_lengths) - 1, pos))
            return int(sorted_lengths[pos] or 0)

        coverage = _compute_chunk_coverage_metrics_from_ranges(chunk_ranges, total_characters=total_characters)
        histogram = _compute_chunk_length_histogram(sorted_lengths, unit=unit, target_bins=8)
        stats = ChunkPreviewStats(
            unit=unit,
            count=len(sorted_lengths),
            total=int(total_len),
            min=int(sorted_lengths[0]),
            max=int(sorted_lengths[-1]),
            avg=int(round(total_len / len(sorted_lengths))) if sorted_lengths else 0,
            median=_pct(50),
            p10=_pct(10),
            p90=_pct(90),
            p95=_pct(95),
            total_tokens_est=int(total_tokens_est),
            short_count=int(short_count),
            duplicate_count=int(duplicate_count),
            histogram=histogram,
            **coverage,
        )
    else:
        coverage = _compute_chunk_coverage_metrics_from_ranges(chunk_ranges, total_characters=total_characters)
        stats = ChunkPreviewStats(unit=unit, **coverage)
    stats_duration_ms = int(max(0.0, (time.perf_counter() - _stats_started) * 1000.0))

    auto_selected_strategy: str | None = None
    if resolved_chunk_strategy == "auto" and auto_counts:
        auto_selected_strategy = auto_counts.most_common(1)[0][0]

    original_text_truncated_val = bool(
        include_original
        and original_text_value is None
        and total_characters > int(original_text_max_chars or 0)
    )
    original_text_cleaned_value: str | None = None
    if original_text_value is not None and "@@" in original_text_value and "##" in original_text_value:
        if POSITION_TAG_RE.search(original_text_value):
            original_text_cleaned_value = POSITION_TAG_RE.sub("", original_text_value)
    quality_gate, recommendations, recommendation_patches = _compute_chunk_preview_quality(
        stats=stats,
        total_chunks=len(chunks),
        total_characters=int(total_characters or 0),
        chunk_size=int(chunk_size or 0),
        chunk_overlap=int(effective_chunk_overlap or 0),
        original_text_included=original_text_value is not None,
        original_text_truncated=original_text_truncated_val,
        original_text_max_chars=int(original_text_max_chars or 0),
    )

    review_signals: ChunkPreviewReviewSignals | None = None
    if bool(include_review_signals):
        signals_strategy = auto_selected_strategy or resolved_chunk_strategy
        with contextlib.suppress(Exception):
            review_signals = _compute_chunk_preview_review_signals(
                chunk_items=chunk_items,
                unit="tokens" if resolved_chunk_strategy == "langchain_token" else "chars",
                strategy=str(signals_strategy or ""),
            )

    preview_duration_ms_val = int(max(0.0, (time.perf_counter() - preview_started) * 1000.0))
    with contextlib.suppress(Exception):
        timing_parts: list[str] = []
        timing_parts.append(f"upload;dur={int(upload_duration_ms)}")
        timing_parts.append(f"parse;dur={int(parse_duration_ms)}")
        timing_parts.append(f"govern;dur={int(governance_duration_ms)}")
        timing_parts.append(f"chunk;dur={int(chunking_duration_ms)}")
        timing_parts.append(f"stats;dur={int(stats_duration_ms)}")
        timing_parts.append(f"total;dur={int(preview_duration_ms_val)}")
        response.headers["Server-Timing"] = ", ".join(timing_parts)

    return ChunkPreviewResponse(
        filename=safe_name,
        file_type=file_ext.lstrip('.'),
        file_size=int(file_size or 0),
        file_sha256=sha,
        parse_cache_hit=bool(parse_cache_hit),
        parse_cache_age_ms=parse_cache_age_ms,
        preview_duration_ms=preview_duration_ms_val,
        upload_duration_ms=int(upload_duration_ms),
        parse_duration_ms=int(parse_duration_ms),
        governance_duration_ms=int(governance_duration_ms),
        chunking_duration_ms=int(chunking_duration_ms),
        stats_duration_ms=int(stats_duration_ms),
        total_chunks=len(chunks),
        total_chunks_full=int(total_chunks_full),
        chunks_truncated=bool(chunks_truncated),
        chunks_max_count=int(max_chunks or 0),
        total_characters=total_characters,
        params=ChunkPreviewParams(
            chunk_size=chunk_size,
            chunk_overlap=effective_chunk_overlap,
            unit="tokens" if resolved_chunk_strategy == "langchain_token" else "chars",
            strategy_params=strategy_params_out,
        ),
        chunks=(chunk_items if bool(include_chunks) else []),
        stats=stats,
        chunking_stats_tokens=token_stats,
        auto_selected_strategy=auto_selected_strategy,
        warnings=warnings_out,
        review_signals=review_signals,
        quality_gate=quality_gate,
        recommendations=recommendations,
        recommendation_patches=recommendation_patches,
        original_text=original_text_value,
        original_text_cleaned=original_text_cleaned_value,
        original_text_included=original_text_value is not None,
        original_text_truncated=original_text_truncated_val,
        original_text_max_chars=int(original_text_max_chars or 0),
        parser_backend=resolved_backend,
        chunk_strategy=resolved_chunk_strategy,
    )
