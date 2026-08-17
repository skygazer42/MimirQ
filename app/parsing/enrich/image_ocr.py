"""
Local OCR enrichment for inline markdown images.

Design constraints:
- local only; no network calls
- best-effort and deterministic
- only reads files under the provided origin path
"""

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


def _build_image_ocr_audit(
    *,
    applied: bool,
    ocr_blocks_added: int,
    images_attempted: int,
    images_succeeded: int,
    elapsed_ms: int = 0,
    error: str | None = None,
) -> ImageOcrAudit:
    return ImageOcrAudit(
        applied=applied,
        ocr_blocks_added=int(ocr_blocks_added),
        images_attempted=int(images_attempted),
        images_succeeded=int(images_succeeded),
        elapsed_ms=int(elapsed_ms),
        backend="local_ocr",
        error=error,
    )


def _next_non_empty_line(lines: list[str], start: int, *, limit: int = 4) -> str:
    for index in range(start + 1, min(len(lines), start + limit)):
        candidate = (lines[index] or "").strip()
        if candidate:
            return candidate
    return ""


def _iter_line_images(line: str) -> list[tuple[str, str]]:
    return _extract_md_images(line) + _extract_html_imgs(line)


def _ocr_text_for_image(
    *,
    src: str,
    origin_path: Path,
    max_image_bytes: int,
    max_ocr_chars: int,
) -> tuple[str | None, int, int]:
    image_bytes, _reason = _safe_read_local_image_bytes(
        src=src,
        origin_path=origin_path,
        max_bytes=int(max_image_bytes or 0),
    )
    if image_bytes is None:
        return None, 0, 0

    try:
        image = PILImage.open(BytesIO(image_bytes))
    except Exception:
        get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
        return None, 1, 0

    try:
        text = str(ocr_image(image, _max_chars=int(max_ocr_chars or 0)) or "").strip()
    finally:
        try:
            image.close()
        except Exception as exc:
            logger.debug("Ignoring local image OCR close failure: %s", exc)

    if not text:
        return None, 1, 0
    return text, 1, 1


def _append_line_ocr_blocks(
    *,
    images: list[tuple[str, str]],
    out_lines: list[str],
    origin_path: Path,
    max_image_bytes: int,
    max_ocr_chars: int,
    remaining: int,
) -> tuple[int, int, int]:
    ocr_blocks_added = 0
    images_attempted = 0
    images_succeeded = 0

    for _alt, src in images:
        if ocr_blocks_added >= remaining:
            break
        text, attempted, succeeded = _ocr_text_for_image(
            src=src,
            origin_path=origin_path,
            max_image_bytes=max_image_bytes,
            max_ocr_chars=max_ocr_chars,
        )
        images_attempted += attempted
        images_succeeded += succeeded
        if not text:
            continue
        ocr_blocks_added += 1
        out_lines.append("Image OCR:")
        out_lines.append(text)

    return ocr_blocks_added, images_attempted, images_succeeded


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
        return (
            "",
            0,
            _build_image_ocr_audit(
                applied=False,
                ocr_blocks_added=0,
                images_attempted=0,
                images_succeeded=0,
            ),
        )

    max_images_i = max(0, int(max_images or 0))
    if max_images_i <= 0:
        return (
            raw,
            0,
            _build_image_ocr_audit(
                applied=False,
                ocr_blocks_added=0,
                images_attempted=0,
                images_succeeded=0,
                error="max_images<=0",
            ),
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

        if _next_non_empty_line(lines, index).lower().startswith("image ocr:"):
            continue

        images = _iter_line_images(line)
        if not images:
            continue

        added, attempted, succeeded = _append_line_ocr_blocks(
            images=images,
            out_lines=out_lines,
            origin_path=origin_path,
            max_image_bytes=max_image_bytes,
            max_ocr_chars=max_ocr_chars,
            remaining=max_images_i - ocr_blocks_added,
        )
        ocr_blocks_added += added
        images_attempted += attempted
        images_succeeded += succeeded

    elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
    return (
        "\n".join(out_lines).rstrip() + "\n",
        int(ocr_blocks_added),
        _build_image_ocr_audit(
            applied=True,
            ocr_blocks_added=ocr_blocks_added,
            images_attempted=images_attempted,
            images_succeeded=images_succeeded,
            elapsed_ms=elapsed_ms,
        ),
    )


__all__ = ["ImageOcrAudit", "add_image_ocr_blocks"]
