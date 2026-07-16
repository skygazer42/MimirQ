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
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id_from_headers
from app.api.schemas.document import (
    DocumentPipelineOptions,
)
from app.api.utils.upload import save_upload_file_with_hash
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
from app.models.dataset import Dataset, DatasetPermissionEnum
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk, DocumentPermission
from app.parsing.factory import parser_factory
from app.parsing.processors.processor import document_processor
from app.parsing.subprocess_runner import run_subprocess_worker
from app.rag.chunking.factory import chunker_factory
from app.rag.core.logging import get_logger
from app.rag.kg.pipeline import extract_events
from app.rag.preprocessing.html_canonical import extract_canonical_url, normalize_url_for_dedup
from app.rag.preprocessing.processor import governance_processor
from app.rag.preprocessing.rules import build_governance_rules
from app.services.dataset_precheck_ingestion_suggestion import apply_ingestion_policy_suggestion
from app.services.dataset_precheck_scan_runner import run_dataset_precheck_scan
from app.services.dataset_service import EDIT_ROLES, DatasetService
from app.services.document_permission_service import DocumentGroupPermissionService
from app.services.document_preview_utils import (
    _compute_chunk_preview_quality,
    _materialize_extracted_images_for_preview,
    _materialize_local_images_for_preview,
)
from app.services.index_audit_service import build_index_drift_marker
from app.services.ingestion_policy import (
    match_ingestion_rule,
    parse_ingestion_policy_from_metadata,
    resolve_governance_profile_ref,
)
from app.services.ingestion_run_service import IngestionRunService
from app.services.pipeline_config import (
    build_indexing_options,
    merge_pipeline_options,
    resolve_pipeline_effective,
    upsert_pipeline_metadata,
)
from app.services.tenant_group_service import TenantGroupService
from app.storage.object.minio import minio_service
from app.tasks.queue import enqueue_document_processing
from app.types.pipeline import PipelineOptions

logger = get_logger("api.documents")

_background_processing_semaphores: dict[int, tuple[int, asyncio.Semaphore]] = {}


def _get_background_processing_semaphore() -> asyncio.Semaphore:
    limit = max(1, int(getattr(settings, "API_DOCUMENT_BACKGROUND_MAX_CONCURRENCY", 2) or 2))
    loop_id = id(asyncio.get_running_loop())
    cached = _background_processing_semaphores.get(loop_id)
    if cached is None or cached[0] != limit:
        sem = asyncio.Semaphore(limit)
        _background_processing_semaphores[loop_id] = (limit, sem)
        return sem
    return cached[1]


async def run_document_processing_limited(*args: Any, **kwargs: Any) -> Any:
    sem = _get_background_processing_semaphore()
    async with sem:
        return await document_processor.process_document(*args, **kwargs)

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
UUID_PATTERN = r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
PREVIEW_IMAGE_REF_RE = re.compile(rf"(?:https?://[^\s)\"']+)?/api/v1/documents/image/({UUID_PATTERN})")
MINIO_IMAGE_REF_RE = re.compile(r"(?:https?://[^\s)\"']+)?/api/v1/documents/image-url/([^\s)\"']+)")
# Position tags emitted by some PDF parsers (used for PDF overlay highlighting).
POSITION_TAG_RE = re.compile(r"@@([0-9-]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##")

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
PREVIEW_IMAGE_EXTENSIONS = [".png", ".jpg", IMAGE_FILE_EXT_JPEG, IMAGE_FILE_EXT_WEBP, ".gif", ".bmp"]
CHUNK_PATCH_OPERATION = 'chunk.patch'


def _existing_minio_image_refs(text: str) -> list[str]:
    existing: list[str] = []
    for match in MINIO_IMAGE_REF_RE.finditer(text):
        value = (match.group(1) or "").strip()
        if value and value not in existing:
            existing.append(value)
    return existing


def _preview_image_matches(text: str) -> list[re.Match[str]]:
    if "/api/v1/documents/image/" not in text:
        return []
    matches = list(PREVIEW_IMAGE_REF_RE.finditer(text))
    max_inline_images = max(0, int(getattr(settings, "MAX_INLINE_IMAGES", 0) or 0))
    return matches[:max_inline_images] if max_inline_images and len(matches) > max_inline_images else matches


def _preview_image_max_bytes() -> int:
    max_bytes = int(getattr(settings, "MAX_INLINE_IMAGE_BYTES", 10_000_000) or 10_000_000)
    return max(1_000_000, max_bytes)


def _preview_local_image_id(raw_id: str | None) -> str | None:
    if not raw_id:
        return None
    try:
        return uuid.UUID(raw_id).hex
    except ValueError:
        return None


def _find_preview_image_path(images_dir: Path, local_id: str) -> Path | None:
    for ext in PREVIEW_IMAGE_EXTENSIONS:
        candidate = images_dir / f"{local_id}{ext}"
        if candidate.exists() and candidate.is_file():
            return candidate

    try:
        for candidate in images_dir.glob(f"{local_id}.*"):
            if candidate.suffix.lower() in PREVIEW_IMAGE_EXTENSIONS and candidate.exists() and candidate.is_file():
                return candidate
    except OSError:
        return None
    return None


def _read_preview_image_bytes(img_path: Path, max_bytes: int) -> bytes | None:
    try:
        if img_path.stat().st_size > max_bytes:
            return None
        raw = img_path.read_bytes()
    except OSError:
        return None
    if not raw or len(raw) > max_bytes:
        return None
    return raw


def _convert_preview_image_to_jpeg(local_id: str, raw: bytes) -> bytes | None:
    from io import BytesIO

    from PIL import Image as PILImage  # type: ignore[import-untyped]

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
        return out.getvalue()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed converting preview image %s to JPEG: %s", local_id, str(exc)[:200])
        return None
    finally:
        for to_close in (converted, img):
            if to_close is None:
                continue
            with contextlib.suppress(Exception):
                to_close.close()


def _upload_preview_image_to_minio(
    *,
    image_bytes: bytes,
    tenant_id: str,
    dataset_id: str,
    document_id: str,
    digest_to_img_id: dict[str, str],
    start_index: int,
) -> tuple[str | None, int]:
    digest = hashlib.sha256(image_bytes).hexdigest()
    img_id = digest_to_img_id.get(digest)
    if img_id:
        return img_id, start_index

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
    except Exception as exc:  # noqa: BLE001
        logger.warning("Preview image upload to MinIO failed; skipping image: %s", str(exc)[:200])
        return None, start_index
    digest_to_img_id[digest] = img_id
    return img_id, start_index


def _replace_preview_ref(match: re.Match[str], local_id_to_img_id: dict[str, str]) -> str:
    local_id = _preview_local_image_id(match.group(1))
    if not local_id:
        return match.group(0)
    img_id = local_id_to_img_id.get(local_id)
    if not img_id:
        return match.group(0)
    return f"/api/v1/documents/image-url/{img_id}"


def _resolve_preview_image_ref(
    *,
    local_id: str,
    images_dir: Path,
    max_bytes: int,
    local_id_to_img_id: dict[str, str],
    digest_to_img_id: dict[str, str],
    tenant_id: str,
    dataset_id: str,
    document_id: str,
    start_index: int,
) -> tuple[str | None, int]:
    img_id = local_id_to_img_id.get(local_id)
    if img_id:
        return img_id, start_index

    img_path = _find_preview_image_path(images_dir, local_id)
    if img_path is None:
        return None, start_index

    raw = _read_preview_image_bytes(img_path, max_bytes)
    if raw is None:
        return None, start_index

    image_bytes = _convert_preview_image_to_jpeg(local_id, raw)
    if image_bytes is None:
        return None, start_index

    img_id, start_index = _upload_preview_image_to_minio(
        image_bytes=image_bytes,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        digest_to_img_id=digest_to_img_id,
        start_index=start_index,
    )
    if img_id:
        local_id_to_img_id[local_id] = img_id
    return img_id, start_index


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
    Convert preview-time local image refs into persisted MinIO image-url refs.

    Manual chunks share the preview image cache with the document preview
    endpoint. When MinIO is enabled, persisted chunks must not retain local
    `/documents/image/{uuid}` refs because those files are temporary.
    """
    if not settings.MINIO_ENABLED:
        return text, [], start_index
    if not isinstance(text, str) or not text:
        return text, [], start_index

    existing = _existing_minio_image_refs(text)
    if existing:
        return text, existing, start_index

    matches = _preview_image_matches(text)
    if not matches:
        return text, [], start_index

    max_bytes = _preview_image_max_bytes()
    referenced_img_ids: list[str] = []
    seen_local_ids: set[str] = set()

    for match in matches:
        local_id = _preview_local_image_id(match.group(1))
        if not local_id:
            continue

        if local_id in seen_local_ids:
            continue
        seen_local_ids.add(local_id)

        img_id, start_index = _resolve_preview_image_ref(
            local_id=local_id,
            images_dir=images_dir,
            max_bytes=max_bytes,
            local_id_to_img_id=local_id_to_img_id,
            digest_to_img_id=digest_to_img_id,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            start_index=start_index,
        )
        if not img_id:
            continue

        if img_id and img_id not in referenced_img_ids:
            referenced_img_ids.append(img_id)

    if not referenced_img_ids:
        return text, [], start_index

    return PREVIEW_IMAGE_REF_RE.sub(lambda match: _replace_preview_ref(match, local_id_to_img_id), text), referenced_img_ids, start_index


def _asset_cache_control(*, max_age: int) -> str:
    del max_age
    return "private, no-store"


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant id") from exc


def _asset_request_header_account(request, *, is_production: bool) -> str | None:
    account_id = (request.headers.get("x-user-id") or "").strip() or None
    if is_production and not account_id:
        raise HTTPException(status_code=401, detail="X-User-ID header required")
    return account_id


def _asset_request_authorization(request) -> str:
    authorization = (request.headers.get("authorization") or "").strip()
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")
    return authorization


async def _resolve_account_id_for_asset_request(request, *, tenant_id: UUID | None = None) -> str | None:
    """
    Resolve account id for asset endpoints that may be requested by <img src>.

    - AUTH_MODE=header: allow anonymous in local/dev (headers can't be set by <img>).
    - AUTH_MODE=jwt: require an Authorization header; query-string bearer tokens are unsupported.
    """
    is_production = is_production_env()
    auth_mode = (getattr(settings, "AUTH_MODE", "jwt") or "jwt").lower()

    if auth_mode == "header":
        return _asset_request_header_account(request, is_production=is_production)

    authorization = _asset_request_authorization(request)
    tenant_value = str(tenant_id).strip() if tenant_id is not None else None
    try:
        return await get_current_account_id_from_headers(
            authorization=authorization,
            x_user_id=None,
            x_tenant_id=tenant_value,
        )
    except HTTPException:
        raise HTTPException(status_code=401, detail="Authentication required") from None


def _get_tenant_id_from_request_if_provided(request) -> UUID | None:
    """
    Return tenant id from header/query if explicitly provided; otherwise None.
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


def _resolve_tenant_id_for_asset_request(request) -> UUID:
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


def _merge_user_metadata_patch(*, current: dict, patch: dict, replace: bool) -> dict:
    if replace:
        return dict(patch or {})

    next_user = dict(current or {})
    for key, value in (patch or {}).items():
        if value is None:
            next_user.pop(key, None)
        else:
            next_user[key] = value
    return next_user


def _normalize_user_metadata_tags(next_user: dict, *, replace: bool) -> None:
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


def _normalize_user_metadata_notes(next_user: dict) -> None:
    notes = next_user.get("notes")
    if isinstance(notes, str):
        val = notes.strip()
        if not val:
            next_user.pop("notes", None)
        else:
            next_user["notes"] = val[:20_000]


def _apply_user_metadata_patch(*, current: dict, patch: dict, replace: bool) -> dict:
    next_user = _merge_user_metadata_patch(current=current, patch=patch, replace=replace)
    _normalize_user_metadata_tags(next_user, replace=replace)
    _normalize_user_metadata_notes(next_user)
    return next_user


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
    max_len = int(getattr(settings, "PIPELINE_FORM_JSON_MAX_CHARS", 200_000) or 200_000)
    if max_len > 0 and len(raw) > max_len:
        raise HTTPException(status_code=400, detail="pipeline is too large")
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("pipeline must be a JSON object")
        allowed = DocumentPipelineOptions.model_fields
        normalized = {key: value for key, value in payload.items() if key in allowed}
        return DocumentPipelineOptions.model_validate(normalized)
    except Exception as exc:  # noqa: BLE001
        msg = (str(exc) or exc.__class__.__name__)[:200]
        detail = "Invalid pipeline JSON" if is_production_env() else f"Invalid pipeline JSON: {msg}"
        raise HTTPException(status_code=400, detail=detail) from exc


def _compute_pipeline_hash(doc_metadata: dict) -> str:
    relevant = {
        "parser_backend": doc_metadata.get("parser_backend"),
        "parser_backend_requested": doc_metadata.get("parser_backend_requested"),
        "chunk_strategy": doc_metadata.get("chunk_strategy"),
        "chunk_strategy_requested": doc_metadata.get("chunk_strategy_requested"),
        "pipeline": doc_metadata.get("pipeline") or {},
    }
    raw = json.dumps(relevant, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _is_uploaded_only_pending_document(document: Any) -> bool:
    """
    True for files registered by upload-only mode but not yet queued/processed.

    Those documents are persisted as `status=pending` so they appear in ingestion
    lists, but they are not active processing jobs. Reingest may safely patch
    their pipeline and start processing them later.
    """
    if str(getattr(document, "status", "") or "").strip().lower() != "pending":
        return False

    meta = getattr(document, "doc_metadata", None)
    meta = meta if isinstance(meta, dict) else {}
    if str(meta.get("ingest_stage") or "").strip() != "uploaded_only":
        return False
    if str(meta.get("task_id") or "").strip():
        return False

    current_stage = str(getattr(document, "current_stage", "") or "").strip().lower()
    if current_stage and current_stage not in {"uploaded_only", "registered"}:
        return False

    return not bool(meta.get("active_pipeline_ready"))


def _is_idle_pending_document(document: Any) -> bool:
    """
    True for pending documents that are persisted but not attached to a live job.

    Legacy imports and upload-only flows can leave a document as `status=pending`
    without `ingest_stage=uploaded_only`. They are safe to reconfigure only when
    no queue/task marker, active stage, or progress indicates work is running.
    """
    if str(getattr(document, "status", "") or "").strip().lower() != "pending":
        return False

    meta = getattr(document, "doc_metadata", None)
    meta = meta if isinstance(meta, dict) else {}
    if str(meta.get("task_id") or "").strip() or str(meta.get("kg_task_id") or "").strip():
        return False

    current_stage = str(getattr(document, "current_stage", "") or "").strip().lower()
    if current_stage and current_stage not in {"uploaded_only", "registered"}:
        return False

    try:
        progress = int(getattr(document, "processing_progress", 0) or 0)
    except (TypeError, ValueError):
        return False
    if progress > 0:
        return False

    return not bool(meta.get("active_pipeline_ready"))


def _is_reprocessable_pending_document(document: Any) -> bool:
    return _is_uploaded_only_pending_document(document) or _is_idle_pending_document(document)


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


def _to_pipeline_options(
    *,
    pipeline: DocumentPipelineOptions | None = None,
    overrides: PipelineOptionOverrides | None = None,
    **legacy_overrides: Any,
) -> PipelineOptions:
    resolved_overrides = _resolve_pipeline_option_overrides(overrides=overrides, legacy_overrides=legacy_overrides)
    overrides_dict = {k: v for k, v in asdict(resolved_overrides).items() if v is not None}

    if pipeline is None:
        pipeline = DocumentPipelineOptions(**overrides_dict) if overrides_dict else None
    elif overrides_dict:
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


def _validate_chunk_params(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_overlap >= chunk_size:
        raise HTTPException(
            status_code=400,
            detail=CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL,
        )


def _is_dataset_owner(dataset: Dataset | None, account_id: str) -> bool:
    return dataset is not None and str(getattr(dataset, "owner_id", "") or "") == account_id


def _document_acl_mode(document: DBDocument) -> str:
    return (str(getattr(document, "access_mode", "") or "")).strip().lower()


def _is_document_owner(document: DBDocument, account_id: str) -> bool:
    owner_id = (str(getattr(document, "owner_id", "") or "")).strip()
    return bool(owner_id and owner_id == account_id)


def _document_partial_member_exists(db: Session, *, tenant_id: UUID, account_id: str, document: DBDocument) -> bool:
    return (
        db.query(DocumentPermission)
        .filter(
            DocumentPermission.tenant_id == tenant_id,
            DocumentPermission.document_id == document.id,
            DocumentPermission.account_id == account_id,
        )
        .first()
        is not None
    )


def _document_partial_group_allowed(db: Session, *, tenant_id: UUID, account_id: str, document: DBDocument) -> bool:
    group_ids = TenantGroupService.resolve_account_group_ids(db, tenant_id=tenant_id, account_id=account_id)
    if not group_ids:
        return False

    allowlist_groups = DocumentGroupPermissionService.get_document_partial_group_list(
        db,
        tenant_id,
        document.id,
    )
    if not allowlist_groups:
        return False
    allowed = set(allowlist_groups)
    return any(gid in allowed for gid in group_ids)


def _document_partial_access_allowed(db: Session, *, tenant_id: UUID, account_id: str, document: DBDocument) -> bool:
    if _document_partial_member_exists(db, tenant_id=tenant_id, account_id=account_id, document=document):
        return True
    return _document_partial_group_allowed(db, tenant_id=tenant_id, account_id=account_id, document=document)


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
    if _is_dataset_owner(dataset, account_id):
        return

    mode = _document_acl_mode(document)
    if not mode or mode in {"inherit", "all_team_members"}:
        return

    if _is_document_owner(document, account_id):
        return

    if mode == "only_me":
        raise HTTPException(status_code=403, detail=NO_DOCUMENT_ACCESS_DETAIL)

    if mode == "partial_members":
        if _document_partial_access_allowed(db, tenant_id=tenant_id, account_id=account_id, document=document):
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


@dataclass
class LocalHtmlIngestFile:
    file_id: UUID
    file_path: Path
    file_ext: str
    filename: str
    file_size: int
    fetched_at_iso: str


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
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}")
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
            raise HTTPException(status_code=500, detail=f"failed to finalize downloaded file: {str(exc)[:120]}") from exc


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

    default_pb_eff = dataset_default_pb or str(getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto").strip().lower() or "auto"
    default_cs_eff = dataset_default_cs or str(getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive").strip().lower() or "langchain_recursive"
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
        ingestion_run = IngestionRunService.create_run(
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
    pipeline_options: PipelineOptions,
    ingestion_meta: dict[str, Any] | None,
    ingestion_run_id: UUID | None,
    ingestion_kind: str | None,
    default_kind: str,
) -> tuple[dict[str, Any], str]:
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


def _create_pending_document_record(
    *,
    db: Session,
    file_id: UUID,
    tenant_id: UUID,
    dataset: Dataset,
    filename: str,
    file_ext: str,
    file_size: int,
    file_path: Path,
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
    db.add(db_document)
    db.commit()
    db.refresh(db_document)
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
        IngestionRunService.add_document(
            db,
            tenant_id=tenant_id,
            run_id=ingestion_run_id,
            document_id=db_document.id,
            source_ref=source_ref,
            initial_status=str(getattr(db_document, "status", "") or "pending"),
            doc_meta=dict(doc_metadata),
        )


async def _schedule_document_processing(
    *,
    db: Session,
    background_tasks: BackgroundTasks | None,
    tenant_id: UUID,
    document_id: UUID,
    file_path: Path,
    requested_by: str,
    pipeline_hash: str,
    parser_backend: str,
    chunk_strategy: str,
    db_document: DBDocument,
) -> None:
    job_id = f"doc:{tenant_id}:{document_id}:{pipeline_hash}"
    task_id = await enqueue_document_processing(
        tenant_id=tenant_id,
        document_id=document_id,
        requested_by=requested_by,
        job_id=job_id,
    )
    if task_id:
        meta = dict(db_document.doc_metadata or {})
        meta["task_id"] = task_id
        db_document.doc_metadata = meta
        db.commit()
        db.refresh(db_document)
        return

    if background_tasks is not None:
        background_tasks.add_task(
            run_document_processing_limited,
            file_path,
            document_id,
            tenant_id,
            parser_backend,
            chunk_strategy,
        )
        return

    await document_processor.process_document(
        file_path=file_path,
        document_id=document_id,
        tenant_id=tenant_id,
        parser_backend=parser_backend,
        chunk_strategy=chunk_strategy,
        db=db,
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
            max_bytes=int(getattr(settings, "URL_INGEST_MAX_BYTES", 0) or settings.MAX_FILE_SIZE),
            timeout_sec=float(getattr(settings, "URL_INGEST_TIMEOUT_SEC", 30.0) or 30.0),
            follow_redirects=bool(getattr(settings, "URL_INGEST_FOLLOW_REDIRECTS", False)),
            user_agent=(body.user_agent or None),
            extra_headers=(body.fetch_headers or None),
        ),
    )

    content_type = (downloaded.content_type or "").split(";", 1)[0].strip().lower()
    file_ext = _resolve_url_file_ext(filename=body.filename, url=url, content_type=content_type)
    final_path = upload_dir / f"{file_id}{file_ext}"
    _finalize_url_download(temp_path, final_path)
    return UrlIngestFile(
        file_id=file_id,
        final_path=final_path,
        file_ext=file_ext,
        downloaded=downloaded,
        content_type=content_type,
        fetched_at_iso=datetime.now(UTC).isoformat(),
    )


def _write_local_html_ingest_file(*, body: LocalHtmlIngestRequest, tenant_id: UUID) -> LocalHtmlIngestFile:
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    data = str(body.html or "").encode("utf-8", "ignore")
    if int(getattr(settings, "MAX_FILE_SIZE", 0) or 0) > 0 and len(data) > int(settings.MAX_FILE_SIZE):
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
        fetched_at_iso=datetime.now(UTC).isoformat(),
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
    return {
        "parser_backend": pipeline.parser_backend,
        "parser_backend_requested": str(body.parser_backend or "").lower(),
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
    return {
        "parser_backend": pipeline.parser_backend,
        "parser_backend_requested": str(body.parser_backend or "").lower(),
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
    file_path: Path,
    source_ref: str | None,
    doc_metadata: dict[str, Any],
    pipeline_hash: str,
    pipeline: ResolvedDocumentPipeline,
    ingestion_run_id: UUID | None,
) -> DBDocument:
    db_document = _create_pending_document_record(
        db=db,
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
    _add_document_to_ingestion_run(
        db=db,
        tenant_id=tenant_id,
        ingestion_run_id=ingestion_run_id,
        db_document=db_document,
        source_ref=source_ref,
        doc_metadata=doc_metadata,
    )
    await _schedule_document_processing(
        db=db,
        background_tasks=background_tasks,
        tenant_id=tenant_id,
        document_id=file_id,
        file_path=file_path,
        requested_by=account_id,
        pipeline_hash=pipeline_hash,
        parser_backend=pipeline.parser_backend,
        chunk_strategy=pipeline.chunk_strategy,
        db_document=db_document,
    )
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
    if not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    url = await validate_url_for_ingest(str(body.url or ""))
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, body.dataset_id)
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
        pipeline_options=prepared.policy.pipeline_options,
        ingestion_meta=prepared.policy.ingestion_meta,
        ingestion_run_id=ingestion_run_id,
        ingestion_kind=ingestion_kind,
        default_kind="upload_url",
    )

    file_size = int(ingest_file.downloaded.size_bytes)
    _enforce_url_upload_quota(db, tenant_id=tenant_id, additional_bytes=file_size, final_path=ingest_file.final_path)

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
        file_path=ingest_file.final_path,
        source_ref=url,
        doc_metadata=doc_metadata,
        pipeline_hash=pipeline_hash,
        pipeline=prepared.pipeline,
        ingestion_run_id=ingestion_run_id,
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
    docs = _duplicate_document_query(db, tenant_id=tenant_id, dataset_id=dataset_id).limit(max(1, int(max_scan or 5000))).all()
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
            .filter(DBDocument.doc_metadata["file_sha256"].astext == sha)  # type: ignore[attr-defined]
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
                str(meta.get("file_sha256") or "").strip().lower() == sha
                and str(meta.get("pipeline_hash") or "").strip() == ph
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
            .filter(DBDocument.doc_metadata["file_sha256"].astext == sha)  # type: ignore[attr-defined]
            .first()
        )
    except Exception:
        return _scan_duplicate_documents(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            max_scan=max_scan,
            predicate=lambda meta: str(meta.get("file_sha256") or "").strip().lower() == sha,
        )


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
    if not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    dataset = _resolve_writable_dataset(db, tenant_id, account_id, body.dataset_id)
    ingest_file = _write_local_html_ingest_file(body=body, tenant_id=tenant_id)
    content_type = "text/html"
    source_url = (str(body.source_url or "").strip() or None)
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
        pipeline_options=prepared.policy.pipeline_options,
        ingestion_meta=prepared.policy.ingestion_meta,
        ingestion_run_id=ingestion_run_id,
        ingestion_kind=ingestion_kind,
        default_kind="connector_html",
    )

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
        file_path=ingest_file.file_path,
        source_ref=(source_url or ingest_file.filename)[:1000] if (source_url or ingest_file.filename) else None,
        doc_metadata=doc_metadata,
        pipeline_hash=pipeline_hash,
        pipeline=prepared.pipeline,
        ingestion_run_id=ingestion_run_id,
    )


document_upload = importlib.import_module("app.api.v1.document_upload")
router.include_router(document_upload.router)

upload_document = document_upload.upload_document
upload_document_from_url = document_upload.upload_document_from_url
upload_documents_batch = document_upload.upload_documents_batch

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
