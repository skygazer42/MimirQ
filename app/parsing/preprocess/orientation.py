"""
Orientation helpers for preprocessing.

docs/plans/2026-03-19-model-based-deskew-watermark-removal.md (Module 3):
- Page orientation detection (0/90/180/270)

This implementation is best-effort and lightweight:
- Images: EXIF transpose (no model).
- PDFs: normalize page rotation metadata when a dominant rotation is detected.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from app.rag.core.logging import get_logger

logger = get_logger(__name__)


def fix_exif_orientation(*, input_path: Path, output_path: Path) -> tuple[bool, str, dict[str, Any]]:
    """
    Returns (changed, note, meta).
    """
    meta: dict[str, Any] = {}
    try:
        with Image.open(input_path) as img:
            try:
                orientation = int(img.getexif().get(274) or 1)
            except Exception:
                orientation = 1
            meta["exif_orientation"] = int(orientation)
            if orientation == 1:
                return False, "no_exif_rotation", meta

            fixed = ImageOps.exif_transpose(img)
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
    meta: dict[str, Any] = {"sample_pages": int(sample_pages or 0)}
    t0 = time.perf_counter()
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # noqa: BLE001
        meta["elapsed_ms"] = int(round((time.perf_counter() - t0) * 1000))
        return False, f"pymupdf_missing:{exc.__class__.__name__}", meta

    doc = None
    try:
        doc = fitz.open(str(input_path))
        n = int(doc.page_count)
        k = max(1, min(int(sample_pages or 0) or 1, n))
        rotations: list[int] = []
        for i in range(k):
            page = doc.load_page(i)
            rotations.append(int(getattr(page, "rotation", 0) or 0) % 360)

        counts: dict[int, int] = {}
        for r in rotations:
            counts[int(r)] = counts.get(int(r), 0) + 1
        meta["rotation_counts"] = {str(k): int(v) for k, v in sorted(counts.items(), key=lambda kv: kv[0])}

        # Only normalize when all sampled pages share the same non-zero rotation.
        mode_rot = max(counts.items(), key=lambda kv: kv[1])[0] if counts else 0
        meta["rotation_mode"] = int(mode_rot)
        if mode_rot == 0:
            meta["elapsed_ms"] = int(round((time.perf_counter() - t0) * 1000))
            return False, "already_upright", meta
        if counts.get(int(mode_rot), 0) != k:
            meta["elapsed_ms"] = int(round((time.perf_counter() - t0) * 1000))
            return False, "mixed_rotation_skipped", meta

        for i in range(n):
            page = doc.load_page(i)
            try:
                page.set_rotation(0)
            except Exception:
                continue

        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(output_path), garbage=4, deflate=True)
        meta["elapsed_ms"] = int(round((time.perf_counter() - t0) * 1000))
        return True, f"normalized_rotation:{mode_rot}->0", meta
    except Exception as exc:  # noqa: BLE001
        meta["elapsed_ms"] = int(round((time.perf_counter() - t0) * 1000))
        return False, f"normalize_failed:{exc.__class__.__name__}", meta
    finally:
        try:
            if doc is not None:
                doc.close()
        except Exception as exc:
            logger.debug("Ignoring PDF rotation document close failure: %s", exc)


__all__ = ["fix_exif_orientation", "normalize_pdf_rotation"]
