"""
Local OCR enrichment for inline markdown images.

Design constraints:
- local only; no network calls
- best-effort and deterministic
- only reads files under the provided origin path
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage

from app.parsing.enrich.image_code import (
    _FENCE_RE,
    _extract_html_imgs,
    _extract_md_images,
    _safe_read_local_image_bytes,
)
from app.parsing.enrich.image_understanding import ocr_image
from app.rag.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ImageOcrAudit:
    applied: bool
    ocr_blocks_added: int
    images_attempted: int
    images_succeeded: int
    elapsed_ms: int
    backend: str
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "applied": bool(self.applied),
            "ocr_blocks_added": int(self.ocr_blocks_added),
            "images_attempted": int(self.images_attempted),
            "images_succeeded": int(self.images_succeeded),
            "elapsed_ms": int(self.elapsed_ms),
            "backend": str(self.backend or ""),
            "error": (str(self.error)[:200] if self.error else None),
        }


def add_image_ocr_blocks(
    markdown: str,
    *,
    origin_path: Path,
    max_images: int = 12,
    max_image_bytes: int = 5_000_000,
    max_ocr_chars: int = 2000,
) -> tuple[str, int, ImageOcrAudit]:
    raw = str(markdown or "")
    if not raw:
        return "", 0, ImageOcrAudit(
            applied=False,
            ocr_blocks_added=0,
            images_attempted=0,
            images_succeeded=0,
            elapsed_ms=0,
            backend="local_ocr",
            error=None,
        )

    max_images_i = max(0, int(max_images or 0))
    if max_images_i <= 0:
        return raw, 0, ImageOcrAudit(
            applied=False,
            ocr_blocks_added=0,
            images_attempted=0,
            images_succeeded=0,
            elapsed_ms=0,
            backend="local_ocr",
            error="max_images<=0",
        )

    t0 = time.perf_counter()
    out_lines: list[str] = []
    in_fence = False
    ocr_blocks_added = 0
    images_attempted = 0
    images_succeeded = 0

    lines = raw.splitlines()
    for index, line in enumerate(lines):
        if _FENCE_RE.match(line or ""):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(line)
            continue

        out_lines.append(line)
        if ocr_blocks_added >= max_images_i:
            continue

        next_non_empty = ""
        for cursor in range(index + 1, min(len(lines), index + 4)):
            candidate = (lines[cursor] or "").strip()
            if candidate:
                next_non_empty = candidate
                break
        if next_non_empty.lower().startswith("image ocr:"):
            continue

        images = _extract_md_images(line) + _extract_html_imgs(line)
        if not images:
            continue

        for _alt, src in images:
            if ocr_blocks_added >= max_images_i:
                break
            image_bytes, _reason = _safe_read_local_image_bytes(
                src=src,
                origin_path=origin_path,
                max_bytes=int(max_image_bytes or 0),
            )
            if image_bytes is None:
                continue
            images_attempted += 1
            try:
                image = PILImage.open(BytesIO(image_bytes))
            except Exception:
                get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
            try:
                text = str(ocr_image(image, _max_chars=int(max_ocr_chars or 0)) or "").strip()
            finally:
                try:
                    image.close()
                except Exception as exc:
                    logger.debug("Ignoring local image OCR close failure: %s", exc)
            if not text:
                continue
            images_succeeded += 1
            ocr_blocks_added += 1
            out_lines.append("Image OCR:")
            out_lines.append(text)

    elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
    return (
        "\n".join(out_lines).rstrip() + "\n",
        int(ocr_blocks_added),
        ImageOcrAudit(
            applied=True,
            ocr_blocks_added=int(ocr_blocks_added),
            images_attempted=int(images_attempted),
            images_succeeded=int(images_succeeded),
            elapsed_ms=elapsed_ms,
            backend="local_ocr",
            error=None,
        ),
    )


__all__ = ["ImageOcrAudit", "add_image_ocr_blocks"]
