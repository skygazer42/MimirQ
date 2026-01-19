"""
Document management API.
"""
import asyncio
import contextlib
import hashlib
import json
import re
import shutil
import mimetypes
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks, Form, Request
from fastapi import Response
from sqlalchemy.orm import Session, selectinload
from typing import List, Optional
from uuid import UUID
from pathlib import Path
import uuid

from app.core.database import get_db
from app.models.document import Document as DBDocument, DocumentChunk
from app.api.schemas.document import (
    DocumentList,
    DocumentDetail,
    DocumentStatus,
    DocumentParsePreview,
    ParsedSegment,
    ManualDocumentCreate,
    DocumentPipelineOptions,
    DocumentUserMetadataPatchRequest,
    DocumentBatchUserMetadataPatchRequest,
    DocumentBatchUserMetadataPatchResponse,
    ChunkPreviewParams,
    ChunkPreviewItem,
    ChunkPreviewResponse,
    BatchUploadRequest,
    BatchUploadResponse,
    BatchTaskStatus,
    DocumentBatchUploadResponse,
)
from langchain_core.documents import Document
from app.parsing.processors.processor import document_processor
from app.parsing.factory import parser_factory
from app.parsing.subprocess_runner import SubprocessCancelled, SubprocessWorkerError, run_subprocess_worker
from app.rag.chunking.factory import chunker_factory
from app.types.indexing import IndexKind, IndexRecord
from app.types.pipeline import PipelineOptions
from app.services.indexer import Indexer
from app.services.pipeline_config import (
    build_indexing_options,
    build_pipeline_metadata,
    resolve_pipeline_effective,
)
from app.services.mineru_service import mineru_service
from app.services.dataset_service import DatasetService, EDIT_ROLES
from app.storage.object.minio import minio_service, is_minio_uri, parse_minio_uri
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.core.config import settings
from app.core.env import is_production_env
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from app.api.dependencies.tenant import get_tenant_id
from app.api.dependencies.auth import get_current_account_id
from app.rag.kg.pipeline import extract_events
from sqlalchemy import or_, and_
from app.rag.core.logging import get_logger
from app.rag.preprocessing.processor import governance_processor
from app.api.utils.upload import save_upload_file
from app.tasks.queue import enqueue_document_processing


logger = get_logger("api.documents")

router = APIRouter()

# Safe filename characters: letters, digits, CJK, spaces, dots, underscores, hyphens.
SAFE_FILENAME_PATTERN = re.compile(r'^[a-zA-Z0-9\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af._\-\s]+$')
UUID_PATTERN = r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
PREVIEW_IMAGE_REF_RE = re.compile(rf"(?:https?://[^\s)\"']+)?/api/v1/documents/image/({UUID_PATTERN})")
MINIO_IMAGE_REF_RE = re.compile(r"(?:https?://[^\s)\"']+)?/api/v1/documents/image-url/([^\s)\"']+)")

def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant id")

def _resolve_account_id_for_asset_request(request: Request) -> Optional[str]:
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

    try:
        return get_current_account_id(authorization=authorization, x_user_id=None)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Authentication required")


def _get_tenant_id_from_request_if_provided(request: Request) -> Optional[UUID]:
    """
    Return tenant id from header/query if explicitly provided; otherwise None.

    This is used for endpoints like `<img src>` where custom headers are not sent.
    """
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
    1) X-Tenant-ID header
    2) ?tenant_id=... query param (or aliases)
    3) settings.DEFAULT_TENANT_ID in non-production
    """
    provided = _get_tenant_id_from_request_if_provided(request)
    if provided is not None:
        return provided

    if is_production_env():
        raise HTTPException(status_code=400, detail="X-Tenant-ID header or tenant_id query param required")
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
        return documents

    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    try:
        from io import BytesIO
        from PIL import Image as PILImage  # type: ignore
    except Exception:
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
        return documents

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

    supported_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

    digest_cache: dict[str, tuple[str, str]] = {}
    try:
        from io import BytesIO
        from PIL import Image as PILImage  # type: ignore

        pillow_ok = True
    except Exception:
        BytesIO = None  # type: ignore
        PILImage = None  # type: ignore
        pillow_ok = False

    from urllib.parse import unquote

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
            if ref_lower.startswith(("http://", "https://", "data:", "blob:")):
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

            resolved_path: Optional[Path] = None
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
                    img = PILImage.open(BytesIO(raw_bytes))  # type: ignore[arg-type]
                    try:
                        if getattr(img, "mode", None) != "RGB":
                            img = img.convert("RGB")
                    except Exception:
                        pass
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

        def _md_repl(m: re.Match) -> str:
            raw = m.group(1) or ""
            key = raw.strip()
            new = replacements.get(key)
            if not new:
                return m.group(0)
            return m.group(0).replace(raw, new, 1)

        def _html_repl(m: re.Match) -> str:
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


def _validate_filename(filename: str) -> None:
    """Validate filename safety."""
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    if len(filename) > 255:
        raise HTTPException(status_code=400, detail="Filename too long (max 255 characters)")
    if not SAFE_FILENAME_PATTERN.match(filename):
        raise HTTPException(status_code=400, detail="Filename contains invalid characters")


def _to_pipeline_options(
    *,
    pipeline: Optional[DocumentPipelineOptions] = None,
    governance_enabled: Optional[bool] = None,
    governance_remove_toc_lines: Optional[bool] = None,
    governance_remove_noise_lines: Optional[bool] = None,
    governance_unwrap_lines: Optional[bool] = None,
    governance_remove_common_lines: Optional[bool] = None,
    governance_unwrap_max_line_length: Optional[int] = None,
    governance_noise_min_chars: Optional[int] = None,
    governance_noise_ratio_threshold: Optional[float] = None,
    governance_common_lines_min_docs: Optional[int] = None,
    governance_common_lines_min_ratio: Optional[float] = None,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    chunk_vector_enabled: Optional[bool] = None,
    bm25_index_enabled: Optional[bool] = None,
    kg_enabled: Optional[bool] = None,
    event_vector_enabled: Optional[bool] = None,
    entity_vector_enabled: Optional[bool] = None,
) -> PipelineOptions:
    if pipeline is None:
        pipeline = DocumentPipelineOptions(
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
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            chunk_vector_enabled=chunk_vector_enabled,
            bm25_index_enabled=bm25_index_enabled,
            kg_enabled=kg_enabled,
            event_vector_enabled=event_vector_enabled,
            entity_vector_enabled=entity_vector_enabled,
        )
    data = pipeline.model_dump(exclude_none=True)
    return PipelineOptions(**data) if data else PipelineOptions()


def _validate_chunk_params(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_overlap >= chunk_size:
        raise HTTPException(
            status_code=400,
            detail="chunk_overlap must be less than chunk_size",
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
) -> tuple[str, List[str], int]:
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

    image_exts = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"]
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
            img_path: Optional[Path] = None
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
            try:
                from io import BytesIO
                from PIL import Image as PILImage  # type: ignore
            except Exception:
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
    dataset_id: Optional[UUID],
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


@router.post("/upload", response_model=DocumentDetail, status_code=201)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    parser_backend: str = Form(default=settings.DEFAULT_PARSER_BACKEND),
    chunk_strategy: str = Form(default=settings.DEFAULT_CHUNK_STRATEGY),
    governance_enabled: Optional[bool] = Form(default=None),
    governance_remove_toc_lines: Optional[bool] = Form(default=None),
    governance_remove_noise_lines: Optional[bool] = Form(default=None),
    governance_unwrap_lines: Optional[bool] = Form(default=None),
    governance_remove_common_lines: Optional[bool] = Form(default=None),
    governance_unwrap_max_line_length: Optional[int] = Form(default=None),
    governance_noise_min_chars: Optional[int] = Form(default=None),
    governance_noise_ratio_threshold: Optional[float] = Form(default=None),
    governance_common_lines_min_docs: Optional[int] = Form(default=None),
    governance_common_lines_min_ratio: Optional[float] = Form(default=None),
    chunk_size: Optional[int] = Form(default=None),
    chunk_overlap: Optional[int] = Form(default=None),
    chunk_vector_enabled: Optional[bool] = Form(default=None),
    bm25_index_enabled: Optional[bool] = Form(default=None),
    kg_enabled: Optional[bool] = Form(default=None),
    event_vector_enabled: Optional[bool] = Form(default=None),
    entity_vector_enabled: Optional[bool] = Form(default=None),
    dataset_id: Optional[UUID] = Form(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    Upload a document.

    Flow:
    1. Validate file type and size
    2. Save file locally
    3. Create database record
    4. Process document asynchronously (parse, chunk, embed)
    """

    # 0. Validate filename safety.
    _validate_filename(file.filename)

    # 1. Validate file type.
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )

    try:
        requested_parser_backend = (parser_backend or "").strip().lower()
        if file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
            # Keep "auto" for background routing (quality scoring happens in DocumentProcessor).
            resolved_parser_backend = "auto"
        else:
            resolved_parser_backend = parser_factory.resolve_backend(file_ext, parser_backend)
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    pipeline_options = _to_pipeline_options(
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
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        chunk_vector_enabled=chunk_vector_enabled,
        bm25_index_enabled=bm25_index_enabled,
        kg_enabled=kg_enabled,
        event_vector_enabled=event_vector_enabled,
        entity_vector_enabled=entity_vector_enabled,
    )
    # Permission check.
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, dataset_id)

    pipeline_effective = resolve_pipeline_effective(
        dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}),
        document_metadata={},
        request_overrides=pipeline_options,
    )
    if resolved_chunk_strategy not in chunker_factory.RAGFLOW_STRATEGIES:
        _validate_chunk_params(pipeline_effective.chunk_size, pipeline_effective.chunk_overlap)
    pipeline_metadata = build_pipeline_metadata(pipeline_options)

    # 3. Save file.
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique filename.
    file_id = uuid.uuid4()
    file_path = upload_dir / f"{file_id}{file_ext}"

    try:
        file_size = await save_upload_file(file, file_path, max_bytes=settings.MAX_FILE_SIZE)
    except HTTPException:
        raise

    # 4. Create database record.
    doc_metadata = {
        "parser_backend": resolved_parser_backend,
        "parser_backend_requested": (parser_backend or "").lower(),
        "chunk_strategy": resolved_chunk_strategy,
        "chunk_strategy_requested": (chunk_strategy or "").lower(),
    }
    if pipeline_metadata:
        doc_metadata["pipeline"] = pipeline_metadata
    pipeline_hash = _compute_pipeline_hash(doc_metadata)
    doc_metadata["pipeline_hash"] = pipeline_hash

    db_document = DBDocument(
        id=file_id,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        filename=file.filename,
        file_type=file_ext.lstrip('.'),
        file_size=file_size,
        file_path=str(file_path),
        status='pending',
        processing_progress=0,
        doc_metadata=doc_metadata,
    )

    db.add(db_document)
    db.commit()
    db.refresh(db_document)

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


@router.post("/upload-batch", response_model=DocumentBatchUploadResponse, status_code=201)
async def upload_documents_batch(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    parser_backend: str = Form(default=settings.DEFAULT_PARSER_BACKEND),
    chunk_strategy: str = Form(default=settings.DEFAULT_CHUNK_STRATEGY),
    governance_enabled: Optional[bool] = Form(default=None),
    governance_remove_toc_lines: Optional[bool] = Form(default=None),
    governance_remove_noise_lines: Optional[bool] = Form(default=None),
    governance_unwrap_lines: Optional[bool] = Form(default=None),
    governance_remove_common_lines: Optional[bool] = Form(default=None),
    governance_unwrap_max_line_length: Optional[int] = Form(default=None),
    governance_noise_min_chars: Optional[int] = Form(default=None),
    governance_noise_ratio_threshold: Optional[float] = Form(default=None),
    governance_common_lines_min_docs: Optional[int] = Form(default=None),
    governance_common_lines_min_ratio: Optional[float] = Form(default=None),
    chunk_size: Optional[int] = Form(default=None),
    chunk_overlap: Optional[int] = Form(default=None),
    chunk_vector_enabled: Optional[bool] = Form(default=None),
    bm25_index_enabled: Optional[bool] = Form(default=None),
    kg_enabled: Optional[bool] = Form(default=None),
    event_vector_enabled: Optional[bool] = Form(default=None),
    entity_vector_enabled: Optional[bool] = Form(default=None),
    dataset_id: Optional[UUID] = Form(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
    max_concurrent: int = Form(default=5)
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
    
    # Cap concurrency.
    max_concurrent = min(max_concurrent, 10)  # Max 10 concurrent.
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_single_file(file: UploadFile) -> dict:
        """Handle upload for a single file."""
        async with semaphore:
            try:
                # Validate filename.
                _validate_filename(file.filename)
                
                # Validate file type.
                file_ext = Path(file.filename).suffix.lower()
                if file_ext not in settings.allowed_extensions_list:
                    return {
                        "success": False,
                        "filename": file.filename,
                        "error": f"Unsupported file type: {file_ext}"
                    }
                
                # Parser validation.
                requested_parser_backend = (parser_backend or "").strip().lower()
                if file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
                    resolved_parser_backend = "auto"
                else:
                    resolved_parser_backend = parser_factory.resolve_backend(file_ext, parser_backend)
                resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
                
                pipeline_options = _to_pipeline_options(
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
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    chunk_vector_enabled=chunk_vector_enabled,
                    bm25_index_enabled=bm25_index_enabled,
                    kg_enabled=kg_enabled,
                    event_vector_enabled=event_vector_enabled,
                    entity_vector_enabled=entity_vector_enabled,
                )
                pipeline_effective = resolve_pipeline_effective(
                    dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}) if dataset else {},
                    document_metadata={},
                    request_overrides=pipeline_options,
                )
                if resolved_chunk_strategy not in chunker_factory.RAGFLOW_STRATEGIES:
                    _validate_chunk_params(pipeline_effective.chunk_size, pipeline_effective.chunk_overlap)
                pipeline_metadata = build_pipeline_metadata(pipeline_options)
                
                # Permission check (already done outside semaphore).
                # Save file.
                upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
                upload_dir.mkdir(parents=True, exist_ok=True)
                
                file_id = uuid.uuid4()
                file_path = upload_dir / f"{file_id}{file_ext}"
                
                file_size = await save_upload_file(file, file_path, max_bytes=settings.MAX_FILE_SIZE)
                
                # Create database record.
                doc_metadata = {
                    "parser_backend": resolved_parser_backend,
                    "parser_backend_requested": (parser_backend or "").lower(),
                    "chunk_strategy": resolved_chunk_strategy,
                    "chunk_strategy_requested": (chunk_strategy or "").lower(),
                }
                if pipeline_metadata:
                    doc_metadata["pipeline"] = pipeline_metadata
                pipeline_hash = _compute_pipeline_hash(doc_metadata)
                doc_metadata["pipeline_hash"] = pipeline_hash
                
                db_document = DBDocument(
                    id=file_id,
                    tenant_id=tenant_id,
                    dataset_id=dataset.id if dataset else None,
                    filename=file.filename,
                    file_type=file_ext.lstrip('.'),
                    file_size=file_size,
                    file_path=str(file_path),
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
                    "document_id": str(file_id),
                    "document": db_document
                }
                
            except Exception as e:
                logger.error(f"Error processing file {file.filename}: {str(e)}")
                return {
                    "success": False,
                    "filename": file.filename,
                    "error": str(e)
                }
    
    # Permission check (done once).
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, dataset_id)
    
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
                "error": str(result)
            })
        else:
            processed_results.append(result)
    
    successful = [r for r in processed_results if r.get("success")]
    failed = [r for r in processed_results if not r.get("success")]
    
    return {
        "total": len(files),
        "successful_count": len(successful),
        "failed_count": len(failed),
        "successful": [
            {
                "document_id": r["document_id"],
                "filename": r["filename"],
                "status": r["document"].status
            }
            for r in successful
        ],
        "failed": [
            {
                "filename": r["filename"],
                "error": r.get("error", "Unknown error")
            }
            for r in failed
        ]
    }


@router.get("/", response_model=DocumentList)
async def list_documents(
    skip: int = 0,
    limit: int = 20,
    status: Optional[str] = None,
    dataset_id: Optional[UUID] = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    List documents.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id)

    if dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
        query = query.filter(DBDocument.dataset_id == dataset_id)
    else:
        # No dataset_id: return all documents the user can read within the tenant.
        # Optimization: use database filtering to avoid N+1 queries.

        # Subquery: dataset IDs accessible via PARTIAL_MEMBERS permission.
        partial_member_subq = (
            db.query(DatasetPermission.dataset_id)
            .filter(
                DatasetPermission.tenant_id == tenant_id,
                DatasetPermission.account_id == account_id,
            )
            .subquery()
        )

        # Build allowed dataset filters.
        allowed_dataset_filter = or_(
            # User is owner.
            Dataset.owner_id == account_id,
            # ALL_TEAM_MEMBERS permission.
            Dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS,
            # PARTIAL_MEMBERS permission and user in list.
            and_(
                Dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS,
                Dataset.id.in_(partial_member_subq)
            )
        )

        # Fetch accessible dataset IDs.
        allowed_dataset_ids_subq = (
            db.query(Dataset.id)
            .filter(
                Dataset.tenant_id == tenant_id,
                allowed_dataset_filter
            )
            .subquery()
        )

        query = query.filter(
            or_(
                DBDocument.dataset_id.is_(None),
                DBDocument.dataset_id.in_(allowed_dataset_ids_subq),
            )
        )

    # Status filter.
    if status and status != 'all':
        query = query.filter(DBDocument.status == status)

    # Total count.
    total = query.count()

    # Pagination.
    documents = query.order_by(DBDocument.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "items": documents
    }


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: uuid.UUID,
    include_chunks: bool = False,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    Get document detail.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    query = db.query(DBDocument).filter(
        DBDocument.id == document_id,
        DBDocument.tenant_id == tenant_id
    )
    if include_chunks:
        query = query.options(selectinload(DBDocument.chunks))
    document = query.first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Permission check.
    if document.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)

    # If chunks are needed, touch the relationship to ensure load.
    if include_chunks:
        # Expose a non-relationship attribute for Pydantic to serialize without triggering
        # accidental lazy-loading when include_chunks=false.
        setattr(document, "chunks_loaded", document.chunks)

    return document


@router.patch("/{document_id}/metadata", response_model=DocumentDetail)
async def patch_document_user_metadata(
    document_id: uuid.UUID,
    payload: DocumentUserMetadataPatchRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Patch `documents.metadata.user` for user-editable document metadata.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    meta = dict(document.doc_metadata or {})
    current_user = meta.get("user") if isinstance(meta.get("user"), dict) else {}
    patch = payload.patch if isinstance(payload.patch, dict) else {}
    next_user = _apply_user_metadata_patch(current=current_user, patch=patch, replace=payload.replace)

    meta["user"] = next_user
    document.doc_metadata = meta
    db.commit()
    db.refresh(document)
    return document


@router.post("/batch/metadata", response_model=DocumentBatchUserMetadataPatchResponse)
async def batch_patch_document_user_metadata(
    payload: DocumentBatchUserMetadataPatchRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Batch patch `documents.metadata.user`.

    For any documents the caller cannot write, they will be returned in `denied`.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    ids = list(payload.document_ids or [])
    if not ids:
        return {"updated": 0, "not_found": [], "denied": []}

    documents = (
        db.query(DBDocument)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(ids))
        .all()
    )
    found_map = {d.id: d for d in documents}
    not_found = [doc_id for doc_id in ids if doc_id not in found_map]

    dataset_ids = {d.dataset_id for d in documents if d.dataset_id is not None}
    dataset_map: dict[UUID, Dataset] = {}
    if dataset_ids:
        rows = (
            db.query(Dataset)
            .filter(Dataset.tenant_id == tenant_id, Dataset.id.in_(sorted(dataset_ids)))
            .all()
        )
        dataset_map = {ds.id: ds for ds in rows}

    denied: list[UUID] = []
    updated = 0

    patch = payload.patch if isinstance(payload.patch, dict) else {}
    for doc in documents:
        if doc.dataset_id:
            ds = dataset_map.get(doc.dataset_id)
            if ds is None:
                denied.append(doc.id)
                continue
            try:
                DatasetService.assert_dataset_writable(db, ds, account_id)
            except HTTPException:
                denied.append(doc.id)
                continue

        meta = dict(doc.doc_metadata or {})
        current_user = meta.get("user") if isinstance(meta.get("user"), dict) else {}
        next_user = _apply_user_metadata_patch(current=current_user, patch=patch, replace=payload.replace)
        meta["user"] = next_user
        doc.doc_metadata = meta
        updated += 1

    if updated:
        db.commit()

    return {"updated": updated, "not_found": not_found, "denied": denied}


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    request: Request,
    inline: bool = True,
    db: Session = Depends(get_db),
):
    """
    Download (or inline-preview) a document file.

    This endpoint supports `?token=` and `?tenant_id=` query params to enable
    usage in <iframe>/<a> tags where custom headers cannot be set.
    """
    tenant_id = _resolve_tenant_id_for_asset_request(request)
    account_id = _resolve_account_id_for_asset_request(request)

    # Best-effort permission check: allow anonymous in local/dev header mode.
    if account_id:
        DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.dataset_id and account_id:
        ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)

    raw_path = str(document.file_path or "").strip()
    if not raw_path or raw_path.startswith("manual://"):
        raise HTTPException(status_code=404, detail="Document file not available")

    # Object storage path (MinIO/S3-compatible).
    if is_minio_uri(raw_path):
        if not bool(getattr(settings, "MINIO_ENABLED", False)):
            raise HTTPException(status_code=503, detail="Object storage is disabled")

        try:
            ref = parse_minio_uri(raw_path)
        except ValueError:
            raise HTTPException(status_code=404, detail="Document file not available")

        if ref.bucket != str(getattr(settings, "MINIO_BUCKET_NAME", "")):
            raise HTTPException(status_code=403, detail="Document file access denied")

        dataset_id = str(document.dataset_id) if document.dataset_id else str(tenant_id)
        expected_object = minio_service.build_document_object_name(
            tenant_id=str(tenant_id),
            dataset_id=dataset_id,
            document_id=str(document.id),
            extension=f".{(document.file_type or '').lower()}",
        )
        if ref.object_name != expected_object:
            raise HTTPException(status_code=403, detail="Document file access denied")

        try:
            stat = minio_service.stat_object(object_name=ref.object_name)
        except Exception:
            raise HTTPException(status_code=404, detail="Document file not found")

        total_size = int(getattr(stat, "size", 0) or 0)
        if total_size <= 0:
            raise HTTPException(status_code=404, detail="Document file not found")

        range_header = (request.headers.get("range") or "").strip()
        offset = 0
        length: Optional[int] = None
        status_code = 200
        headers: dict[str, str] = {
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Content-Type-Options": "nosniff",
            "Accept-Ranges": "bytes",
        }

        # Basic single-range support for PDF iframe previews.
        if range_header.lower().startswith("bytes="):
            spec = range_header[6:].strip()
            if "," in spec:
                raise HTTPException(status_code=416, detail="Multiple ranges not supported")
            start_s, end_s = (spec.split("-", 1) + [""])[:2]
            try:
                if start_s == "":
                    # suffix range: "-N"
                    suffix = int(end_s)
                    if suffix <= 0:
                        raise ValueError
                    offset = max(0, total_size - suffix)
                    end = total_size - 1
                else:
                    offset = int(start_s)
                    end = int(end_s) if end_s else (total_size - 1)
                    if offset < 0:
                        raise ValueError
                    if end < offset:
                        raise ValueError
                    if offset >= total_size:
                        raise HTTPException(status_code=416, detail="Range not satisfiable")
                    end = min(end, total_size - 1)
                length = int(end - offset + 1)
                status_code = 206
                headers["Content-Range"] = f"bytes {offset}-{offset + length - 1}/{total_size}"
                headers["Content-Length"] = str(length)
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=416, detail="Invalid Range header")
        else:
            headers["Content-Length"] = str(total_size)

        media_type, _encoding = mimetypes.guess_type(document.filename)
        if not media_type:
            media_type = "application/octet-stream"

        from urllib.parse import quote

        disposition = "inline" if inline else "attachment"
        safe_name = (document.filename or "document").replace("\n", " ").replace("\r", " ")
        headers["Content-Disposition"] = f"{disposition}; filename*=UTF-8''{quote(safe_name)}"

        return StreamingResponse(
            minio_service.iter_object_bytes(object_name=ref.object_name, offset=offset, length=length),
            status_code=status_code,
            media_type=media_type,
            headers=headers,
        )

    # Local filesystem path (legacy/default).
    path = Path(raw_path).resolve(strict=False)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Document file not found")

    # Prevent path traversal / unsafe paths in DB: only allow files under uploads/{tenant_id}/
    upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
    tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
    try:
        path.relative_to(tenant_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Document file access denied")

    media_type, _encoding = mimetypes.guess_type(path.name)
    if not media_type:
        media_type = "application/octet-stream"

    # Avoid caching sensitive content; tokens may be embedded in URLs.
    headers = {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "Expires": "0",
        "X-Content-Type-Options": "nosniff",
    }

    return FileResponse(
        path,
        media_type=media_type,
        filename=document.filename,
        content_disposition_type="inline" if inline else "attachment",
        headers=headers,
    )


@router.get("/{document_id}/status", response_model=DocumentStatus)
async def get_document_status(
    document_id: uuid.UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    Get document processing status (for polling).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    document = db.query(DBDocument).filter(
        DBDocument.id == document_id,
        DBDocument.tenant_id == tenant_id
    ).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)

    return {
        "id": document.id,
        "status": document.status,
        "processing_progress": document.processing_progress,
        "current_stage": document.current_stage,
        "error_message": document.error_message
    }


@router.post("/{document_id}/cancel", response_model=DocumentStatus)
async def cancel_document_processing(
    document_id: uuid.UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Cancel an in-progress document processing task.

    Notes:
    - When TASK_QUEUE_ENABLED=true, this will best-effort abort the arq job.
    - When queue is disabled, the in-process/background worker cooperatively checks the cancelled status.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = db.query(DBDocument).filter(
        DBDocument.id == document_id,
        DBDocument.tenant_id == tenant_id,
    ).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    current_status = str(document.status or "").lower()
    if current_status in {"completed", "failed"}:
        raise HTTPException(status_code=409, detail=f"Cannot cancel a {current_status} document")

    meta = dict(document.doc_metadata or {})
    meta["cancel_requested"] = True
    document.doc_metadata = meta
    document.status = "cancelled"
    document.processing_progress = 0
    document.current_stage = "cancelled"
    document.error_message = "cancelled"
    db.commit()
    db.refresh(document)

    task_id = meta.get("task_id")
    kg_task_id = meta.get("kg_task_id")
    task_ids: list[str] = []
    for raw in (task_id, kg_task_id):
        if isinstance(raw, str) and raw.strip():
            task_ids.append(raw.strip())

    if bool(getattr(settings, "TASK_QUEUE_ENABLED", False)) and task_ids:
        try:
            from arq.jobs import Job
            from app.tasks.queue import get_queue

            q = await get_queue()
            if q is not None:
                queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
                for tid in task_ids:
                    job = Job(tid, q, _queue_name=queue_name)
                    with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                        # Abort signal was enqueued; the worker will pick it up shortly.
                        await job.abort(timeout=0.2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to abort tasks %s for document %s: %s", task_ids, document_id, str(exc)[:200])

    return {
        "id": document.id,
        "status": document.status,
        "processing_progress": document.processing_progress,
        "current_stage": document.current_stage,
        "error_message": document.error_message,
    }


@router.post("/{document_id}/retry", response_model=DocumentStatus)
async def retry_document_processing(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    force: bool = False,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Retry a failed/cancelled document processing task.

    Notes:
    - This will delete existing chunks (DB) and indexes (vector/BM25/KG) before reprocessing.
    - Use `force=true` to allow retrying completed documents.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    current_status = str(document.status or "").lower()
    if current_status in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail=f"Cannot retry a {current_status} document")
    if current_status == "completed" and not force:
        raise HTTPException(status_code=409, detail="Document is already completed (use force=true to reprocess)")

    raw_path = str(document.file_path or "").strip()
    if not raw_path or raw_path.startswith("manual://"):
        raise HTTPException(status_code=409, detail="Document file is not reprocessable")

    object_name: str | None = None
    file_path: Path | None = None
    if is_minio_uri(raw_path):
        if not bool(getattr(settings, "MINIO_ENABLED", False)):
            raise HTTPException(status_code=503, detail="Object storage is disabled")
        try:
            ref = parse_minio_uri(raw_path)
        except ValueError:
            raise HTTPException(status_code=404, detail="Document file not found")
        if ref.bucket != str(getattr(settings, "MINIO_BUCKET_NAME", "")):
            raise HTTPException(status_code=403, detail="Document file access denied")
        dataset_id = str(document.dataset_id) if document.dataset_id else str(tenant_id)
        expected_object = minio_service.build_document_object_name(
            tenant_id=str(tenant_id),
            dataset_id=dataset_id,
            document_id=str(document.id),
            extension=f".{(document.file_type or '').lower()}",
        )
        if ref.object_name != expected_object:
            raise HTTPException(status_code=403, detail="Document file access denied")
        try:
            minio_service.stat_object(object_name=ref.object_name)
        except Exception:
            raise HTTPException(status_code=404, detail="Document file not found")
        object_name = ref.object_name
    else:
        file_path = Path(raw_path)
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="Document file not found")

    # Reset indexes (vector/BM25/KG) + DB chunks to avoid duplicates on re-run.
    with contextlib.suppress(Exception):
        Indexer(db).delete_all(tenant_id=tenant_id, document_id=document_id, commit=False)
    with contextlib.suppress(Exception):
        db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document_id,
            DocumentChunk.tenant_id == tenant_id,
        ).delete(synchronize_session=False)

    meta = dict(document.doc_metadata or {})
    meta.pop("cancel_requested", None)
    meta.pop("task_id", None)
    meta.pop("kg_task_id", None)
    meta.pop("img_ids", None)

    pipeline_hash = str(meta.get("pipeline_hash") or "").strip()
    if not pipeline_hash:
        pipeline_hash = _compute_pipeline_hash(meta)
        meta["pipeline_hash"] = pipeline_hash

    document.doc_metadata = meta
    document.status = "pending"
    document.processing_progress = 0
    document.current_stage = "queued"
    document.error_message = None
    document.chunk_count = 0
    document.total_characters = 0
    db.commit()
    db.refresh(document)

    job_id = f"doc:{tenant_id}:{document_id}:{pipeline_hash}"
    task_id = await enqueue_document_processing(
        tenant_id=tenant_id,
        document_id=document_id,
        requested_by=account_id,
        job_id=job_id,
    )
    if task_id:
        meta = dict(document.doc_metadata or {})
        meta["task_id"] = task_id
        document.doc_metadata = meta
        db.commit()
        db.refresh(document)
    else:
        if file_path is not None:
            background_tasks.add_task(
                document_processor.process_document,
                file_path,
                document_id,
                tenant_id,
                meta.get("parser_backend"),
                meta.get("chunk_strategy"),
            )
        else:
            # Queue is disabled; download from object storage and process locally (best-effort cleanup).
            temp_dir = (Path(settings.UPLOAD_DIR) / str(tenant_id) / ".tmp").resolve(strict=False)
            suffix = f".{(document.file_type or '').lower()}"
            temp_path = temp_dir / f"{document_id}.{uuid.uuid4().hex}{suffix}"

            async def _process_from_object_store() -> None:
                try:
                    await asyncio.to_thread(
                        minio_service.download_object_to_path,
                        object_name=str(object_name),
                        destination=temp_path,
                        max_bytes=int(getattr(settings, "MAX_FILE_SIZE", 0) or 0),
                    )
                    await document_processor.process_document(
                        file_path=temp_path,
                        document_id=document_id,
                        tenant_id=tenant_id,
                        parser_backend=meta.get("parser_backend"),
                        chunk_strategy=meta.get("chunk_strategy"),
                        db=None,
                    )
                finally:
                    with contextlib.suppress(Exception):
                        temp_path.unlink(missing_ok=True)

            background_tasks.add_task(_process_from_object_store)

    return {
        "id": document.id,
        "status": document.status,
        "processing_progress": document.processing_progress,
        "current_stage": document.current_stage,
        "error_message": document.error_message,
    }


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    Delete document.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    document = db.query(DBDocument).filter(
        DBDocument.id == document_id,
        DBDocument.tenant_id == tenant_id
    ).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.dataset_id:
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
    Indexer(db).delete_all(tenant_id=tenant_id, document_id=document_id, commit=False)

    # 3. Delete local file.
    try:
        raw_path = str(document.file_path or "").strip()
        if raw_path and not raw_path.startswith("manual://"):
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
                if file_path.exists():
                    file_path.unlink()
    except Exception as e:
        logger.warning("Failed to delete file: %s", e)

    # 4. Delete DB record (cascade chunks).
    db.delete(document)
    db.commit()

    # 5. Remove chunks from BM25 index (in-memory).
    return None


@router.get("/image/{image_id}")
async def get_image(
    image_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Return stored image by image_id.
    Standard path: {UPLOAD_DIR}/{tenant_id}/images/{image_id}(.png|.jpg|.jpeg|.webp|.gif|.bmp)
    """
    tenant_id = _resolve_tenant_id_for_asset_request(request)
    account_id = _resolve_account_id_for_asset_request(request)

    # Best-effort permission check: in local/dev header mode, image URLs are loaded
    # by the browser without custom headers; allow anonymous image access there.
    if account_id:
        DatasetService.ensure_member(db, tenant_id, account_id)
    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    # Prevent path traversal: only allow UUID / 32-hex (internal image_id).
    try:
        safe_id = uuid.UUID(image_id).hex
    except ValueError:
        raise HTTPException(status_code=404, detail="Image not found")

    images_dir_resolved = images_dir.resolve(strict=False)

    candidates: list[tuple[str, str]] = [
        (".png", "image/png"),
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".webp", "image/webp"),
        (".gif", "image/gif"),
        (".bmp", "image/bmp"),
    ]

    for ext, media_type in candidates:
        file_path = (images_dir / f"{safe_id}{ext}").resolve(strict=False)
        # Safety check: ensure file_path stays under images_dir (prevent path traversal).
        try:
            file_path.relative_to(images_dir_resolved)
        except ValueError:
            continue
        if file_path.exists() and file_path.is_file():
            max_age = max(0, int(getattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 0) or 0))
            cache_control = f"private, max-age={max_age}" if max_age > 0 else "no-cache"
            try:
                st = file_path.stat()
            except Exception:
                st = None

            etag: str | None = None
            if st is not None:
                # Strong etag based on mtime+size; stable for immutable UUID-based assets.
                etag = f"\"{int(getattr(st, 'st_mtime_ns', 0) or 0):x}-{int(getattr(st, 'st_size', 0) or 0):x}\""

            if etag:
                if_none_match = (request.headers.get("if-none-match") or "").strip()
                if if_none_match:
                    candidates_etag = [p.strip() for p in if_none_match.split(",") if p.strip()]
                    if "*" in candidates_etag or etag in candidates_etag:
                        return Response(
                            status_code=304,
                            headers={
                                "ETag": etag,
                                "Cache-Control": cache_control,
                                "X-Content-Type-Options": "nosniff",
                            },
                        )
            return FileResponse(
                file_path,
                media_type=media_type,
                headers={
                    "Cache-Control": cache_control,
                    "X-Content-Type-Options": "nosniff",
                    **({"ETag": etag} if etag else {}),
                },
                stat_result=st,
                content_disposition_type="inline",
            )

    raise HTTPException(status_code=404, detail="Image not found")


@router.get("/image-url/{img_id}")
async def get_image_url(
    img_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Get MinIO presigned URL by img_id ({tenant_id}:{dataset_id}:{document_id}:{chunk_index}).
    Returns a 302 redirect to the image URL.
    """
    if not settings.MINIO_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="MinIO is disabled; cannot retrieve image URL"
        )
    account_id = _resolve_account_id_for_asset_request(request)

    # Resolve tenant_id even when the request is coming from <img src> (no custom headers).
    requested_tenant = _get_tenant_id_from_request_if_provided(request)

    def _tenant_from_img_id(val: str) -> Optional[UUID]:
        if ":" not in val:
            return None
        raw_tenant = (val.split(":", 1)[0] or "").strip()
        if not raw_tenant:
            return None
        try:
            return UUID(raw_tenant)
        except Exception:
            return None

    tenant_in_img = _tenant_from_img_id(img_id)
    if tenant_in_img and requested_tenant and tenant_in_img != requested_tenant:
        raise HTTPException(status_code=403, detail="Image access denied for this tenant")

    tenant_id = tenant_in_img or requested_tenant or _resolve_tenant_id_for_asset_request(request)

    # Best-effort permission check: in local/dev header mode, image URLs are loaded
    # by the browser without custom headers; allow anonymous image access there.
    if account_id:
        DatasetService.ensure_member(db, tenant_id, account_id)

    # Permission check: parse dataset/document from img_id when possible for dataset-level control.
    if ":" in img_id:
        try:
            _tenant_part, dataset_part, document_part, _chunk_key = img_id.split(":", 3)
            dataset_uuid = UUID(dataset_part)
            document_uuid = UUID(document_part)
        except Exception:
            raise HTTPException(status_code=404, detail="Image not found")

        document = (
            db.query(DBDocument)
            .filter(DBDocument.id == document_uuid, DBDocument.tenant_id == tenant_id)
            .first()
        )
        if not document:
            raise HTTPException(status_code=404, detail="Image not found")
        if document.dataset_id and document.dataset_id != dataset_uuid:
            raise HTTPException(status_code=404, detail="Image not found")
        if document.dataset_id and account_id:
            ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
            DatasetService.assert_dataset_readable(db, ds, account_id)
    else:
        # Backward compatible: "{dataset_id}-{chunk_id}"
        try:
            dataset_part = img_id.split("-", 1)[0]
            dataset_uuid = UUID(dataset_part)
        except Exception:
            raise HTTPException(status_code=404, detail="Image not found")
        if account_id:
            ds = DatasetService.get_dataset(db, tenant_id, dataset_uuid)
            DatasetService.assert_dataset_readable(db, ds, account_id)

    try:
        url = minio_service.get_image_url(img_id, extension="jpg")
        # Redirect to MinIO presigned URL.
        return RedirectResponse(
            url=url,
            status_code=302,
            headers={
                # Avoid caching sensitive presigned URLs.
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Image not found or retrieval failed: {str(e)}"
        )


@router.post("/preview", response_model=DocumentParsePreview)
async def preview_document(
    request: Request,
    file: UploadFile = File(...),
    parser_backend: str = Form(default=settings.DEFAULT_PARSER_BACKEND),
    chunk_strategy: str = Form(default=settings.DEFAULT_CHUNK_STRATEGY),
    dataset_id: Optional[str] = Form(default=None),
    governance_enabled: Optional[bool] = Form(default=None),
    governance_remove_toc_lines: Optional[bool] = Form(default=None),
    governance_remove_noise_lines: Optional[bool] = Form(default=None),
    governance_unwrap_lines: Optional[bool] = Form(default=None),
    governance_remove_common_lines: Optional[bool] = Form(default=None),
    governance_unwrap_max_line_length: Optional[int] = Form(default=None),
    governance_noise_min_chars: Optional[int] = Form(default=None),
    governance_noise_ratio_threshold: Optional[float] = Form(default=None),
    governance_common_lines_min_docs: Optional[int] = Form(default=None),
    governance_common_lines_min_ratio: Optional[float] = Form(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Document parse preview endpoint.

    Only parses the document and returns structured segments; does not create
    a document record or persist data. Useful for frontend custom chunking.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
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

        pipeline_options = _to_pipeline_options(
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
        if pipeline_effective.governance_enabled:
            documents, _stats = governance_processor.clean_documents(
                documents,
                remove_toc_lines=pipeline_effective.governance_remove_toc_lines,
                remove_noise_lines=pipeline_effective.governance_remove_noise_lines,
                unwrap_lines=pipeline_effective.governance_unwrap_lines,
                remove_common_lines=pipeline_effective.governance_remove_common_lines,
                unwrap_max_line_length=pipeline_effective.governance_unwrap_max_line_length,
                noise_min_chars=pipeline_effective.governance_noise_min_chars,
                noise_ratio_threshold=pipeline_effective.governance_noise_ratio_threshold,
                common_lines_min_docs=pipeline_effective.governance_common_lines_min_docs,
                common_lines_min_ratio=pipeline_effective.governance_common_lines_min_ratio,
            )

        segments: List[ParsedSegment] = []
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
            parser_backend=resolved_backend
        )
    except SubprocessCancelled:
        # Client disconnected; stop work early.
        raise HTTPException(status_code=499, detail="Client closed request")
    except SubprocessWorkerError as e:
        # Map input validation errors to 400 to preserve historical behavior.
        err_type = (e.details or {}).get("type")
        if err_type == "ValueError":
            raise HTTPException(status_code=400, detail=f"Invalid input: {str(e)[:100]}")
        logger.error("Subprocess worker failed during preview: %s", str(e)[:200])
        raise HTTPException(status_code=500, detail="Failed to parse document")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid input: {str(e)[:100]}")
    except IOError as e:
        logger.error("File read error during preview: %s", str(e)[:200])
        raise HTTPException(status_code=500, detail="File read error")
    except Exception as e:
        logger.error("Unexpected error during document preview: %s", str(e)[:200])
        raise HTTPException(status_code=500, detail="Failed to parse document")
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
                    if not any(p in path.parts for p in {".magicpdf", ".deepseek_ocr", ".etl4llm", ".marker", ".paddlevl"}):
                        continue
                    path.relative_to(tenant_root)
                except Exception:
                    continue
                with contextlib.suppress(Exception):
                    shutil.rmtree(path, ignore_errors=True)


@router.post("/manual", response_model=DocumentDetail, status_code=201)
async def create_document_with_manual_chunks(
    request: ManualDocumentCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    Create a document from frontend custom chunks.

    Flow:
    1. Create document record (status=processing)
    2. Generate embeddings from chunks and store in Milvus
    3. Write chunks to PostgreSQL
    4. Rebuild BM25 index
    5. Update document status to completed
    """
    # Permission check.
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, request.dataset_id)

    # Basic validation.
    if not request.chunks:
        raise HTTPException(status_code=400, detail="Chunks cannot be empty")

    # Validate file type.
    file_type_with_dot = f".{request.file_type.lower()}"
    if file_type_with_dot not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {request.file_type}"
        )

    # Create document record.
    document_id = uuid.uuid4()
    pipeline_options = _to_pipeline_options(pipeline=request.pipeline)
    pipeline_effective = resolve_pipeline_effective(
        dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}),
        document_metadata={},
        request_overrides=pipeline_options,
    )
    index_options = build_indexing_options(pipeline_effective)
    pipeline_metadata = build_pipeline_metadata(pipeline_options)

    doc_metadata = dict(request.metadata or {})
    if pipeline_metadata:
        doc_metadata["pipeline"] = pipeline_metadata

    db_document = DBDocument(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        filename=request.filename,
        file_type=request.file_type.lower(),
        file_size=request.file_size,
        # Manual-chunk documents have no real file path; use a placeholder.
        file_path=f"manual://{document_id}",
        status='processing',
        processing_progress=0,
        current_stage='embedding',
        doc_metadata=doc_metadata,
    )

    db.add(db_document)
    db.flush()  # Flush only (no commit) to allow rollback.

    try:
        # Best-effort: migrate preview-time local images to MinIO so retrieval can cite them.
        images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
        local_id_to_img_id: dict[str, str] = {}
        digest_to_img_id: dict[str, str] = {}
        asset_index = 0
        document_img_ids: set[str] = set()

        records: List[IndexRecord] = []
        for idx, chunk in enumerate(request.chunks):
            content = chunk.content or ""
            metadata = {
                "source": request.filename,
                "file_type": request.file_type.lower(),
                "page": chunk.page_number,
                "document_id": str(document_id),
                "chunk_index": idx,
                **(chunk.metadata or {}),
            }

            if settings.MINIO_ENABLED:
                # If the chunk already references MinIO images, backfill img_id for citations.
                if not (metadata.get("img_id") or metadata.get("image_id")):
                    m = MINIO_IMAGE_REF_RE.search(content)
                    if m:
                        maybe_id = (m.group(1) or "").strip()
                        if maybe_id:
                            metadata["img_id"] = maybe_id

                content, img_ids, asset_index = _rewrite_preview_images_to_minio(
                    content,
                    tenant_id=str(tenant_id),
                    dataset_id=str(dataset.id),
                    document_id=str(document_id),
                    images_dir=images_dir,
                    local_id_to_img_id=local_id_to_img_id,
                    digest_to_img_id=digest_to_img_id,
                    start_index=asset_index,
                )
                if img_ids:
                    document_img_ids.update(img_ids)
                    metadata.setdefault("img_id", img_ids[0])
                    metadata.setdefault("img_ids", img_ids)
                    metadata.setdefault("image_count", len(img_ids))

            records.append(
                IndexRecord(
                    kind=IndexKind.CHUNK,
                    content=content,
                    metadata=metadata,
                    document_id=document_id,
                    page_number=chunk.page_number,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                )
            )

        if settings.MINIO_ENABLED and document_img_ids:
            # Store a document-level image list for cleanup and compatibility.
            meta = dict(db_document.doc_metadata or {})
            existing = meta.get("img_ids")
            merged: set[str] = set()
            if isinstance(existing, list):
                merged |= {v for v in existing if isinstance(v, str) and v.strip()}
            merged |= {v for v in document_img_ids if isinstance(v, str) and v.strip()}
            meta["img_ids"] = sorted(merged)
            meta["image_count"] = len(merged)
            db_document.doc_metadata = meta

        persist_result = Indexer(db).upsert(
            tenant_id=tenant_id,
            records=records,
            default_source=request.filename,
            options=index_options,
            commit=False,
        ).chunk_result
        if persist_result is None:
            raise RuntimeError("Chunk indexing returned no result")
        if not persist_result.chunk_ids:
            raise RuntimeError("No chunks were indexed")
        if not persist_result.db_chunks:
            raise RuntimeError("Database chunks were not persisted")

        # Update document stats and status.
        db_document.chunk_count = len(request.chunks)
        db_document.total_characters = persist_result.total_characters
        db_document.status = 'completed'
        db_document.processing_progress = 100
        db_document.current_stage = 'completed'
        db.commit()
        db.refresh(db_document)

        if pipeline_effective.kg_enabled:
            try:
                prompt_template_id = None
                raw_tid = (getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_ID", "") or "").strip()
                if raw_tid:
                    try:
                        prompt_template_id = UUID(raw_tid)
                    except ValueError:
                        logger.warning("Invalid KG_EXTRACT_PROMPT_TEMPLATE_ID: %s", raw_tid[:50])
                await extract_events(
                    chunk_ids=persist_result.chunk_ids,
                    tenant_id=tenant_id,
                    chunks=persist_result.db_chunks,
                    index_options=index_options,
                    prompt_template_id=prompt_template_id,
                    prompt_template_key=(getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", "") or "").strip() or None,
                    prompt_ab_experiment_key=(getattr(settings, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", "") or "").strip() or None,
                    ab_user_key=account_id,
                )
            except Exception as exc:
                # KG extraction is optional; failures do not block the main flow.
                logger.warning("KG extraction failed for document %s: %s", document_id, str(exc)[:200])

        return db_document

    except Exception as e:
        db.rollback()
        # Best-effort cleanup for partially indexed vectors / BM25
        with contextlib.suppress(Exception):
            Indexer(db).delete_chunk_indexes(tenant_id=tenant_id, document_id=document_id)
        db_document.status = 'failed'
        db_document.processing_progress = 0
        db_document.current_stage = 'failed'
        db_document.error_message = str(e)
        db.commit()
        db.refresh(db_document)
        raise HTTPException(status_code=500, detail=f"Failed to create document with manual chunks: {str(e)}")


@router.post("/chunk-preview", response_model=ChunkPreviewResponse)
async def preview_chunking(
    request: Request,
    file: UploadFile = File(...),
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    parser_backend: str = Form(default=settings.DEFAULT_PARSER_BACKEND),
    chunk_strategy: str = Form(default=settings.DEFAULT_CHUNK_STRATEGY),
    dataset_id: Optional[str] = Form(default=None),
    governance_enabled: Optional[bool] = Form(default=None),
    governance_remove_toc_lines: Optional[bool] = Form(default=None),
    governance_remove_noise_lines: Optional[bool] = Form(default=None),
    governance_unwrap_lines: Optional[bool] = Form(default=None),
    governance_remove_common_lines: Optional[bool] = Form(default=None),
    governance_unwrap_max_line_length: Optional[int] = Form(default=None),
    governance_noise_min_chars: Optional[int] = Form(default=None),
    governance_noise_ratio_threshold: Optional[float] = Form(default=None),
    governance_common_lines_min_docs: Optional[int] = Form(default=None),
    governance_common_lines_min_ratio: Optional[float] = Form(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
    # Parameter validation.
    if chunk_size < 100 or chunk_size > 4000:
        raise HTTPException(status_code=400, detail="chunk_size must be between 100 and 4000")
    if chunk_overlap < 0 or chunk_overlap > 1000:
        raise HTTPException(status_code=400, detail="chunk_overlap must be between 0 and 1000")
    if chunk_overlap >= chunk_size:
        raise HTTPException(status_code=400, detail="chunk_overlap must be less than chunk_size")

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
        file_size = int(await save_upload_file(file, temp_path, max_bytes=settings.MAX_FILE_SIZE) or 0)
        if file_size <= 0:
            with contextlib.suppress(OSError):
                file_size = int(temp_path.stat().st_size)

        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
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
        governance_kwargs = {
            "remove_toc_lines": pipeline_effective.governance_remove_toc_lines,
            "remove_noise_lines": pipeline_effective.governance_remove_noise_lines,
            "unwrap_lines": pipeline_effective.governance_unwrap_lines,
            "remove_common_lines": pipeline_effective.governance_remove_common_lines,
            "unwrap_max_line_length": pipeline_effective.governance_unwrap_max_line_length,
            "noise_min_chars": pipeline_effective.governance_noise_min_chars,
            "noise_ratio_threshold": pipeline_effective.governance_noise_ratio_threshold,
            "common_lines_min_docs": pipeline_effective.governance_common_lines_min_docs,
            "common_lines_min_ratio": pipeline_effective.governance_common_lines_min_ratio,
        }

        # Ragflow preset uses a separate branch (self-parse + chunk).
        if resolved_chunk_strategy in chunker_factory.RAGFLOW_STRATEGIES:
            result = await run_subprocess_worker(
                tenant_id=tenant_id,
                payload={
                    "action": "ragflow_chunk",
                    "tenant_id": str(tenant_id),
                    "file_path": str(temp_path),
                    "strategy": resolved_chunk_strategy,
                    "mode": "preview",
                },
                disconnect_check=request.is_disconnected,
                timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
            )
            chunks = [
                Document(
                    page_content=str(item.get("page_content") or ""),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    id=item.get("id") if isinstance(item.get("id"), str) else None,
                )
                for item in (result.get("documents") or [])
                if isinstance(item, dict)
            ]
            resolved_backend = "ragflow"
            documents = []  # Ragflow already handled.
            if pipeline_effective.governance_enabled:
                chunks, _stats = governance_processor.clean_documents(
                    chunks,
                    **governance_kwargs,
                )
        else:
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
            if pipeline_effective.governance_enabled:
                documents, _stats = governance_processor.clean_documents(
                    documents,
                    **governance_kwargs,
                )

            chunker = chunker_factory.get_chunker(
                resolved_chunk_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
            chunks = chunker.split_documents(documents)

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
                    or ("data:image" in content.lower())
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

        # Merge original text: use parsed pages for non-ragflow, chunks for ragflow,
        # to keep original_text aligned with chunks for frontend highlighting.
        page_texts = []
        current_pos = 0
        ragflow_chunk_start_map: dict[int, int] = {}

        if documents:
            for doc in documents:
                text = doc.page_content
                page_num = doc.metadata.get('page')
                page_texts.append({
                    'text': text,
                    'page': page_num,
                    'start': current_pos,
                    'end': current_pos + len(text)
                })
                current_pos += len(text) + 1  # +1 for separator

            full_text = "\n".join([p['text'] for p in page_texts]) if page_texts else ""
            page_start_map = {item['page']: item['start'] for item in page_texts} if page_texts else {}
        else:
            # Ragflow preset: documents is empty; build "locatable" text from chunks.
            # Note: not a strict original full text, but keeps highlighting stable.
            parts: list[str] = []
            for idx, chunk in enumerate(chunks):
                text = chunk.page_content or ""
                parts.append(text)
                ragflow_chunk_start_map[idx] = current_pos
                current_pos += len(text) + 2  # +2 for "\n\n"

            full_text = "\n\n".join(parts) if parts else ""
            page_start_map = {}

        # Build response.
        chunk_items: List[ChunkPreviewItem] = []
        for idx, chunk in enumerate(chunks):
            meta = chunk.metadata or {}
            page_num = meta.get('page') or meta.get('page_number')
            local_start = meta.get('start_char')

            if idx in ragflow_chunk_start_map:
                start_idx = ragflow_chunk_start_map[idx]
            elif local_start is not None and page_num in page_start_map:
                start_idx = page_start_map[page_num] + int(local_start)
            elif page_num in page_start_map:
                start_idx = page_start_map[page_num]
            elif meta.get("start_char") is not None:
                start_idx = int(meta.get("start_char"))
            else:
                start_idx = 0

            end_idx = start_idx + len(chunk.page_content)

            chunk_items.append(ChunkPreviewItem(
                index=idx,
                content=chunk.page_content,
                length=len(chunk.page_content),
                start_index=start_idx,
                end_index=end_idx,
                page_number=page_num,
                metadata=chunk.metadata
            ))

        return ChunkPreviewResponse(
            filename=file.filename,
            file_type=file_ext.lstrip('.'),
            file_size=file_size,
            total_chunks=len(chunks),
            total_characters=len(full_text),
            params=ChunkPreviewParams(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                unit="tokens" if resolved_chunk_strategy == "langchain_token" else "chars",
            ),
            chunks=chunk_items,
            original_text=full_text if len(full_text) <= 100000 else None,  # Skip original text > 100 KB.
            parser_backend=resolved_backend,
            chunk_strategy=resolved_chunk_strategy
        )

    except SubprocessCancelled:
        raise HTTPException(status_code=499, detail="Client closed request")
    except SubprocessWorkerError as e:
        err_type = (e.details or {}).get("type")
        if err_type == "ValueError":
            raise HTTPException(status_code=400, detail=str(e))
        logger.error("Subprocess worker failed during chunk preview: %s", str(e)[:200])
        raise HTTPException(status_code=500, detail="Failed to preview chunking")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to preview chunking: {str(e)}")
    finally:
        try:
            if run_dir.exists():
                shutil.rmtree(run_dir, ignore_errors=True)
        except Exception:
            pass


# ==================== MinerU batch upload API ====================

@router.post("/batch-upload/apply-urls", response_model=BatchUploadResponse)
async def apply_batch_upload_urls(
    request: BatchUploadRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Batch request file upload URLs (MinerU online parsing).

    Use case: batch upload local files for parsing.

    Flow:
    1. Call this endpoint to request upload URLs (up to 200 files)
    2. Upload files to returned URLs (PUT; no Content-Type needed)
    3. After upload, the system submits parsing tasks automatically
    4. Query status using batch_id

    Notes:
    - Upload links are valid for 24 hours
    - No Content-Type header required for uploads
    - No manual submit needed; the system scans and processes automatically

    Example:
        # Step 1: request upload URLs
        response = requests.post("http://localhost:8000/api/v1/documents/batch-upload/apply-urls", headers={
            "X-User-ID": "demo",
        }, json={
            "files": [
                {"name": "file1.pdf", "data_id": "doc1"},
                {"name": "file2.pdf", "data_id": "doc2"}
            ]
        })

        # Step 2: upload files
        batch_id = response.json()["batch_id"]
        urls = response.json()["file_urls"]

        for i, url in enumerate(urls):
            with open(f"file{i+1}.pdf", "rb") as f:
                requests.put(url, data=f)

        # Step 3: query status
        requests.get(f"http://localhost:8000/api/v1/documents/batch-upload/status/{batch_id}", headers={
            "X-User-ID": "demo",
        })
    """
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = (member.role or "").lower()
    if role not in EDIT_ROLES:
        raise HTTPException(status_code=403, detail="No permission to apply upload URLs")

    try:
        result = await mineru_service.aapply_batch_upload_urls(
            files=[f.model_dump() for f in request.files]
        )

        return BatchUploadResponse(
            batch_id=result["batch_id"],
            file_urls=result["file_urls"],
            files=request.files
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to apply upload URLs: {str(e)}")


@router.get("/batch-upload/status/{batch_id}", response_model=BatchTaskStatus)
async def get_batch_task_status(
    batch_id: str,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Query batch parsing task status.

    Args:
        batch_id: Batch ID (from apply upload URLs).

    Returns:
        Task status info, including progress and completion counts.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    try:
        status = await mineru_service.aget_task_status(batch_id)

        # Normalize to a standard format.
        return BatchTaskStatus(
            batch_id=batch_id,
            status=status.get("status", "pending"),
            total_files=status.get("total_files", 0),
            completed_files=status.get("completed_files", 0),
            failed_files=status.get("failed_files", 0),
            progress=status.get("progress", 0),
            result_url=status.get("result_url"),
            error=status.get("error")
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get task status: {str(e)}")
