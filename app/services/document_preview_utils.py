from __future__ import annotations

import contextlib
import hashlib
import math
import re
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse
from uuid import UUID

from langchain_core.documents import Document

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

logger = get_logger("documents.preview_utils")

UUID_PATTERN = r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
PREVIEW_IMAGE_REF_RE = re.compile(rf"(?:https?://[^\s)\"']+)?/api/v1/documents/image/({UUID_PATTERN})")
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
REMOTE_PREVIEW_IMAGE_SCHEMES = {"http", "https", "data", "blob"}


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


def _preview_page_text_by_index(documents: list[Document]) -> dict[int, str]:
    page_text: dict[int, str] = {}
    for i, doc in enumerate(documents):
        meta = dict(getattr(doc, "metadata", None) or {})
        try:
            page_index = int(meta.get("page_index") or (i + 1))
        except Exception:
            page_index = i + 1
        page_text[page_index] = str(doc.page_content or "")
    return page_text


def _preview_page_index_of(chunk: Document) -> int | None:
    meta = getattr(chunk, "metadata", None) or {}
    raw = meta.get("page_index")
    try:
        return int(raw) if raw is not None else None
    except Exception:
        return None


def _preview_local_range(meta: dict[str, Any]) -> tuple[int, int] | None:
    try:
        start = int(meta.get("start_char")) if meta.get("start_char") is not None else None
        end = int(meta.get("end_char")) if meta.get("end_char") is not None else None
    except Exception:
        return None
    if start is None or end is None or end < start:
        return None
    return start, end


def _preview_chunk_mergeable(chunk: Document, *, page_index: int | None, page_text: dict[int, str]) -> bool:
    meta = dict(getattr(chunk, "metadata", None) or {})
    return (
        page_index is not None
        and page_index in page_text
        and not _preview_chunk_has_asset(meta, chunk.page_content or "")
        and not (meta.get("chunk_role") or meta.get("parent_id"))
        and _preview_local_range(meta) is not None
    )


def _merge_preview_chunks_on_page(a: Document, b: Document, *, page_index: int, page_text: dict[int, str]) -> Document | None:
    text = page_text.get(page_index)
    if text is None:
        return None

    meta_a = dict(getattr(a, "metadata", None) or {})
    meta_b = dict(getattr(b, "metadata", None) or {})
    range_a = _preview_local_range(meta_a)
    range_b = _preview_local_range(meta_b)
    if range_a is None or range_b is None:
        return None

    start_local = max(0, min(min(range_a[0], range_b[0]), len(text)))
    end_local = max(start_local, min(max(range_a[1], range_b[1]), len(text)))
    meta_a["start_char"] = start_local
    meta_a["end_char"] = end_local
    meta_a["merged_small_chunks"] = int(meta_a.get("merged_small_chunks") or 0) + 1
    return Document(page_content=text[start_local:end_local], metadata=meta_a, id=getattr(a, "id", None))


def _merge_preview_pair_or_append(out: list[Document], first: Document, second: Document, *, page_index: int, page_text: dict[int, str]) -> None:
    merged = _merge_preview_chunks_on_page(first, second, page_index=page_index, page_text=page_text)
    if merged is None:
        out.extend([first, second])
        return
    out.append(merged)


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

    page_text = _preview_page_text_by_index(documents)
    out: list[Document] = []
    pending: Document | None = None
    pending_page: int | None = None

    for chunk in chunks:
        page_index = _preview_page_index_of(chunk)
        if pending is not None and page_index != pending_page:
            out.append(pending)
            pending = None
            pending_page = None

        if not _preview_chunk_mergeable(chunk, page_index=page_index, page_text=page_text):
            if pending is not None:
                out.append(pending)
                pending = None
                pending_page = None
            out.append(chunk)
            continue

        content_len = len((chunk.page_content or "").strip())

        if pending is not None:
            if page_index is not None:
                _merge_preview_pair_or_append(out, pending, chunk, page_index=page_index, page_text=page_text)
            else:
                out.extend([pending, chunk])
            pending = None
            pending_page = None
            continue

        if content_len >= min_chars:
            out.append(chunk)
            continue

        if out:
            prev = out[-1]
            prev_page = _preview_page_index_of(prev)
            if prev_page == page_index and _preview_chunk_mergeable(prev, page_index=prev_page, page_text=page_text):
                merged = (
                    _merge_preview_chunks_on_page(prev, chunk, page_index=page_index, page_text=page_text)
                    if page_index is not None
                    else None
                )
                if merged is not None:
                    out[-1] = merged
                    continue

        pending = chunk
        pending_page = page_index

    if pending is not None:
        out.append(pending)

    return out


def _preview_images_dir(tenant_id: UUID) -> Path:
    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir


def _load_preview_pillow_image_class() -> tuple[Any | None, bool]:
    try:
        from PIL import Image as pil_image  # type: ignore
    except ImportError:
        return None, False
    return pil_image, True


def _drop_preview_image_objects(documents: list) -> list:
    for doc in documents:
        meta = getattr(doc, "metadata", None) or {}
        if isinstance(meta, dict) and "image" in meta:
            meta.pop("image", None)
            doc.metadata = meta
    return documents


def _save_extracted_preview_image(image_obj: object, out_path: Path, pil_image: Any) -> None:
    img = pil_image.open(BytesIO(bytes(image_obj))) if isinstance(image_obj, (bytes, bytearray)) else image_obj
    with contextlib.suppress(Exception):
        if getattr(img, "mode", None) != "RGB":
            img = img.convert("RGB")
    img.save(out_path, format="JPEG", quality=85, optimize=True)


def _close_preview_image_object(image_obj: object) -> None:
    if isinstance(image_obj, (bytes, bytearray)) or not hasattr(image_obj, "close"):
        return
    with contextlib.suppress(Exception):
        image_obj.close()


def _materialize_extracted_preview_image_doc(doc: Any, *, images_dir: Path, pil_image: Any) -> None:
    meta = getattr(doc, "metadata", None) or {}
    if not isinstance(meta, dict):
        return

    image_obj = meta.get("image")
    if image_obj is None:
        return

    doc_type = str(meta.get("doc_type_kwd") or "").lower()
    if doc_type != "image":
        meta.pop("image", None)
        doc.metadata = meta
        return

    preview_id = uuid.uuid4().hex
    out_path = images_dir / f"{preview_id}.jpg"
    url = f"/api/v1/documents/image/{preview_id}"
    try:
        _save_extracted_preview_image(image_obj, out_path, pil_image)
    except Exception as exc:
        logger.warning("Failed to persist preview image: %s", str(exc)[:200])
    finally:
        meta.pop("image", None)
        doc.metadata = meta
        _close_preview_image_object(image_obj)

    caption = (getattr(doc, "page_content", "") or "").strip()
    img_md = f"![image]({url})"
    doc.page_content = f"{img_md}\n\n{caption}" if caption else img_md
    meta["preview_image_id"] = preview_id
    meta["preview_image_url"] = url
    doc.metadata = meta


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

    images_dir = _preview_images_dir(tenant_id)
    pil_image, pillow_ok = _load_preview_pillow_image_class()
    if not pillow_ok:
        logger.warning("Pillow not available; dropping preview image objects (hint: pip install Pillow)")
        return _drop_preview_image_objects(documents)

    for doc in documents:
        _materialize_extracted_preview_image_doc(doc, images_dir=images_dir, pil_image=pil_image)

    return documents


def _preview_local_image_limits() -> tuple[int, int]:
    max_inline_images = max(0, int(getattr(settings, "MAX_INLINE_IMAGES", 0) or 0))
    max_image_bytes = int(getattr(settings, "MAX_INLINE_IMAGE_BYTES", 10_000_000) or 10_000_000)
    return max_inline_images, max(1_000_000, max_image_bytes)


def _preview_content_image_refs(content: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pattern in (PREVIEW_MD_IMAGE_REF_RE, PREVIEW_HTML_IMAGE_REF_RE):
        for match in pattern.finditer(content):
            ref = (match.group(1) or "").strip()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            found.append(ref)
    return found


def _preview_doc_asset_base_dir(doc: Any) -> Path | None:
    meta = getattr(doc, "metadata", None) or {}
    if not isinstance(meta, dict):
        return None

    base_dir_raw = meta.get("asset_base_dir")
    if not isinstance(base_dir_raw, str) or not base_dir_raw.strip():
        return None

    base_dir = Path(base_dir_raw.strip()).resolve(strict=False)
    if not base_dir.exists() or not base_dir.is_dir():
        return None
    return base_dir.resolve(strict=False)


def _preview_local_ref_skippable(ref: str) -> bool:
    parsed_ref = urlparse(ref)
    scheme = (parsed_ref.scheme or "").lower().strip()
    if scheme in REMOTE_PREVIEW_IMAGE_SCHEMES or (parsed_ref.netloc or "").strip():
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
            path_obj = path_obj.resolve(strict=False) if path_obj.is_absolute() else (base_dir_resolved / path_obj).resolve(strict=False)
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


def _convert_preview_local_image_bytes(raw_bytes: bytes, *, ext: str, pil_image: Any | None, pillow_ok: bool) -> tuple[bytes, str] | None:
    if ext in LOCAL_PREVIEW_IMAGE_EXTS:
        return raw_bytes, ext
    if not pillow_ok or pil_image is None:
        return None
    try:
        img = pil_image.open(BytesIO(raw_bytes))
        if getattr(img, "mode", None) != "RGB":
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
) -> str | None:
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
        except Exception as exc:
            logger.warning("Failed to persist preview local image: %s", str(exc)[:200])
            return None
        digest_cache[digest] = (preview_id, out_ext)
    return f"/api/v1/documents/image/{preview_id}"


def _preview_local_image_replacements(
    refs: list[str],
    *,
    base_dir_resolved: Path,
    max_image_bytes: int,
    pil_image: Any | None,
    pillow_ok: bool,
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
        converted = _convert_preview_local_image_bytes(image[0], ext=image[1], pil_image=pil_image, pillow_ok=pillow_ok)
        if converted is None:
            continue
        url = _preview_cached_or_persisted_image_url(converted[0], out_ext=converted[1], digest_cache=digest_cache, images_dir=images_dir)
        if url:
            replacements[ref] = url
    return replacements


def _replace_preview_image_ref(match: re.Match, replacements: dict[str, str]) -> str:
    raw = match.group(1) or ""
    new = replacements.get(raw.strip())
    return match.group(0).replace(raw, new, 1) if new else match.group(0)


def _rewrite_preview_local_image_refs(content: str, replacements: dict[str, str]) -> str:
    content = PREVIEW_MD_IMAGE_REF_RE.sub(lambda m: _replace_preview_image_ref(m, replacements), content)
    return PREVIEW_HTML_IMAGE_REF_RE.sub(lambda m: _replace_preview_image_ref(m, replacements), content)


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

    images_dir = _preview_images_dir(tenant_id)
    max_inline_images, max_image_bytes = _preview_local_image_limits()
    digest_cache: dict[str, tuple[str, str]] = {}
    pil_image, pillow_ok = _load_preview_pillow_image_class()

    for doc in documents:
        content = getattr(doc, "page_content", "") or ""
        if not isinstance(content, str) or not content:
            continue

        lowered = content.lower()
        if "![" not in lowered and "<img" not in lowered:
            continue

        base_dir_resolved = _preview_doc_asset_base_dir(doc)
        if base_dir_resolved is None:
            continue

        found = _preview_content_image_refs(content)
        if max_inline_images:
            found = found[:max_inline_images]
        if not found:
            continue

        replacements = _preview_local_image_replacements(
            found,
            base_dir_resolved=base_dir_resolved,
            max_image_bytes=max_image_bytes,
            pil_image=pil_image,
            pillow_ok=pillow_ok,
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


def _safe_nonnegative_int_values(values: list[int]) -> list[int]:
    out: list[int] = []
    for value in values or []:
        try:
            number = int(value)
        except Exception:
            continue
        out.append(max(0, number))
    return out


def _chunk_histogram_step(max_value: int, *, unit: Literal["chars", "tokens"], target_bins: int) -> int:
    bins = max(3, min(12, int(target_bins or 8)))
    base = 25 if unit == "tokens" else 50
    if max_value <= 0:
        return base
    step = int(math.ceil((max_value / bins) / base) * base)
    return max(base, step) if step > 0 else base


def _chunk_histogram_empty_bins(max_value: int, *, step: int) -> list[dict[str, object]]:
    bin_count = max(1, int(math.ceil((max_value + 1) / step))) if step > 0 else 1
    return [
        {"label": f"{int(i * step)}-{int((i + 1) * step)}", "min": int(i * step), "max": int((i + 1) * step), "count": 0}
        for i in range(bin_count)
    ]


def _increment_chunk_histogram_bins(bins: list[dict[str, object]], values: list[int], *, step: int) -> None:
    for value in values:
        idx = int(value // step) if step > 0 else 0
        idx = max(0, min(idx, len(bins) - 1))
        bins[idx]["count"] = int(bins[idx].get("count") or 0) + 1


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
    values = _safe_nonnegative_int_values(lengths)
    if not values:
        return []

    max_val = max(values)
    step = _chunk_histogram_step(max_val, unit=unit, target_bins=target_bins)
    bins = _chunk_histogram_empty_bins(max_val, step=step)
    _increment_chunk_histogram_bins(bins, values, step=step)
    return bins


def _chunk_preview_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except Exception:
        return default


def _chunk_preview_item_key(chunk: ChunkPreviewItem) -> tuple[int, int, int]:
    start = _chunk_preview_int(getattr(chunk, "start_index", 0))
    end = _chunk_preview_int(getattr(chunk, "end_index", start), default=start)
    index = _chunk_preview_int(getattr(chunk, "index", 0))
    return start, end, index


def _chunk_preview_analysis_items(
    chunk_items: list[ChunkPreviewItem], *, strategy: str
) -> tuple[list[ChunkPreviewItem], Literal["all", "child"]]:
    analysis = list(chunk_items or [])
    if str(strategy or "") != "parent_child":
        return analysis, "all"

    filtered = [
        chunk
        for chunk in analysis
        if not isinstance(getattr(chunk, "metadata", None), dict) or getattr(chunk, "metadata", {}).get("chunk_role") != "parent"
    ]
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
        idx = _chunk_preview_int(getattr(chunk, "index", None), default=-1)
        if idx < 0:
            continue
        start = max(0, _chunk_preview_int(getattr(chunk, "start_index", 0)))
        end = max(start, _chunk_preview_int(getattr(chunk, "end_index", start), default=start))

        if start > covered_end:
            gap = start - covered_end
            gap_indices.add(idx)
            gap_before_by_index[idx] = int(gap)
        elif start < covered_end:
            overlap = covered_end - start
            chunk_len = max(1, end - start)
            overlap_prev_by_index[idx] = int(overlap)
            if strict_no_overlap or (overlap / chunk_len) >= 0.6 or overlap >= 800:
                overlap_indices.add(idx)

        covered_end = max(covered_end, end)

    return gap_indices, overlap_indices, gap_before_by_index, overlap_prev_by_index


def _chunk_preview_length_for_short_signal(chunk: ChunkPreviewItem, *, unit: Literal["chars", "tokens"]) -> int:
    if unit == "tokens":
        return _chunk_preview_int(getattr(chunk, "tokens_est", None))
    return _chunk_preview_int(getattr(chunk, "length", 0))


def _collect_short_chunk_indices(chunk_items: list[ChunkPreviewItem], *, unit: Literal["chars", "tokens"]) -> set[int]:
    threshold = 40 if unit == "tokens" else 120
    out: set[int] = set()
    for chunk in chunk_items or []:
        idx = _chunk_preview_int(getattr(chunk, "index", None), default=-1)
        length = _chunk_preview_length_for_short_signal(chunk, unit=unit)
        if idx >= 0 and 0 < length < threshold:
            out.add(idx)
    return out


def _collect_duplicate_chunk_indices(chunk_items: list[ChunkPreviewItem]) -> set[int]:
    duplicate_indices: set[int] = set()
    seen: dict[str, int] = {}
    for chunk in chunk_items or []:
        idx = _chunk_preview_int(getattr(chunk, "index", None), default=-1)
        if idx < 0:
            continue
        trimmed = str(getattr(chunk, "content", "") or "").strip()
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
    strict_no_overlap = str(strategy or "") == "separator"
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
        "count": int(getattr(stats, "count", 0) or 0),
        "short_count": int(getattr(stats, "short_count", 0) or 0),
        "duplicate_count": int(getattr(stats, "duplicate_count", 0) or 0),
        "covered_chars": int(getattr(stats, "covered_chars", 0) or 0),
        "coverage_ratio": float(getattr(stats, "coverage_ratio", 0.0) or 0.0),
        "overlap_waste_ratio": float(getattr(stats, "overlap_waste_ratio", 0.0) or 0.0),
        "gap_count": int(getattr(stats, "gap_count", 0) or 0),
    }


def _chunk_preview_quality_reason(raw: object) -> ChunkPreviewQualityReason | None:
    if not isinstance(raw, dict):
        return None
    try:
        return ChunkPreviewQualityReason(
            code=str(raw.get("code") or "")[:80],
            severity=str(raw.get("severity") or "info"),  # type: ignore[arg-type]
            message=str(raw.get("message") or "")[:200],
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
            id=str(raw.get("id") or "")[:80],
            title=str(raw.get("title") or "")[:120],
            description=str(raw.get("description") or "")[:400],
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
        total_chunks=int(total_chunks or 0),
        total_characters=int(total_characters or 0),
        chunk_size=int(chunk_size or 0),
        chunk_overlap=int(chunk_overlap or 0),
        original_text_included=bool(original_text_included),
        original_text_truncated=bool(original_text_truncated),
        original_text_max_chars=int(original_text_max_chars or 0),
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
