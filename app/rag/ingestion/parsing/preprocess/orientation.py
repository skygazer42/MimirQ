"""
Orientation helpers for preprocessing.

This implementation is best-effort and lightweight:
- Images: EXIF transpose (no model).
- PDFs: normalize page rotation metadata when a dominant rotation is detected.
"""

from __future__ import annotations

import logging
import time
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageOps

if TYPE_CHECKING:
    import fitz

logger = logging.getLogger(__name__)


def _elapsed_ms(started_at: float) -> int:
    return int(round((time.perf_counter() - started_at) * 1000))


def _sample_pdf_rotations(*, doc: fitz.Document, sample_pages: int) -> tuple[int, list[int]]:
    page_count = doc.page_count
    sample_count = max(0, min(sample_pages, page_count))
    rotations: list[int] = []
    for index in range(sample_count):
        page = doc.load_page(index)
        rotations.append(page.rotation % 360)
    return sample_count, rotations


def _count_rotations(rotations: list[int]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for rotation in rotations:
        counts[rotation] = counts.get(rotation, 0) + 1
    return counts


def _normalize_pdf_pages(*, doc: fitz.Document, page_count: int, rotation: int) -> None:
    for index in range(page_count):
        page = doc.load_page(index)
        if page.rotation % 360 == rotation:
            page.set_rotation(0)


def fix_exif_orientation(*, input_path: Path, output_path: Path) -> tuple[bool, str, dict[str, Any]]:
    """
    Returns (changed, note, meta).
    """
    meta: dict[str, Any] = {}
    try:
        with closing(Image.open(input_path)) as img:
            raw_orientation = img.getexif().get(274)
            orientation = 1 if raw_orientation is None else int(raw_orientation)
            meta["exif_orientation"] = orientation
            if orientation == 1:
                return False, "no_exif_rotation", meta
            if orientation not in range(2, 9):
                return False, "unsupported_exif_orientation", meta

            with closing(ImageOps.exif_transpose(img)) as fixed:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                fixed.save(output_path)
            return True, f"exif_orientation={orientation}", meta
    except Exception as exc:  # noqa: BLE001
        return False, f"exif_failed:{exc.__class__.__name__}", meta


def normalize_pdf_rotation(
    *,
    input_path: Path,
    output_path: Path,
    sample_pages: int = 3,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Best-effort: normalize PDF page rotation metadata to 0 degrees.

    Returns (changed, note, meta).
    """
    meta: dict[str, Any] = {"sample_pages": sample_pages}
    t0 = time.perf_counter()
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # noqa: BLE001
        meta["elapsed_ms"] = _elapsed_ms(t0)
        return False, f"pymupdf_missing:{exc.__class__.__name__}", meta

    try:
        with fitz.open(str(input_path)) as doc:
            page_count = doc.page_count
            sample_count, rotations = _sample_pdf_rotations(doc=doc, sample_pages=sample_pages)
            if not rotations:
                meta["elapsed_ms"] = _elapsed_ms(t0)
                return False, "no_pages_to_sample", meta
            counts = _count_rotations(rotations)
            meta["rotation_counts"] = {str(k): v for k, v in sorted(counts.items(), key=lambda kv: kv[0])}

            # Only normalize when all sampled pages share the same non-zero rotation.
            mode_rot = max(counts.items(), key=lambda kv: kv[1])[0]
            meta["rotation_mode"] = mode_rot
            if mode_rot == 0:
                meta["elapsed_ms"] = _elapsed_ms(t0)
                return False, "already_upright", meta
            if counts[mode_rot] != sample_count:
                meta["elapsed_ms"] = _elapsed_ms(t0)
                return False, "mixed_rotation_skipped", meta

            _normalize_pdf_pages(doc=doc, page_count=page_count, rotation=mode_rot)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            doc.save(str(output_path), garbage=4, deflate=True)
            meta["elapsed_ms"] = _elapsed_ms(t0)
            return True, f"normalized_rotation:{mode_rot}->0", meta
    except Exception as exc:  # noqa: BLE001
        meta["elapsed_ms"] = _elapsed_ms(t0)
        return False, f"normalize_failed:{exc.__class__.__name__}", meta


__all__ = ["fix_exif_orientation", "normalize_pdf_rotation"]
