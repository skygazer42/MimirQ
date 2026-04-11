from __future__ import annotations

import base64
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image as PILImage

from app.core.config import settings

_GENERIC_IMAGE_TEXT_RE = re.compile(r"^(image|figure|photo|picture|diagram|chart)\b", re.IGNORECASE)
_PAGE_ONLY_RE = re.compile(r"^page\s+\d+\s*$", re.IGNORECASE)


def _clean_single_line(s: str, *, max_chars: int) -> str:
    s0 = re.sub(r"\s+", " ", str(s or "")).strip()
    if not s0:
        return ""
    if max_chars > 0 and len(s0) > max_chars:
        s0 = s0[: max_chars - 3].rstrip() + "..."
    return s0


def derive_image_caption(text: str, meta: dict[str, Any], *, max_chars: int = 200) -> str:
    """
    Derive a short, human-friendly caption for an image chunk.

    Conservative heuristics:
    - Prefer existing chunk text if it's not a generic placeholder.
    - Fallback to "Page {n} image" when page info exists.
    """
    raw = (text or "").strip()
    if raw and not _PAGE_ONLY_RE.match(raw) and not _GENERIC_IMAGE_TEXT_RE.match(raw):
        return _clean_single_line(raw, max_chars=max_chars)

    page = meta.get("page") or meta.get("page_number")
    try:
        page_i = int(page)
    except Exception:
        page_i = 0
    if page_i > 0:
        return f"Page {page_i} image"

    return "Image"


def _b64_to_bytes(s: str) -> bytes:
    s0 = (s or "").strip()
    if not s0:
        return b""
    if s0.startswith("data:"):
        parts = s0.split(",", 1)
        if len(parts) == 2:
            s0 = parts[1]
    return base64.b64decode(s0)


def _safe_read_image_path(raw_path: str, *, tenant_id: str) -> bytes:
    """
    Best-effort safe file read for parser-emitted image paths.

    Only allows reading paths under {UPLOAD_DIR}/{tenant_id}.
    """
    if not raw_path:
        return b""
    upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
    tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
    candidate = Path(str(raw_path).strip()).resolve(strict=False)
    candidate.relative_to(tenant_root)
    if not candidate.exists() or not candidate.is_file():
        return b""
    return candidate.read_bytes()


def load_image_for_ocr(meta: dict[str, Any], *, _tenant_id: str) -> tuple[PILImage.Image | None, bool]:
    """
    Load a PIL image from chunk metadata for OCR (best-effort).

    Returns:
        (image, should_close)
    """
    if not isinstance(meta, dict):
        return None, False
    if str(meta.get("doc_type_kwd") or "").lower() != "image":
        return None, False

    val = meta.get("image")
    if isinstance(val, PILImage.Image):
        return val, False
    if isinstance(val, (bytes, bytearray)):
        try:
            img = PILImage.open(BytesIO(bytes(val)))
            return img, True
        except Exception:
            return None, False
    if isinstance(val, str) and val.strip():
        try:
            img = PILImage.open(BytesIO(_b64_to_bytes(val)))
            return img, True
        except Exception:
            return None, False

    raw_path = meta.get("image_path")
    if isinstance(raw_path, str) and raw_path.strip():
        try:
            binary = _safe_read_image_path(raw_path, tenant_id=_tenant_id)
            if binary:
                img = PILImage.open(BytesIO(binary))
                return img, True
        except Exception:
            return None, False

    for key in ("image_base64", "img_base64", "img", "image_data"):
        s = meta.get(key)
        if isinstance(s, str) and s.strip():
            try:
                img = PILImage.open(BytesIO(_b64_to_bytes(s)))
                return img, True
            except Exception:
                return None, False

    return None, False


def ocr_image(image: PILImage.Image, *, _max_chars: int = 2000) -> str:
    """
    Run OCR on a PIL image (best-effort) and return text.

    Notes:
    - Uses the same RapidOCR wrapper as PDF quality validation (lazy init).
    - Returns "" on any failure.
    """
    max_chars_i = max(0, int(_max_chars or 0))
    if max_chars_i == 0:
        return ""

    try:
        from app.parsing.quality.ocr_validator import rapid_ocr_service

        text = rapid_ocr_service.ocr_image(image)
    except Exception:
        return ""

    text0 = (text or "").strip()
    if not text0:
        return ""
    if len(text0) > max_chars_i:
        text0 = text0[: max_chars_i - 3].rstrip() + "..."
    return text0


def decode_image_codes(image: PILImage.Image) -> dict[str, Any]:
    """
    Best-effort decode of QR/barcode content from an image.

    Returns a compact payload:
    - visual_kind: qr | barcode
    - text: first decoded value
    - values: all decoded values (deduplicated)
    """
    values: list[str] = []
    visual_kind = ""
    try:
        from pyzbar.pyzbar import decode  # type: ignore[import-untyped]

        items = decode(image)
        for item in items or []:
            raw_type = str(getattr(item, "type", "") or "").strip().upper()
            raw_data = getattr(item, "data", b"")
            try:
                text = raw_data.decode("utf-8", "ignore").strip()
            except Exception:
                text = ""
            if text and text not in values:
                values.append(text)
            if raw_type == "QRCODE":
                visual_kind = "qr"
            elif raw_type and not visual_kind:
                visual_kind = "barcode"
    except Exception:
        pass

    if not values:
        try:
            import cv2
            import numpy as np

            detector = cv2.QRCodeDetector()
            arr = np.array(image.convert("RGB"))
            for candidate in (arr, cv2.resize(arr, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)):
                text, _points, _straight = detector.detectAndDecode(candidate)
                text = str(text or "").strip()
                if text:
                    values.append(text)
                    visual_kind = "qr"
                    break
        except Exception:
            pass

    if not values:
        return {}
    return {
        "visual_kind": visual_kind or "barcode",
        "text": values[0],
        "values": values,
    }


def infer_visual_kind_from_pixels(image: PILImage.Image) -> str:
    """
    Best-effort local visual-kind inference from image pixels.

    Current supported kinds:
    - chart: multiple solid bar-like regions
    - diagram: multiple box-like regions connected by sparse lines
    """
    try:
        import cv2
        import numpy as np
    except Exception:
        return ""

    try:
        rgb = image.convert("RGB")
        arr = np.array(rgb)
    except Exception:
        return ""

    if arr.size == 0 or arr.ndim != 3:
        return ""

    height, width = arr.shape[:2]
    if height < 24 or width < 24:
        return ""

    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    mask = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)[1]
    ink_ratio = float(mask.mean() / 255.0)
    if ink_ratio <= 0.01:
        return ""

    min_component_area = max(32, int(width * height * 0.004))
    component_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

    solid_rects: list[tuple[int, int, int, int, int]] = []
    for index in range(1, int(component_count)):
        x, y, w, h, area = (int(value) for value in stats[index])
        if area < min_component_area or w <= 0 or h <= 0:
            continue
        fill_ratio = float(area / float(w * h))
        aspect_ratio = float(w / float(h))
        if fill_ratio >= 0.55 and 0.18 <= aspect_ratio <= 1.8 and h >= int(height * 0.12):
            solid_rects.append((x, y, w, h, area))

    if len(solid_rects) >= 3:
        solid_rects.sort(key=lambda item: item[0])
        heights = [item[3] for item in solid_rects]
        unique_heights = len({int(round(value / 4.0) * 4) for value in heights})
        if unique_heights >= 3 and max(heights) - min(heights) >= int(height * 0.12):
            return "chart"

    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    rectangular_regions = 0
    for contour in contours:
        x, y, w, h = (int(value) for value in cv2.boundingRect(contour))
        if w <= 0 or h <= 0:
            continue
        box_area = w * h
        if box_area < min_component_area:
            continue
        contour_area = float(cv2.contourArea(contour))
        if contour_area < float(min_component_area):
            continue
        perimeter = float(cv2.arcLength(contour, True))
        if perimeter <= 0:
            continue
        approx = cv2.approxPolyDP(contour, 0.03 * perimeter, True)
        aspect_ratio = float(w / float(h))
        extent = contour_area / float(box_area)
        if 4 <= len(approx) <= 10 and 1.2 <= aspect_ratio <= 4.5 and extent >= 0.45:
            rectangular_regions += 1

    if rectangular_regions >= 3 and len(solid_rects) < 3 and ink_ratio <= 0.12:
        return "diagram"

    return ""


def append_image_understanding_text(
    text: str,
    *,
    caption: str = "",
    ocr_text: str = "",
    code_text: str = "",
) -> str:
    """
    Append caption/OCR text into chunk content so it becomes retrievable.
    """
    base = (text or "").rstrip()
    blocks: list[str] = []
    if base:
        blocks.append(base)

    caption0 = (caption or "").strip()
    if caption0 and "image caption:" not in base.lower():
        blocks.append(f"Image caption: {caption0}")

    ocr0 = (ocr_text or "").strip()
    if ocr0 and "image ocr:" not in base.lower():
        blocks.append(f"Image OCR:\n{ocr0}")

    code0 = (code_text or "").strip()
    if code0 and "image code:" not in base.lower():
        blocks.append(f"Image code:\n{code0}")

    return "\n\n".join(blocks).strip() + ("\n" if (text or "").endswith("\n") else "")


__all__ = [
    "append_image_understanding_text",
    "decode_image_codes",
    "derive_image_caption",
    "infer_visual_kind_from_pixels",
    "load_image_for_ocr",
    "ocr_image",
]
