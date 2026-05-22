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
from app.api.utils.url_ingest import download_url_to_path, validate_url_for_ingest
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
from app.services.audit_log_service import audit_log_event
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
from app.services.indexer import Indexer
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
from app.storage.object.minio import is_minio_uri, minio_service, parse_minio_uri
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

    existing: list[str] = []
    for match in MINIO_IMAGE_REF_RE.finditer(text):
        value = (match.group(1) or "").strip()
        if value and value not in existing:
            existing.append(value)
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

    for match in matches:
        raw_id = match.group(1)
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
                raw = img_path.read_bytes()
            except OSError:
                continue
            if not raw or len(raw) > max_bytes:
                continue

            from io import BytesIO

            try:
                from PIL import Image as PILImage  # type: ignore[import-untyped]
            except ImportError:
                logger.warning("Pillow not available; skipping preview image upload to MinIO")
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
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed converting preview image %s to JPEG: %s", local_id, str(exc)[:200])
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
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Preview image upload to MinIO failed; skipping image: %s", str(exc)[:200])
                    continue
                digest_to_img_id[digest] = img_id

            local_id_to_img_id[local_id] = img_id

        if img_id and img_id not in referenced_img_ids:
            referenced_img_ids.append(img_id)

    if not referenced_img_ids:
        return text, [], start_index

    def _replace_preview_ref(match: re.Match[str]) -> str:
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

    return PREVIEW_IMAGE_REF_RE.sub(_replace_preview_ref, text), referenced_img_ids, start_index


def _asset_cache_control(*, token_in_url: bool, max_age: int) -> str:
    if token_in_url:
        return "no-store"
    if max_age > 0:
        return f"private, max-age={max_age}"
    return "no-cache"


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant id") from exc


async def _resolve_account_id_for_asset_request(request, *, tenant_id: UUID | None = None) -> str | None:
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
    raw = str(filename or "")
    if not raw:
        return []
    if "\x7f" in raw or any(ord(ch) < 32 for ch in raw):
        raise HTTPException(status_code=400, detail=FILENAME_INVALID_CHARS_DETAIL)

    cleaned = raw.replace("\\", "/").strip()
    if not cleaned:
        return []

    parts = [p.strip() for p in cleaned.split("/") if p.strip() and p.strip() != "."]
    if parts and _WINDOWS_DRIVE_LETTER_RE.fullmatch(parts[0]):
        parts = parts[1:]
    if not parts:
        return []

    stack: list[str] = []
    for p in parts:
        if p == "..":
            if stack:
                stack.pop()
            continue
        stack.append(p)

    if len(stack) == 2 and stack[0].lower() == "fakepath":
        stack = [stack[1]]

    return stack


def _normalize_upload_key(filename: str) -> str:
    parts = _normalize_upload_path_parts(filename)
    if not parts:
        return _sanitize_filename(filename)
    key = "/".join(parts)
    if len(key) > _UPLOAD_SOURCE_PATH_MAX_LEN:
        key = key[:_UPLOAD_SOURCE_PATH_MAX_LEN]
    return key


def _normalize_upload_source_path(filename: str) -> str | None:
    key = _normalize_upload_key(filename)
    if "/" not in key:
        return None
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
        return DocumentPipelineOptions.model_validate_json(raw)
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

    file_ext = _ext_from_filename(body.filename)
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
    doc_metadata.setdefault("active_pipeline_hash", pipeline_hash)
    doc_metadata.setdefault("active_pipeline_ready", False)
    if ingestion_run_id is not None:
        doc_metadata.setdefault("created_by_run_id", str(ingestion_run_id))
        doc_metadata["last_ingestion_run_id"] = str(ingestion_run_id)
        doc_metadata["last_ingestion_kind"] = str(ingestion_kind or "upload_url")

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
        access_mode=None,
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
                run_document_processing_limited,
                final_path,
                file_id,
                tenant_id,
                resolved_parser_backend,
                resolved_chunk_strategy,
            )
        else:
            await document_processor.process_document(
                file_path=final_path,
                document_id=file_id,
                tenant_id=tenant_id,
                parser_backend=resolved_parser_backend,
                chunk_strategy=resolved_chunk_strategy,
                db=db,
            )

    return db_document


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
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
            )
            .filter(DBDocument.doc_metadata["file_sha256"].astext == sha)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["pipeline_hash"].astext == ph)  # type: ignore[attr-defined]
            .order_by(DBDocument.updated_at.desc(), DBDocument.created_at.desc())
            .first()
        )
    except Exception:
        docs = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
            )
            .order_by(DBDocument.updated_at.desc(), DBDocument.created_at.desc())
            .limit(max(1, int(max_scan or 5000)))
            .all()
        )
        for doc in docs or []:
            meta = dict(getattr(doc, "doc_metadata", None) or {})
            if str(meta.get("file_sha256") or "").strip().lower() != sha:
                continue
            if str(meta.get("pipeline_hash") or "").strip() != ph:
                continue
            return doc
    return None


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
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
            )
            .filter(DBDocument.doc_metadata["file_sha256"].astext == sha)  # type: ignore[attr-defined]
            .order_by(DBDocument.updated_at.desc(), DBDocument.created_at.desc())
            .first()
        )
    except Exception:
        docs = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
            )
            .order_by(DBDocument.updated_at.desc(), DBDocument.created_at.desc())
            .limit(max(1, int(max_scan or 5000)))
            .all()
        )
        for doc in docs or []:
            meta = dict(getattr(doc, "doc_metadata", None) or {})
            if str(meta.get("file_sha256") or "").strip().lower() != sha:
                continue
            return doc
    return None


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
                run_document_processing_limited,
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

document_chunk_preview = importlib.import_module("app.api.v1.document_chunk_preview")
router.include_router(document_chunk_preview.router)

ChunkPreviewRequestFields = document_chunk_preview.ChunkPreviewRequestFields
ChunkPreviewByShaFileFields = document_chunk_preview.ChunkPreviewByShaFileFields
preview_chunking = document_chunk_preview.preview_chunking
preview_chunking_by_sha = document_chunk_preview.preview_chunking_by_sha
