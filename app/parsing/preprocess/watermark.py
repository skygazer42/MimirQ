"""
Watermark helpers for preprocessing (Module 2).

This provides three best-effort paths:
1) PDF annotation stripping via PyMuPDF (cheap; no model).
2) External HTTP watermark removal backend.
3) Local ONNX inpainting with OCR/rule/geometry-derived mask boxes.
"""

from __future__ import annotations

import asyncio
import math
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw

from app.parsing.enrich.watermark_suppressor import suppress_watermark_file
from app.parsing.preprocess.model_loader import get_preprocess_model_loader
from app.rag.core.logging import get_logger

_RASTER_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
logger = get_logger(__name__)


def _run_coroutine_sync(factory: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(factory())).result()


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except Exception:
        return None
    return number if number > 0 else None


def _infer_onnx_layout(shape: Any) -> str:
    dims = list(shape or [])
    if len(dims) != 4:
        return "nchw"
    if _positive_int(dims[-1]) in {1, 3, 4}:
        return "nhwc"
    if _positive_int(dims[1]) in {1, 3, 4}:
        return "nchw"
    return "nchw"


def _normalize_ocr_line(line: Any) -> dict[str, Any] | None:
    if not isinstance(line, (list, tuple)) or len(line) < 2:
        return None
    points = line[0]
    if not isinstance(points, (list, tuple)) or not points:
        return None
    out_points: list[tuple[float, float]] = []
    for item in points:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            out_points.append((float(item[0]), float(item[1])))
        except Exception:
            continue
    if not out_points:
        return None

    text_raw = line[1]
    score = None
    if isinstance(text_raw, (list, tuple)) and text_raw:
        text = str(text_raw[0] or "").strip()
        if len(text_raw) >= 2:
            try:
                score = float(text_raw[1])
            except Exception:
                score = None
    else:
        text = str(text_raw or "").strip()
        if len(line) >= 3:
            try:
                score = float(line[2])
            except Exception:
                score = None

    if not text:
        return None
    xs = [p[0] for p in out_points]
    ys = [p[1] for p in out_points]
    return {
        "text": text,
        "score": score,
        "points": out_points,
        "bbox": [min(xs), min(ys), max(xs), max(ys)],
    }


def _ocr_lines_for_mask(image: Image.Image) -> list[dict[str, Any]]:
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
    except Exception:
        return []

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        image.save(tmp_path)
        engine = RapidOCR(det_box_thresh=0.2)
        result, _ = engine(str(tmp_path))
    except Exception:
        result = []
    finally:
        try:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink()
        except Exception as exc:
            logger.debug("Ignoring non-critical watermark preprocess fallback failure: %s", exc)

    out: list[dict[str, Any]] = []
    for line in result or []:
        item = _normalize_ocr_line(line)
        if item:
            out.append(item)
    return out


def _estimate_angle_deg(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    (x0, y0), (x1, y1) = points[0], points[1]
    return abs(math.degrees(math.atan2(y1 - y0, x1 - x0)))


def _is_center_region(*, bbox: list[float], width: int, height: int) -> bool:
    x0, y0, x1, y1 = bbox
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    return (0.18 * width) <= cx <= (0.82 * width) and (0.18 * height) <= cy <= (0.82 * height)


def _crop_stddev(gray: Image.Image, bbox: list[float]) -> float:
    import numpy as np

    x0, y0, x1, y1 = bbox
    crop = gray.crop((int(max(0, x0)), int(max(0, y0)), int(max(x0 + 1, x1)), int(max(y0 + 1, y1))))
    arr = np.asarray(crop, dtype="float32")
    if arr.size <= 0:
        return 0.0
    return float(arr.std())


def _collect_watermark_mask_boxes(image: Image.Image, *, max_boxes: int = 32) -> list[dict[str, Any]]:
    import re

    width, height = image.size
    gray = image.convert("L")
    keyword_re = re.compile(r"(draft|company confidential|for internal use only|仅供内部使用|机密|保密)", re.IGNORECASE)
    boxes: list[dict[str, Any]] = []
    for item in _ocr_lines_for_mask(image):
        bbox = list(item.get("bbox") or [])
        points = list(item.get("points") or [])
        text = str(item.get("text") or "").strip()
        if len(bbox) != 4 or not text:
            continue
        x0, y0, x1, y1 = bbox
        bw = max(1.0, float(x1) - float(x0))
        bh = max(1.0, float(y1) - float(y0))
        area_ratio = (bw * bh) / float(max(1, width * height))
        width_ratio = bw / float(max(1, width))
        angle = _estimate_angle_deg(points)
        low_contrast = _crop_stddev(gray, bbox) <= 28.0
        centerish = _is_center_region(bbox=bbox, width=width, height=height)

        reason = ""
        if keyword_re.search(text):
            reason = "keyword"
        elif centerish and low_contrast and (width_ratio >= 0.22 or area_ratio >= 0.035 or (12.0 <= angle <= 78.0)):
            reason = "geometry"
        if not reason:
            continue

        pad_x = max(6.0, bw * 0.08)
        pad_y = max(6.0, bh * 0.25)
        boxes.append(
            {
                "bbox": [
                    max(0.0, x0 - pad_x),
                    max(0.0, y0 - pad_y),
                    min(float(width), x1 + pad_x),
                    min(float(height), y1 + pad_y),
                ],
                "text": text,
                "score": item.get("score"),
                "reason": reason,
            }
        )
        if len(boxes) >= int(max_boxes or 32):
            break
    return boxes


def _mask_image_from_boxes(*, size: tuple[int, int], boxes: list[dict[str, Any]]) -> Image.Image:
    mask = Image.new("L", size, color=0)
    draw = ImageDraw.Draw(mask)
    for item in boxes:
        bbox = list(item.get("bbox") or [])
        if len(bbox) != 4:
            continue
        draw.rectangle(tuple(float(v) for v in bbox), fill=255)
    return mask


def _run_local_onnx_inpaint(*, input_path: Path, output_path: Path, session: Any, mask_image: Image.Image) -> bool:
    import numpy as np

    if input_path.suffix.lower() not in _RASTER_EXTS:
        raise ValueError("unsupported_input_type")

    with Image.open(input_path) as image:
        source = image.convert("RGB")
        original_size = source.size

    inputs = list(session.get_inputs() or [])
    if not inputs:
        raise ValueError("empty_inputs")
    image_input = inputs[0]
    mask_input = inputs[1] if len(inputs) > 1 else None
    layout = _infer_onnx_layout(getattr(image_input, "shape", None))
    dims = list(getattr(image_input, "shape", None) or [])
    target_height = None
    target_width = None
    if len(dims) == 4:
        if layout == "nhwc":
            target_height = _positive_int(dims[1])
            target_width = _positive_int(dims[2])
        else:
            target_height = _positive_int(dims[2])
            target_width = _positive_int(dims[3])

    prepared = source
    prepared_mask = mask_image.convert("L")
    if target_width and target_height and (target_width, target_height) != original_size:
        prepared = prepared.resize((target_width, target_height))
        prepared_mask = prepared_mask.resize((target_width, target_height))

    image_arr = np.asarray(prepared, dtype=np.float32) / 255.0
    mask_arr = (np.asarray(prepared_mask, dtype=np.float32) > 0).astype("float32")
    if mask_input is not None:
        if layout == "nhwc":
            feeds = {
                str(getattr(image_input, "name", "") or "image"): image_arr[None, ...],
                str(getattr(mask_input, "name", "") or "mask"): mask_arr[None, ..., None],
            }
        else:
            feeds = {
                str(getattr(image_input, "name", "") or "image"): np.transpose(image_arr, (2, 0, 1))[None, ...],
                str(getattr(mask_input, "name", "") or "mask"): mask_arr[None, None, ...],
            }
    else:
        if layout == "nhwc":
            combined = np.concatenate([image_arr, mask_arr[..., None]], axis=-1)[None, ...]
        else:
            combined = np.concatenate([np.transpose(image_arr, (2, 0, 1)), mask_arr[None, ...]], axis=0)[None, ...]
        feeds = {str(getattr(image_input, "name", "") or "image"): combined}

    outputs = list(session.run(None, feeds) or [])
    if not outputs:
        raise ValueError("empty_output")
    arr = np.asarray(outputs[0])
    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim == 3 and arr.shape[0] in {1, 3} and arr.shape[-1] not in {1, 3}:
        arr = np.transpose(arr, (1, 2, 0))
    if arr.ndim == 3 and arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    if arr.ndim != 3:
        raise ValueError("unsupported_output_shape")
    if arr.dtype.kind in {"f", "c"} and float(arr.max()) <= 1.5:
        arr = arr * 255.0
    arr = arr.clip(0, 255).astype("uint8")
    cleaned = Image.fromarray(arr, mode="RGB")
    if cleaned.size != original_size:
        cleaned = cleaned.resize(original_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned.save(output_path)
    try:
        return output_path.read_bytes() != input_path.read_bytes()
    except Exception:
        return True


def strip_pdf_watermark_annotations(
    *,
    input_path: Path,
    output_path: Path,
    sample_pages: int = 3,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Remove watermark/stamp-like annotations from a PDF (best-effort).

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
    removed = 0
    scanned_pages = 0
    try:
        doc = fitz.open(str(input_path))
        n = int(doc.page_count)
        k = max(1, min(int(sample_pages or 0) or 1, n))
        for i in range(k):
            page = doc.load_page(i)
            scanned_pages += 1
            annots = list(page.annots() or [])
            for annot in annots:
                try:
                    typ = getattr(annot, "type", None)
                    name = ""
                    if isinstance(typ, (tuple, list)) and len(typ) >= 2:
                        name = str(typ[1] or "")
                    info = getattr(annot, "info", None) or {}
                    subject = str((info or {}).get("subject") or (info or {}).get("title") or "")
                    hint = f"{name} {subject}".lower()
                    if "watermark" in hint or name.strip().lower() in {"watermark", "stamp"}:
                        page.delete_annot(annot)
                        removed += 1
                except Exception:
                    continue

        if removed <= 0:
            meta["removed"] = 0
            meta["scanned_pages"] = int(scanned_pages)
            meta["elapsed_ms"] = int(round((time.perf_counter() - t0) * 1000))
            return False, "no_watermark_annots", meta

        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(output_path), garbage=4, deflate=True)
        meta["removed"] = int(removed)
        meta["scanned_pages"] = int(scanned_pages)
        meta["elapsed_ms"] = int(round((time.perf_counter() - t0) * 1000))
        return True, f"removed_annots:{removed}", meta
    except Exception as exc:  # noqa: BLE001
        meta["elapsed_ms"] = int(round((time.perf_counter() - t0) * 1000))
        return False, f"strip_failed:{exc.__class__.__name__}", meta
    finally:
        try:
            if doc is not None:
                doc.close()
        except Exception as exc:
            logger.debug("Ignoring non-critical watermark preprocess fallback failure: %s", exc)


async def _remove_watermark_via_http_async(
    *,
    input_path: Path,
    output_path: Path,
    url: str,
    timeout_sec: float,
) -> tuple[bool, str]:
    """
    Generic watermark removal via an external service.

    Contract (best-effort):
    - POST multipart form with file field "file"
    - Response body is treated as the processed file bytes (PDF or image).
    """
    try:
        file_bytes = input_path.read_bytes()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                str(url).strip(),
                files={"file": (input_path.name, file_bytes, "application/octet-stream")},
                timeout=float(timeout_sec),
            )
    except Exception as exc:  # noqa: BLE001
        return False, f"watermark_http_failed:{exc.__class__.__name__}"

    if int(resp.status_code) >= 400:
        return False, f"watermark_http_{int(resp.status_code)}"
    if not resp.content:
        return False, "watermark_empty_response"

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(resp.content)
        return True, "watermark_ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"watermark_write_failed:{exc.__class__.__name__}"


def remove_watermark_via_http(
    *,
    input_path: Path,
    output_path: Path,
    url: str,
    timeout_sec: float,
) -> tuple[bool, str]:
    return _run_coroutine_sync(
        lambda: _remove_watermark_via_http_async(
            input_path=input_path,
            output_path=output_path,
            url=url,
            timeout_sec=timeout_sec,
        )
    )


def cleanup_watermark_document(
    *,
    input_path: Path,
    output_path: Path,
    backend: str,
    model_path: str = "",
    api_url: str = "",
    timeout_sec: float = 120.0,
) -> tuple[bool, str, dict[str, Any]]:
    normalized_backend = str(backend or "auto").strip().lower() or "auto"
    info: dict[str, Any] = {"backend": normalized_backend}

    if normalized_backend == "skip":
        return False, "skipped", info

    if normalized_backend == "auto":
        if str(model_path or "").strip():
            normalized_backend = "local"
        elif str(api_url or "").strip():
            normalized_backend = "http"
        elif input_path.suffix.lower() in _RASTER_EXTS:
            normalized_backend = "heuristic"
        else:
            normalized_backend = "http"
        info["backend"] = normalized_backend

    if normalized_backend == "heuristic":
        if input_path.suffix.lower() not in _RASTER_EXTS:
            return False, "unsupported_input_type", info
        try:
            with Image.open(input_path) as image:
                boxes = _collect_watermark_mask_boxes(image)
            info["mask_box_count"] = int(len(boxes))
            info["mask_reasons"] = [str(item.get("reason") or "") for item in boxes if str(item.get("reason") or "")]
            if not boxes:
                return False, "no_mask_boxes", info
            changed, suppress_meta = suppress_watermark_file(input_path=input_path, output_path=output_path, boxes=boxes)
            info["suppressor"] = suppress_meta
        except Exception as exc:  # noqa: BLE001
            return False, f"heuristic_failed:{exc.__class__.__name__}", info
        return changed, "watermark_ok" if changed else "watermark_no_change", info

    if normalized_backend == "local":
        model_ref = str(model_path or "").strip()
        if not model_ref:
            return False, "missing_model_path", info
        try:
            loaded = get_preprocess_model_loader().load_onnx(name="watermark_removal", model_path=model_ref)
            info["model_backend"] = str(loaded.backend or "")
            info["model_name"] = str(loaded.name or "")
        except Exception as exc:  # noqa: BLE001
            return False, f"model_unavailable:{exc.__class__.__name__}", info
        if input_path.suffix.lower() not in _RASTER_EXTS:
            return False, "unsupported_input_type", info
        try:
            with Image.open(input_path) as image:
                boxes = _collect_watermark_mask_boxes(image)
                info["mask_box_count"] = int(len(boxes))
                info["mask_reasons"] = [str(item.get("reason") or "") for item in boxes if str(item.get("reason") or "")]
                if not boxes:
                    return False, "no_mask_boxes", info
                mask = _mask_image_from_boxes(size=image.size, boxes=boxes)
            changed = _run_local_onnx_inpaint(input_path=input_path, output_path=output_path, session=loaded.handle, mask_image=mask)
        except ValueError as exc:
            return False, f"onnx_{exc}", info
        except Exception as exc:  # noqa: BLE001
            return False, f"onnx_failed:{exc.__class__.__name__}", info
        return changed, "watermark_ok" if changed else "watermark_no_change", info

    if normalized_backend != "http":
        return False, "unsupported_backend", info

    target_url = str(api_url or "").strip()
    if not target_url:
        return False, "missing_api_url", info
    changed, note = remove_watermark_via_http(
        input_path=input_path,
        output_path=output_path,
        url=target_url,
        timeout_sec=timeout_sec,
    )
    return changed, note, info


__all__ = [
    "cleanup_watermark_document",
    "remove_watermark_via_http",
    "strip_pdf_watermark_annotations",
]
