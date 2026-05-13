from __future__ import annotations

import contextlib
import hashlib
import math
import re
import uuid
from pathlib import Path
from typing import Any, Literal
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
DATA_IMAGE_PREFIX = "data:image"
IMAGE_FILE_EXT_JPEG = ".jpeg"
IMAGE_FILE_EXT_WEBP = ".webp"
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
