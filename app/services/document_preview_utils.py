import contextlib
import hashlib
import json
import math
import re
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, TypedDict
from urllib.parse import unquote, urlparse
from uuid import UUID

from fastapi import HTTPException
from langchain_core.documents import Document
from PIL import Image
from sqlalchemy.orm import Session

from app.api.schemas.document import (
    ChunkPreviewItem,
    ChunkPreviewQualityGate,
    ChunkPreviewQualityReason,
    ChunkPreviewRecommendationPatch,
    ChunkPreviewReviewSignals,
    ChunkPreviewStats,
)
from app.core.config import settings
from app.rag.core.logging import get_logger
from app.storage.object.minio import minio_service

logger = get_logger("documents.preview_utils")
_document_image_logger = get_logger("api.documents")

UUID_PATTERN = r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
PREVIEW_IMAGE_REF_RE = re.compile(rf"(?:https?://[^\s)\"']+)?/api/v1/documents/image/({UUID_PATTERN})(?![0-9A-Za-z_-])")
MINIO_IMAGE_REF_RE = re.compile(r"(?:https?://[^\s)\"']+)?/api/v1/documents/image-url/([^\s)\"']+)")
PREVIEW_MD_IMAGE_REF_RE = re.compile(
    r"!\[[^\]]*\]\(\s*(?:<)?([^)\s>]+)(?:>)?(?:\s+['\"][^'\"]*['\"])?\s*\)",
    flags=re.IGNORECASE,
)
PREVIEW_HTML_IMAGE_REF_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", flags=re.IGNORECASE)
DATA_IMAGE_PREFIX = "data:image"
IMAGE_FILE_EXT_JPEG = ".jpeg"
IMAGE_FILE_EXT_WEBP = ".webp"
LOCAL_PREVIEW_IMAGE_EXTS = {".png", ".jpg", IMAGE_FILE_EXT_JPEG, IMAGE_FILE_EXT_WEBP, ".gif", ".bmp"}
PREVIEW_IMAGE_EXTENSIONS = [".png", ".jpg", IMAGE_FILE_EXT_JPEG, IMAGE_FILE_EXT_WEBP, ".gif", ".bmp"]
REMOTE_PREVIEW_IMAGE_SCHEMES = {"http", "https", "data", "blob"}


class _ChunkHistogramBin(TypedDict):
    label: str
    min: int
    max: int
    count: int


def _rewrite_preview_images_to_minio(
    text: str,
    *,
    tenant_id: str,
    dataset_id: str,
    document_id: str,
    account_id: str,
    images_dir: Path,
    local_id_to_img_id: dict[str, str],
    digest_to_img_id: dict[str, str],
    db: Session | None = None,
    start_index: int = 0,
) -> tuple[str, list[str], int]:
    """
    Convert preview-time local image refs into persisted MinIO image-url refs.

    Manual chunks share the preview image cache with the document preview
    endpoint. When MinIO is enabled, persisted chunks must not retain local
    `/documents/image/{uuid}` refs because those files are temporary.
    """
    if not isinstance(text, str) or not text:
        return text, [], start_index

    existing = _existing_minio_image_refs(text)
    matches = _preview_image_matches(text)
    if not matches:
        return text, existing, start_index
    local_ids = _iter_unique_preview_local_ids(matches)

    if not settings.MINIO_ENABLED:
        _claim_preview_refs_without_minio(
            local_ids=local_ids,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            account_id=account_id,
            images_dir=images_dir,
            db=db,
        )
        return text, existing, start_index

    referenced_img_ids, start_index = _persist_preview_refs_to_minio(
        local_ids=local_ids,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        account_id=account_id,
        images_dir=images_dir,
        local_id_to_img_id=local_id_to_img_id,
        digest_to_img_id=digest_to_img_id,
        db=db,
        start_index=start_index,
        existing_refs=existing,
    )

    return (
        PREVIEW_IMAGE_REF_RE.sub(lambda match: _replace_preview_ref(match, local_id_to_img_id), text),
        referenced_img_ids,
        start_index,
    )


def _existing_minio_image_refs(text: str) -> list[str]:
    existing: list[str] = []
    for match in MINIO_IMAGE_REF_RE.finditer(text):
        value = match.group(1).strip()
        if value and value not in existing:
            existing.append(value)
    return existing


def _preview_image_matches(text: str) -> list[re.Match[str]]:
    if "/api/v1/documents/image/" not in text:
        return []
    matches = list(PREVIEW_IMAGE_REF_RE.finditer(text))
    max_inline_images = max(0, settings.MAX_INLINE_IMAGES or 0)
    return matches[:max_inline_images] if max_inline_images and len(matches) > max_inline_images else matches


def _iter_unique_preview_local_ids(matches: list[re.Match[str]]) -> list[str]:
    seen_local_ids: set[str] = set()
    unique_local_ids: list[str] = []
    for match in matches:
        local_id = _preview_local_image_id(match.group(1))
        if not local_id or local_id in seen_local_ids:
            continue
        seen_local_ids.add(local_id)
        unique_local_ids.append(local_id)
    return unique_local_ids


def _preview_local_image_id(raw_id: str | None) -> str | None:
    if not raw_id:
        return None
    try:
        return uuid.UUID(raw_id).hex
    except ValueError:
        return None


def _replace_preview_ref(match: re.Match[str], local_id_to_img_id: dict[str, str]) -> str:
    local_id = _preview_local_image_id(match.group(1))
    if not local_id:
        return match.group(0)
    img_id = local_id_to_img_id.get(local_id)
    if not img_id:
        return match.group(0)
    return f"/api/v1/documents/image-url/{img_id}"


def _claim_preview_refs_without_minio(
    *,
    local_ids: list[str],
    tenant_id: str,
    dataset_id: str,
    document_id: str,
    account_id: str,
    images_dir: Path,
    db: Session | None,
) -> None:
    for local_id in local_ids:
        if _find_preview_image_path(images_dir, local_id) is None:
            raise HTTPException(status_code=422, detail="Preview image could not be persisted")
        promoted = _claim_preview_image_for_document(
            db=db,
            images_dir=images_dir,
            local_id=local_id,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            account_id=account_id,
        )
        if not promoted:
            raise HTTPException(status_code=403, detail="Preview image cannot be reused for this document")


def _persist_preview_refs_to_minio(
    *,
    local_ids: list[str],
    tenant_id: str,
    dataset_id: str,
    document_id: str,
    account_id: str,
    images_dir: Path,
    local_id_to_img_id: dict[str, str],
    digest_to_img_id: dict[str, str],
    db: Session | None,
    start_index: int,
    existing_refs: list[str],
) -> tuple[list[str], int]:
    referenced_img_ids: list[str] = list(existing_refs)
    max_bytes = _preview_image_max_bytes()
    for local_id in local_ids:
        img_id, start_index = _resolve_preview_image_ref(
            local_id=local_id,
            images_dir=images_dir,
            max_bytes=max_bytes,
            local_id_to_img_id=local_id_to_img_id,
            digest_to_img_id=digest_to_img_id,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            account_id=account_id,
            db=db,
            start_index=start_index,
        )
        if not img_id:
            raise HTTPException(status_code=422, detail="Preview image could not be persisted")
        if img_id not in referenced_img_ids:
            referenced_img_ids.append(img_id)
    return referenced_img_ids, start_index


def _preview_image_max_bytes() -> int:
    max_bytes = settings.MAX_INLINE_IMAGE_BYTES or 10_000_000
    return max(1_000_000, max_bytes)


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
    img = None
    converted = None
    try:
        img = Image.open(BytesIO(raw))
        if img.mode in ("RGBA", "P"):
            converted = img.convert("RGB")
            out_img = converted
        else:
            out_img = img
        out = BytesIO()
        out_img.save(out, format="JPEG", quality=85, optimize=True)
        return out.getvalue()
    except Exception as exc:  # noqa: BLE001
        _document_image_logger.warning("Failed converting preview image %s to JPEG: %s", local_id, str(exc)[:200])
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
        _document_image_logger.warning("Preview image upload to MinIO failed; skipping image: %s", str(exc)[:200])
        return None, start_index
    digest_to_img_id[digest] = img_id
    return img_id, start_index


def _claim_preview_image_for_document(
    *,
    db: Session | None,
    images_dir: Path,
    local_id: str,
    tenant_id: str,
    dataset_id: str,
    document_id: str,
    account_id: str,
) -> bool:
    # The legacy lookup imports PREVIEW_IMAGE_REF_RE here, so defer it to avoid a module cycle.
    from app.services.document_preview_legacy import legacy_preview_ref_belongs_to_document

    binding_path = images_dir / f"{local_id}.json"
    binding = _load_preview_owner_binding(images_dir=images_dir, preview_id=local_id)
    if binding is not None:
        return _promote_preview_owner_binding(
            images_dir=images_dir,
            preview_id=local_id,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            account_id=account_id,
        )
    if binding_path.exists() or db is None:
        return False
    try:
        tenant_uuid = UUID(tenant_id)
        dataset_uuid = UUID(dataset_id)
        document_uuid = UUID(document_id)
    except ValueError:
        return False
    if not legacy_preview_ref_belongs_to_document(
        db,
        tenant_id=tenant_uuid,
        document_id=document_uuid,
        preview_id=local_id,
    ):
        return False
    return _write_preview_owner_binding(
        images_dir=images_dir,
        preview_id=local_id,
        binding={
            "tenant_id": str(tenant_uuid),
            "dataset_id": str(dataset_uuid),
            "document_id": str(document_uuid),
        },
    )


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
    account_id: str,
    db: Session | None,
    start_index: int,
) -> tuple[str | None, int]:
    img_id = local_id_to_img_id.get(local_id)
    if img_id:
        return img_id, start_index

    img_path = _find_preview_image_path(images_dir, local_id)
    if img_path is None:
        return None, start_index

    if not _claim_preview_image_for_document(
        db=db,
        images_dir=images_dir,
        local_id=local_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        account_id=account_id,
    ):
        raise HTTPException(status_code=403, detail="Preview image cannot be reused for this document")

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


def _ensure_preview_page_indices(documents: list[Document]) -> None:
    """
    Ensure each parsed Document has a stable per-document index for preview offset rebasing.

    Some parsers emit multiple Documents without a unique `metadata.page` (or with duplicates).
    Chunk preview joins these docs with "\\n" and returns global `start_index`/`end_index` offsets;
    without a stable key, mapping by `page` can collide and misplace chunks.
    """
    for i, doc in enumerate(documents or []):
        meta = dict(doc.metadata)
        # Keep existing value if present; otherwise assign a deterministic 1-based index.
        meta.setdefault("page_index", i + 1)
        doc.metadata = meta


def _preview_chunk_has_asset(meta: dict[str, Any], content: str | None = None) -> bool:
    doc_type = meta.get("doc_type_kwd")
    if doc_type is not None:
        doc_type = doc_type.lower()
    if doc_type in {"image", "table"}:
        return True
    if meta.get("image") is not None:
        return True
    if isinstance(meta.get("image_path"), str) and meta.get("image_path").strip():
        return True
    if meta.get("img_id") or meta.get("image_id") or meta.get("image_url"):
        return True
    if content:
        lower = content.lower()
        if (DATA_IMAGE_PREFIX in lower) or PREVIEW_IMAGE_REF_RE.search(content) or MINIO_IMAGE_REF_RE.search(content):
            return True
    return False


def _preview_page_text_by_index(documents: list[Document]) -> dict[int, str]:
    page_text: dict[int, str] = {}
    for i, doc in enumerate(documents):
        meta = dict(doc.metadata)
        try:
            page_index = int(meta.get("page_index") or (i + 1))
        except (OverflowError, TypeError, ValueError):
            page_index = i + 1
        page_text[page_index] = doc.page_content
    return page_text


def _preview_page_index_of(chunk: Document) -> int | None:
    meta = chunk.metadata
    raw = meta.get("page_index")
    try:
        return int(raw) if raw is not None else None
    except (OverflowError, TypeError, ValueError):
        return None


def _preview_local_range(meta: dict[str, Any]) -> tuple[int, int] | None:
    try:
        start = int(meta.get("start_char")) if meta.get("start_char") is not None else None
        end = int(meta.get("end_char")) if meta.get("end_char") is not None else None
    except (OverflowError, TypeError, ValueError):
        return None
    if start is None or end is None or end < start:
        return None
    return start, end


def _preview_chunk_mergeable(chunk: Document, *, page_index: int | None, page_text: dict[int, str]) -> bool:
    meta = dict(chunk.metadata)
    return (
        page_index is not None
        and page_index in page_text
        and not _preview_chunk_has_asset(meta, chunk.page_content)
        and not (meta.get("chunk_role") or meta.get("parent_id"))
        and _preview_local_range(meta) is not None
    )


def _merge_preview_chunks_on_page(
    a: Document, b: Document, *, page_index: int, page_text: dict[int, str]
) -> Document | None:
    text = page_text.get(page_index)
    if text is None:
        return None

    meta_a = dict(a.metadata)
    meta_b = dict(b.metadata)
    range_a = _preview_local_range(meta_a)
    range_b = _preview_local_range(meta_b)
    if range_a is None or range_b is None:
        return None

    start_local = max(0, min(min(range_a[0], range_b[0]), len(text)))
    end_local = max(start_local, min(max(range_a[1], range_b[1]), len(text)))
    meta_a["start_char"] = start_local
    meta_a["end_char"] = end_local
    meta_a["merged_small_chunks"] = int(meta_a.get("merged_small_chunks") or 0) + 1
    return Document(page_content=text[start_local:end_local], metadata=meta_a, id=a.id)


def _merge_preview_pair_or_append(
    out: list[Document], first: Document, second: Document, *, page_index: int, page_text: dict[int, str]
) -> None:
    merged = _merge_preview_chunks_on_page(first, second, page_index=page_index, page_text=page_text)
    if merged is None:
        out.extend([first, second])
        return
    out.append(merged)


def _flush_pending_preview_chunk(out: list[Document], pending: Document | None) -> None:
    if pending is not None:
        out.append(pending)


def _append_non_mergeable_preview_chunk(
    out: list[Document], pending: Document | None, chunk: Document
) -> tuple[None, None]:
    _flush_pending_preview_chunk(out, pending)
    out.append(chunk)
    return None, None


def _merge_short_preview_chunk_with_previous(
    *,
    out: list[Document],
    chunk: Document,
    page_index: int | None,
    page_text: dict[int, str],
) -> bool:
    if not out:
        return False
    prev = out[-1]
    prev_page = _preview_page_index_of(prev)
    if prev_page != page_index or not _preview_chunk_mergeable(prev, page_index=prev_page, page_text=page_text):
        return False
    merged = (
        _merge_preview_chunks_on_page(prev, chunk, page_index=page_index, page_text=page_text)
        if page_index is not None
        else None
    )
    if merged is None:
        return False
    out[-1] = merged
    return True


def _consume_mergeable_preview_chunk(
    *,
    out: list[Document],
    pending: Document | None,
    chunk: Document,
    page_index: int | None,
    page_text: dict[int, str],
    min_chars: int,
) -> tuple[Document | None, int | None]:
    if pending is not None:
        if page_index is not None:
            _merge_preview_pair_or_append(out, pending, chunk, page_index=page_index, page_text=page_text)
        else:
            out.extend([pending, chunk])
        return None, None

    if len((chunk.page_content).strip()) >= min_chars:
        out.append(chunk)
        return None, None

    if _merge_short_preview_chunk_with_previous(out=out, chunk=chunk, page_index=page_index, page_text=page_text):
        return None, None

    return chunk, page_index


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
    min_chars = max(0, min_chars or 0)
    if min_chars <= 0 or not documents or not chunks:
        return chunks

    page_text = _preview_page_text_by_index(documents)
    out: list[Document] = []
    pending: Document | None = None
    pending_page: int | None = None

    for chunk in chunks:
        page_index = _preview_page_index_of(chunk)
        if pending is not None and page_index != pending_page:
            _flush_pending_preview_chunk(out, pending)
            pending = None
            pending_page = None

        if not _preview_chunk_mergeable(chunk, page_index=page_index, page_text=page_text):
            pending, pending_page = _append_non_mergeable_preview_chunk(out, pending, chunk)
            continue

        pending, pending_page = _consume_mergeable_preview_chunk(
            out=out,
            pending=pending,
            chunk=chunk,
            page_index=page_index,
            page_text=page_text,
            min_chars=min_chars,
        )

    _flush_pending_preview_chunk(out, pending)

    return out


def _preview_images_dir(tenant_id: UUID) -> Path:
    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir


def _coerce_preview_owner_uuid(value: object) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return str(UUID(raw))
    except ValueError:
        return None


def _preview_owner_binding(
    *, tenant_id: UUID, meta: dict[str, Any], account_id: str | None = None
) -> dict[str, str] | None:
    document_id = _coerce_preview_owner_uuid(meta.get("document_id"))
    dataset_id = _coerce_preview_owner_uuid(meta.get("dataset_id"))
    if document_id and dataset_id:
        return {
            "tenant_id": str(tenant_id),
            "dataset_id": dataset_id,
            "document_id": document_id,
        }
    owner_account_id = account_id
    if owner_account_id is not None:
        owner_account_id = owner_account_id.strip()
    if owner_account_id:
        return {"tenant_id": str(tenant_id), "account_id": owner_account_id}
    return None


def _write_preview_owner_binding(*, images_dir: Path, preview_id: str, binding: dict[str, str] | None) -> bool:
    if not binding:
        return False
    sidecar_path = images_dir / f"{preview_id}.json"
    try:
        sidecar_path.write_text(
            json.dumps(binding, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Failed to persist preview image binding: %s", str(exc)[:200])
        return False
    return True


def _load_preview_owner_binding(*, images_dir: Path, preview_id: str) -> dict[str, str | None] | None:
    sidecar_path = images_dir / f"{preview_id}.json"
    try:
        raw = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    tenant_id = _coerce_preview_owner_uuid(raw.get("tenant_id"))
    dataset_id = _coerce_preview_owner_uuid(raw.get("dataset_id"))
    document_id = _coerce_preview_owner_uuid(raw.get("document_id"))
    account_id = raw.get("account_id")
    if account_id is not None:
        if not isinstance(account_id, str):
            return None
        account_id = account_id.strip()
    document_bound = bool(dataset_id and document_id and not account_id)
    account_bound = bool(account_id and not dataset_id and not document_id)
    if not tenant_id or not (document_bound or account_bound):
        return None
    return {
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "document_id": document_id,
        "account_id": account_id,
    }


def _promote_preview_owner_binding(
    *,
    images_dir: Path,
    preview_id: str,
    tenant_id: str,
    dataset_id: str,
    document_id: str,
    account_id: str,
) -> bool:
    binding = _load_preview_owner_binding(images_dir=images_dir, preview_id=preview_id)
    if not binding:
        return False
    if binding["tenant_id"] != tenant_id.strip():
        return False
    bound_dataset_id = binding["dataset_id"]
    bound_document_id = binding["document_id"]
    if bound_dataset_id and bound_document_id:
        return bound_dataset_id == (dataset_id).strip() and bound_document_id == (document_id).strip()
    if binding["account_id"] != account_id.strip():
        return False
    return _write_preview_owner_binding(
        images_dir=images_dir,
        preview_id=preview_id,
        binding={
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "document_id": document_id,
        },
    )


def _save_extracted_preview_image(image_obj: object, out_path: Path) -> None:
    img = Image.open(BytesIO(bytes(image_obj))) if isinstance(image_obj, (bytes, bytearray)) else image_obj
    with contextlib.suppress(Exception):
        if getattr(img, "mode", None) != "RGB":
            img = img.convert("RGB")
    img.save(out_path, format="JPEG", quality=85, optimize=True)


def _close_preview_image_object(image_obj: object) -> None:
    if isinstance(image_obj, (bytes, bytearray)) or not hasattr(image_obj, "close"):
        return
    with contextlib.suppress(Exception):
        image_obj.close()


def _materialize_extracted_preview_image_doc(
    doc: Document,
    *,
    tenant_id: UUID,
    account_id: str | None,
    images_dir: Path,
) -> None:
    meta = doc.metadata or {}

    image_obj = meta.get("image")
    if image_obj is None:
        return

    doc_type = meta.get("doc_type_kwd")
    if doc_type is not None:
        doc_type = doc_type.lower()
    if doc_type != "image":
        meta.pop("image", None)
        doc.metadata = meta
        return

    preview_id = uuid.uuid4().hex
    out_path = images_dir / f"{preview_id}.jpg"
    url = f"/api/v1/documents/image/{preview_id}"
    owner_binding = _preview_owner_binding(tenant_id=tenant_id, meta=meta, account_id=account_id)
    persisted = False
    try:
        _save_extracted_preview_image(image_obj, out_path)
        persisted = _write_preview_owner_binding(
            images_dir=images_dir,
            preview_id=preview_id,
            binding=owner_binding,
        )
        if not persisted:
            out_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Failed to persist preview image: %s", str(exc)[:200])
    finally:
        meta.pop("image", None)
        doc.metadata = meta
        _close_preview_image_object(image_obj)

    if not persisted:
        return

    caption = doc.page_content.strip()
    img_md = f"![image]({url})"
    doc.page_content = f"{img_md}\n\n{caption}" if caption else img_md
    meta["preview_image_id"] = preview_id
    meta["preview_image_url"] = url
    doc.metadata = meta


def _materialize_extracted_images_for_preview(
    documents: list[Document], *, tenant_id: UUID, account_id: str | None = None
) -> list[Document]:
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

    images_dir = _preview_images_dir(tenant_id)
    for doc in documents:
        _materialize_extracted_preview_image_doc(
            doc,
            tenant_id=tenant_id,
            account_id=account_id,
            images_dir=images_dir,
        )

    return documents


def _preview_local_image_limits() -> tuple[int, int]:
    max_inline_images = max(0, settings.MAX_INLINE_IMAGES or 0)
    max_image_bytes = settings.MAX_INLINE_IMAGE_BYTES or 10_000_000
    return max_inline_images, max(1_000_000, max_image_bytes)


def _preview_content_image_refs(content: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pattern in (PREVIEW_MD_IMAGE_REF_RE, PREVIEW_HTML_IMAGE_REF_RE):
        for match in pattern.finditer(content):
            ref = match.group(1).strip()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            found.append(ref)
    return found


def _preview_doc_asset_base_dir(doc: Document) -> Path | None:
    meta = doc.metadata or {}

    base_dir_raw = meta.get("asset_base_dir")
    if not isinstance(base_dir_raw, str) or not base_dir_raw.strip():
        return None

    base_dir = Path(base_dir_raw.strip()).resolve(strict=False)
    if not base_dir.exists() or not base_dir.is_dir():
        return None
    return base_dir.resolve(strict=False)


def _preview_local_ref_skippable(ref: str) -> bool:
    parsed_ref = urlparse(ref)
    scheme = (parsed_ref.scheme).lower().strip()
    if scheme in REMOTE_PREVIEW_IMAGE_SCHEMES or (parsed_ref.netloc).strip():
        return True
    ref_lower = ref.lower()
    return "/api/v1/documents/image-url/" in ref_lower or "/api/v1/documents/image/" in ref_lower


def _preview_ref_path_candidates(ref: str) -> list[str]:
    ref_path = ref.split("?", 1)[0].split("#", 1)[0].strip()
    if not ref_path:
        return []
    with contextlib.suppress(Exception):
        ref_path = unquote(ref_path)
    candidates = [ref_path]
    if ref_path.startswith("/") and not ref_path.startswith("/api/"):
        candidates.insert(0, ref_path.lstrip("/"))
    return candidates


def _resolve_preview_local_image_path(ref: str, *, base_dir_resolved: Path) -> Path | None:
    ref_stripped = ref.strip()
    if not ref_stripped or _preview_local_ref_skippable(ref_stripped):
        return None

    for candidate in _preview_ref_path_candidates(ref_stripped):
        if not candidate:
            continue
        with contextlib.suppress(Exception):
            path_obj = Path(candidate)
            path_obj = (
                path_obj.resolve(strict=False)
                if path_obj.is_absolute()
                else (base_dir_resolved / path_obj).resolve(strict=False)
            )
            path_obj.relative_to(base_dir_resolved)
            if path_obj.exists() and path_obj.is_file():
                return path_obj
    return None


def _read_preview_local_image(path: Path, *, max_image_bytes: int) -> tuple[bytes, str] | None:
    try:
        if path.stat().st_size > max_image_bytes:
            return None
        raw_bytes = path.read_bytes()
    except Exception:
        return None
    if not raw_bytes or len(raw_bytes) > max_image_bytes:
        return None
    return raw_bytes, path.suffix.lower()


def _convert_preview_local_image_bytes(raw_bytes: bytes, *, ext: str) -> tuple[bytes, str] | None:
    if ext in LOCAL_PREVIEW_IMAGE_EXTS:
        return raw_bytes, ext
    try:
        img = Image.open(BytesIO(raw_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        out = BytesIO()
        img.save(out, format="JPEG", quality=85, optimize=True)
        return out.getvalue(), ".jpg"
    except Exception as exc:
        logger.warning("Failed converting preview local image to JPEG: %s", str(exc)[:200])
        return None


def _preview_cached_or_persisted_image_url(
    image_bytes: bytes,
    *,
    out_ext: str,
    digest_cache: dict[str, tuple[str, str]],
    images_dir: Path,
    owner_binding: dict[str, str] | None,
) -> str | None:
    if not owner_binding:
        return None
    digest = hashlib.sha256(image_bytes).hexdigest()
    binding_digest = hashlib.sha256(
        json.dumps(owner_binding, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    cache_key = f"{digest}:{binding_digest}"
    cached = digest_cache.get(cache_key)
    if cached:
        preview_id, cached_ext = cached
        out_ext = cached_ext
    else:
        preview_id = uuid.uuid4().hex
        out_path = images_dir / f"{preview_id}{out_ext}"
        try:
            out_path.write_bytes(image_bytes)
            if not _write_preview_owner_binding(
                images_dir=images_dir,
                preview_id=preview_id,
                binding=owner_binding,
            ):
                out_path.unlink(missing_ok=True)
                return None
        except Exception as exc:
            logger.warning("Failed to persist preview local image: %s", str(exc)[:200])
            return None
        digest_cache[cache_key] = (preview_id, out_ext)
    return f"/api/v1/documents/image/{preview_id}"


def _preview_local_image_replacements(
    refs: list[str],
    *,
    owner_binding: dict[str, str] | None,
    base_dir_resolved: Path,
    max_image_bytes: int,
    digest_cache: dict[str, tuple[str, str]],
    images_dir: Path,
) -> dict[str, str]:
    replacements: dict[str, str] = {}
    for ref in refs:
        resolved_path = _resolve_preview_local_image_path(ref, base_dir_resolved=base_dir_resolved)
        if resolved_path is None:
            continue
        image = _read_preview_local_image(resolved_path, max_image_bytes=max_image_bytes)
        if image is None:
            continue
        converted = _convert_preview_local_image_bytes(image[0], ext=image[1])
        if converted is None:
            continue
        url = _preview_cached_or_persisted_image_url(
            converted[0],
            out_ext=converted[1],
            digest_cache=digest_cache,
            images_dir=images_dir,
            owner_binding=owner_binding,
        )
        if url:
            replacements[ref] = url
    return replacements


def _replace_preview_image_ref(match: re.Match, replacements: dict[str, str]) -> str:
    raw = match.group(1)
    new = replacements.get(raw.strip())
    return match.group(0).replace(raw, new, 1) if new else match.group(0)


def _rewrite_preview_local_image_refs(content: str, replacements: dict[str, str]) -> str:
    content = PREVIEW_MD_IMAGE_REF_RE.sub(lambda m: _replace_preview_image_ref(m, replacements), content)
    return PREVIEW_HTML_IMAGE_REF_RE.sub(lambda m: _replace_preview_image_ref(m, replacements), content)


def _materialize_local_images_for_preview(
    documents: list[Document], *, tenant_id: UUID, account_id: str | None = None
) -> list[Document]:
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

    images_dir = _preview_images_dir(tenant_id)
    max_inline_images, max_image_bytes = _preview_local_image_limits()
    digest_cache: dict[str, tuple[str, str]] = {}

    for doc in documents:
        content = doc.page_content
        if not content:
            continue

        lowered = content.lower()
        if "![" not in lowered and "<img" not in lowered:
            continue

        base_dir_resolved = _preview_doc_asset_base_dir(doc)
        if base_dir_resolved is None:
            continue
        owner_binding = _preview_owner_binding(
            tenant_id=tenant_id,
            meta=doc.metadata,
            account_id=account_id,
        )

        found = _preview_content_image_refs(content)
        if max_inline_images:
            found = found[:max_inline_images]
        if not found:
            continue

        replacements = _preview_local_image_replacements(
            found,
            owner_binding=owner_binding,
            base_dir_resolved=base_dir_resolved,
            max_image_bytes=max_image_bytes,
            digest_cache=digest_cache,
            images_dir=images_dir,
        )
        if not replacements:
            continue

        doc.page_content = _rewrite_preview_local_image_refs(content, replacements)

    return documents


def _compute_chunk_coverage_metrics_from_ranges(
    ranges: list[tuple[int, int]], *, total_characters: int
) -> dict[str, float | int]:
    """
    Compute coverage/overlap signals from chunk start/end ranges.

    Same semantics as `_compute_chunk_coverage_metrics`, but avoids requiring `ChunkPreviewItem`
    objects when callers only need lightweight stats (e.g. auto-tune).
    """
    from app.services.chunk_coverage_utils import compute_chunk_coverage_metrics_from_ranges

    return compute_chunk_coverage_metrics_from_ranges(ranges, total_characters=total_characters)


def _chunk_histogram_step(max_value: int, *, unit: Literal["chars", "tokens"], target_bins: int) -> int:
    bins = max(3, min(12, target_bins or 8))
    base = 25 if unit == "tokens" else 50
    if max_value <= 0:
        return base
    step = math.ceil((max_value / bins) / base) * base
    return max(base, step) if step > 0 else base


def _chunk_histogram_empty_bins(max_value: int, *, step: int) -> list[_ChunkHistogramBin]:
    bin_count = max(1, math.ceil((max_value + 1) / step)) if step > 0 else 1
    return [
        {
            "label": f"{i * step}-{(i + 1) * step}",
            "min": i * step,
            "max": (i + 1) * step,
            "count": 0,
        }
        for i in range(bin_count)
    ]


def _increment_chunk_histogram_bins(bins: list[_ChunkHistogramBin], values: list[int], *, step: int) -> None:
    for value in values:
        idx = value // step if step > 0 else 0
        idx = max(0, min(idx, len(bins) - 1))
        bins[idx]["count"] += 1


def _compute_chunk_length_histogram(
    lengths: list[int],
    *,
    unit: Literal["chars", "tokens"],
    target_bins: int = 8,
) -> list[_ChunkHistogramBin]:
    """
    Compute a coarse histogram for chunk length distribution.

    Returned bins use the schema:
      {label: "min-max", min: int, max: int, count: int}

    Notes:
    - Bin bounds are best-effort; the UI should treat them as descriptive, not strict.
    - We keep bin widths "round" to keep charts readable.
    """
    values = lengths
    if not values:
        return []

    max_val = max(values)
    step = _chunk_histogram_step(max_val, unit=unit, target_bins=target_bins)
    bins = _chunk_histogram_empty_bins(max_val, step=step)
    _increment_chunk_histogram_bins(bins, values, step=step)
    return bins


def _chunk_preview_item_key(chunk: ChunkPreviewItem) -> tuple[int, int, int]:
    return chunk.start_index, chunk.end_index, chunk.index


def _chunk_preview_analysis_items(
    chunk_items: list[ChunkPreviewItem], *, strategy: str
) -> tuple[list[ChunkPreviewItem], Literal["all", "child"]]:
    analysis = list(chunk_items or [])
    if strategy != "parent_child":
        return analysis, "all"

    filtered = [chunk for chunk in analysis if chunk.metadata.get("chunk_role") != "parent"]
    return (filtered, "child") if filtered else (analysis, "all")


def _collect_chunk_gap_overlap_signals(
    analysis: list[ChunkPreviewItem], *, strict_no_overlap: bool
) -> tuple[set[int], set[int], dict[int, int], dict[int, int]]:
    gap_indices: set[int] = set()
    overlap_indices: set[int] = set()
    gap_before_by_index: dict[int, int] = {}
    overlap_prev_by_index: dict[int, int] = {}
    covered_end = 0

    for chunk in sorted(analysis, key=_chunk_preview_item_key):
        idx = chunk.index
        if idx < 0:
            continue
        start = max(0, chunk.start_index)
        end = max(start, chunk.end_index)

        if start > covered_end:
            gap = start - covered_end
            gap_indices.add(idx)
            gap_before_by_index[idx] = gap
        elif start < covered_end:
            overlap = covered_end - start
            chunk_len = max(1, end - start)
            overlap_prev_by_index[idx] = overlap
            if strict_no_overlap or (overlap / chunk_len) >= 0.6 or overlap >= 800:
                overlap_indices.add(idx)

        covered_end = max(covered_end, end)

    return gap_indices, overlap_indices, gap_before_by_index, overlap_prev_by_index


def _chunk_preview_length_for_short_signal(chunk: ChunkPreviewItem, *, unit: Literal["chars", "tokens"]) -> int:
    if unit == "tokens":
        return chunk.tokens_est or 0
    return chunk.length


def _collect_short_chunk_indices(chunk_items: list[ChunkPreviewItem], *, unit: Literal["chars", "tokens"]) -> set[int]:
    threshold = 40 if unit == "tokens" else 120
    out: set[int] = set()
    for chunk in chunk_items or []:
        idx = chunk.index
        length = _chunk_preview_length_for_short_signal(chunk, unit=unit)
        if idx >= 0 and 0 < length < threshold:
            out.add(idx)
    return out


def _collect_duplicate_chunk_indices(chunk_items: list[ChunkPreviewItem]) -> set[int]:
    duplicate_indices: set[int] = set()
    seen: dict[str, int] = {}
    for chunk in chunk_items or []:
        idx = chunk.index
        if idx < 0:
            continue
        trimmed = chunk.content.strip()
        if not trimmed:
            continue
        digest = hashlib.blake2b(trimmed.encode("utf-8"), digest_size=16).hexdigest()
        prev = seen.get(digest)
        if prev is None:
            seen[digest] = idx
            continue
        duplicate_indices.update({prev, idx})
    return duplicate_indices


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
    strict_no_overlap = strategy == "separator"
    analysis, basis = _chunk_preview_analysis_items(chunk_items, strategy=strategy)
    gap_indices, overlap_indices, gap_before_by_index, overlap_prev_by_index = _collect_chunk_gap_overlap_signals(
        analysis,
        strict_no_overlap=strict_no_overlap,
    )
    short_indices = _collect_short_chunk_indices(chunk_items, unit=unit)
    duplicate_indices = _collect_duplicate_chunk_indices(chunk_items)

    return ChunkPreviewReviewSignals(
        basis=basis,
        short_indices=sorted(short_indices),
        duplicate_indices=sorted(duplicate_indices),
        gap_indices=sorted(gap_indices),
        overlap_indices=sorted(overlap_indices),
        gap_before_by_index=gap_before_by_index,
        overlap_prev_by_index=overlap_prev_by_index,
    )


def _chunk_preview_stats_dict(stats: ChunkPreviewStats) -> dict[str, float | int]:
    return {
        "count": stats.count,
        "short_count": stats.short_count,
        "duplicate_count": stats.duplicate_count,
        "covered_chars": stats.covered_chars,
        "coverage_ratio": stats.coverage_ratio,
        "overlap_waste_ratio": stats.overlap_waste_ratio,
        "gap_count": stats.gap_count,
    }


def _chunk_preview_quality_reason(raw: object) -> ChunkPreviewQualityReason | None:
    if not isinstance(raw, dict):
        return None
    try:
        return ChunkPreviewQualityReason(
            code=raw["code"][:80],
            severity=str(raw.get("severity") or "info"),  # type: ignore[arg-type]
            message=raw["message"][:200],
            meta=dict(raw.get("meta") or {}),
        )
    except Exception:
        return None


def _chunk_preview_quality_reasons(gate_raw: object) -> list[ChunkPreviewQualityReason]:
    raw_items = gate_raw.get("reason_items") if isinstance(gate_raw, dict) else []
    out: list[ChunkPreviewQualityReason] = []
    for raw in raw_items or []:
        item = _chunk_preview_quality_reason(raw)
        if item is not None:
            out.append(item)
    return out


def _chunk_preview_recommendation_patch(raw: object) -> ChunkPreviewRecommendationPatch | None:
    if not isinstance(raw, dict):
        return None
    try:
        return ChunkPreviewRecommendationPatch(
            id=raw["id"][:80],
            title=raw["title"][:120],
            description=raw["description"][:400],
            target=str(raw.get("target") or "preview"),  # type: ignore[arg-type]
            patch=dict(raw.get("patch") or {}),
        )
    except Exception:
        return None


def _chunk_preview_recommendation_patches(patches_raw: object) -> list[ChunkPreviewRecommendationPatch]:
    out: list[ChunkPreviewRecommendationPatch] = []
    for raw in patches_raw or []:
        patch = _chunk_preview_recommendation_patch(raw)
        if patch is not None:
            out.append(patch)
    return out


def _chunk_preview_legacy_reasons(gate_raw: object) -> list[str]:
    reasons = gate_raw.get("reasons") if isinstance(gate_raw, dict) else []
    return [str(reason) for reason in reasons] if isinstance(reasons, list) else []


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

    gate_raw, recs, patches_raw = compute_chunk_quality_gate(
        stats=_chunk_preview_stats_dict(stats),
        total_chunks=total_chunks,
        total_characters=total_characters,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        original_text_included=original_text_included,
        original_text_truncated=original_text_truncated,
        original_text_max_chars=original_text_max_chars,
    )

    grade = str(gate_raw.get("grade") if isinstance(gate_raw, dict) else "pass") or "pass"

    return (
        ChunkPreviewQualityGate(
            grade=grade,
            reasons=_chunk_preview_legacy_reasons(gate_raw)[:10],
            reason_items=_chunk_preview_quality_reasons(gate_raw)[:10],
        ),
        list(recs or [])[:10],
        _chunk_preview_recommendation_patches(patches_raw)[:10],
    )
