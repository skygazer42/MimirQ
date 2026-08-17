"""
Orientation helpers for preprocessing.

This implementation is best-effort and lightweight:
- Images: EXIF transpose (no model).
- PDFs: normalize page rotation metadata when a dominant rotation is detected.
"""


import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from app.rag.core.logging import get_logger

logger = get_logger(__name__)


def _elapsed_ms(started_at: float) -> int:
    return int(round((time.perf_counter() - started_at) * 1000))


def _sample_pdf_rotations(*, doc, sample_pages: int) -> tuple[int, list[int]]:  # noqa: ANN001
    page_count = int(doc.page_count)
    sample_count = max(1, min(int(sample_pages or 0) or 1, page_count))
    rotations: list[int] = []
    for index in range(sample_count):
        page = doc.load_page(index)
        rotations.append(int(getattr(page, "rotation", 0) or 0) % 360)
    return sample_count, rotations


def _count_rotations(rotations: list[int]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for rotation in rotations:
        counts[int(rotation)] = counts.get(int(rotation), 0) + 1
    return counts


def _normalize_pdf_pages(*, doc, page_count: int) -> None:  # noqa: ANN001
    for index in range(page_count):
        page = doc.load_page(index)
        try:
            page.set_rotation(0)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue


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
        meta["elapsed_ms"] = _elapsed_ms(t0)
        return False, f"pymupdf_missing:{exc.__class__.__name__}", meta

    doc = None
    try:
        doc = fitz.open(str(input_path))
        page_count = int(doc.page_count)
        sample_count, rotations = _sample_pdf_rotations(doc=doc, sample_pages=sample_pages)
        counts = _count_rotations(rotations)
        meta["rotation_counts"] = {str(k): int(v) for k, v in sorted(counts.items(), key=lambda kv: kv[0])}

        # Only normalize when all sampled pages share the same non-zero rotation.
        mode_rot = max(counts.items(), key=lambda kv: kv[1])[0] if counts else 0
        meta["rotation_mode"] = int(mode_rot)
        if mode_rot == 0:
            meta["elapsed_ms"] = _elapsed_ms(t0)
            return False, "already_upright", meta
        if counts.get(int(mode_rot), 0) != sample_count:
            meta["elapsed_ms"] = _elapsed_ms(t0)
            return False, "mixed_rotation_skipped", meta

        _normalize_pdf_pages(doc=doc, page_count=page_count)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(output_path), garbage=4, deflate=True)
        meta["elapsed_ms"] = _elapsed_ms(t0)
        return True, f"normalized_rotation:{mode_rot}->0", meta
    except Exception as exc:  # noqa: BLE001
        meta["elapsed_ms"] = _elapsed_ms(t0)
        return False, f"normalize_failed:{exc.__class__.__name__}", meta
    finally:
        try:
            if doc is not None:
                doc.close()
        except Exception as exc:
            logger.debug("Ignoring PDF rotation document close failure: %s", exc)


__all__ = ["fix_exif_orientation", "normalize_pdf_rotation"]
