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


def _ocr_points(points: Any) -> list[tuple[float, float]]:
    if not isinstance(points, (list, tuple)) or not points:
        return []
    out_points: list[tuple[float, float]] = []
    for item in points:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            out_points.append((float(item[0]), float(item[1])))
        except Exception:
            continue
    return out_points


def _ocr_text_and_score(line: Any) -> tuple[str, float | None]:
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
    return text, score


def _normalize_ocr_line(line: Any) -> dict[str, Any] | None:
    if not isinstance(line, (list, tuple)) or len(line) < 2:
        return None
    out_points = _ocr_points(line[0])
    if not out_points:
        return None

    text, score = _ocr_text_and_score(line)
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

    try:
        with tempfile.TemporaryDirectory(prefix="watermark_ocr_") as tmp_dir:
            tmp_path = Path(tmp_dir) / "sample.png"
            image.save(tmp_path)
            engine = RapidOCR(det_box_thresh=0.2)
            result, _ = engine(str(tmp_path))
    except Exception:
        result = []

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


def _watermark_reason(
    *,
    text: str,
    bbox: list[float],
    points: list[tuple[float, float]],
    width: int,
    height: int,
    gray: Image.Image,
) -> str:
    import re

    keyword_re = re.compile(r"(draft|company confidential|for internal use only|仅供内部使用|机密|保密)", re.IGNORECASE)
    x0, y0, x1, y1 = bbox
    box_width = max(1.0, float(x1) - float(x0))
    box_height = max(1.0, float(y1) - float(y0))
    area_ratio = (box_width * box_height) / float(max(1, width * height))
    width_ratio = box_width / float(max(1, width))
    angle = _estimate_angle_deg(points)
    low_contrast = _crop_stddev(gray, bbox) <= 28.0
    centerish = _is_center_region(bbox=bbox, width=width, height=height)

    if keyword_re.search(text):
        return "keyword"
    if centerish and low_contrast and (width_ratio >= 0.22 or area_ratio >= 0.035 or (12.0 <= angle <= 78.0)):
        return "geometry"
    return ""


def _padded_watermark_box(*, bbox: list[float], width: int, height: int) -> list[float]:
    x0, y0, x1, y1 = bbox
    box_width = max(1.0, float(x1) - float(x0))
    box_height = max(1.0, float(y1) - float(y0))
    pad_x = max(6.0, box_width * 0.08)
    pad_y = max(6.0, box_height * 0.25)
    return [
        max(0.0, x0 - pad_x),
        max(0.0, y0 - pad_y),
        min(float(width), x1 + pad_x),
        min(float(height), y1 + pad_y),
    ]


def _watermark_box_from_ocr_item(
    item: dict[str, Any],
    *,
    width: int,
    height: int,
    gray: Image.Image,
) -> dict[str, Any] | None:
    bbox = list(item.get("bbox") or [])
    points = list(item.get("points") or [])
    text = str(item.get("text") or "").strip()
    if len(bbox) != 4 or not text:
        return None

    reason = _watermark_reason(text=text, bbox=bbox, points=points, width=width, height=height, gray=gray)
    if not reason:
        return None
    return {
        "bbox": _padded_watermark_box(bbox=bbox, width=width, height=height),
        "text": text,
        "score": item.get("score"),
        "reason": reason,
    }


def _collect_watermark_mask_boxes(image: Image.Image, *, max_boxes: int = 32) -> list[dict[str, Any]]:
    width, height = image.size
    gray = image.convert("L")
    boxes: list[dict[str, Any]] = []
    for item in _ocr_lines_for_mask(image):
        box = _watermark_box_from_ocr_item(item, width=width, height=height, gray=gray)
        if box is None:
            continue
        boxes.append(box)
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


def _onnx_target_size(*, dims: list[Any], layout: str) -> tuple[int | None, int | None]:
    if len(dims) != 4:
        return None, None
    if layout == "nhwc":
        return _positive_int(dims[2]), _positive_int(dims[1])
    return _positive_int(dims[3]), _positive_int(dims[2])


def _prepare_onnx_images(
    *,
    source: Image.Image,
    mask_image: Image.Image,
    target_width: int | None,
    target_height: int | None,
) -> tuple[Image.Image, Image.Image]:
    prepared = source
    prepared_mask = mask_image.convert("L")
    if target_width and target_height and (target_width, target_height) != source.size:
        prepared = prepared.resize((target_width, target_height))
        prepared_mask = prepared_mask.resize((target_width, target_height))
    return prepared, prepared_mask


def _onnx_feeds(
    *,
    image_input: Any,
    mask_input: Any | None,
    image_arr: Any,
    mask_arr: Any,
    layout: str,
) -> dict[str, Any]:
    import numpy as np

    image_name = str(getattr(image_input, "name", "") or "image")
    if mask_input is None:
        if layout == "nhwc":
            combined = np.concatenate([image_arr, mask_arr[..., None]], axis=-1)[None, ...]
        else:
            combined = np.concatenate([np.transpose(image_arr, (2, 0, 1)), mask_arr[None, ...]], axis=0)[None, ...]
        return {image_name: combined}

    mask_name = str(getattr(mask_input, "name", "") or "mask")
    if layout == "nhwc":
        return {image_name: image_arr[None, ...], mask_name: mask_arr[None, ..., None]}
    return {image_name: np.transpose(image_arr, (2, 0, 1))[None, ...], mask_name: mask_arr[None, None, ...]}


def _normalize_onnx_output(output: Any, *, original_size: tuple[int, int]) -> Image.Image:
    import numpy as np

    arr = np.asarray(output)
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
    return cleaned.resize(original_size) if cleaned.size != original_size else cleaned


def _output_changed(*, input_path: Path, output_path: Path) -> bool:
    try:
        return output_path.read_bytes() != input_path.read_bytes()
    except Exception:
        return True


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
    target_width, target_height = _onnx_target_size(dims=dims, layout=layout)
    prepared, prepared_mask = _prepare_onnx_images(
        source=source,
        mask_image=mask_image,
        target_width=target_width,
        target_height=target_height,
    )

    image_arr = np.asarray(prepared, dtype=np.float32) / 255.0
    mask_arr = (np.asarray(prepared_mask, dtype=np.float32) > 0).astype("float32")
    feeds = _onnx_feeds(
        image_input=image_input,
        mask_input=mask_input,
        image_arr=image_arr,
        mask_arr=mask_arr,
        layout=layout,
    )

    outputs = list(session.run(None, feeds) or [])
    if not outputs:
        raise ValueError("empty_output")
    cleaned = _normalize_onnx_output(outputs[0], original_size=original_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned.save(output_path)
    return _output_changed(input_path=input_path, output_path=output_path)


def _elapsed_ms(start: float) -> int:
    return int(round((time.perf_counter() - start) * 1000))


def _annotation_name_and_subject(annot: Any) -> tuple[str, str]:
    typ = getattr(annot, "type", None)
    name = ""
    if isinstance(typ, (tuple, list)) and len(typ) >= 2:
        name = str(typ[1] or "")
    info = getattr(annot, "info", None) or {}
    subject = str((info or {}).get("subject") or (info or {}).get("title") or "")
    return name, subject


def _is_watermark_annotation(annot: Any) -> bool:
    name, subject = _annotation_name_and_subject(annot)
    hint = f"{name} {subject}".lower()
    return "watermark" in hint or name.strip().lower() in {"watermark", "stamp"}


def _remove_watermark_annots_from_page(page: Any) -> int:
    removed = 0
    for annot in page.annots() or []:
        try:
            if _is_watermark_annotation(annot):
                page.delete_annot(annot)
                removed += 1
        except Exception:
            continue
    return removed


def _strip_pdf_meta(meta: dict[str, Any], *, removed: int, scanned_pages: int, start: float) -> dict[str, Any]:
    meta["removed"] = int(removed)
    meta["scanned_pages"] = int(scanned_pages)
    meta["elapsed_ms"] = _elapsed_ms(start)
    return meta


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
        meta["elapsed_ms"] = _elapsed_ms(t0)
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
            removed += _remove_watermark_annots_from_page(page)

        if removed <= 0:
            _strip_pdf_meta(meta, removed=0, scanned_pages=scanned_pages, start=t0)
            return False, "no_watermark_annots", meta

        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(output_path), garbage=4, deflate=True)
        _strip_pdf_meta(meta, removed=removed, scanned_pages=scanned_pages, start=t0)
        return True, f"removed_annots:{removed}", meta
    except Exception as exc:  # noqa: BLE001
        meta["elapsed_ms"] = _elapsed_ms(t0)
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
        timeout = float(timeout_sec)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                str(url).strip(),
                files={"file": (input_path.name, file_bytes, "application/octet-stream")},
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


def _resolve_watermark_backend(
    *,
    backend: str,
    model_path: str,
    api_url: str,
    input_path: Path,
) -> tuple[str, bool]:
    normalized_backend = str(backend or "auto").strip().lower() or "auto"
    auto_selected = normalized_backend == "auto"
    if not auto_selected:
        return normalized_backend, False
    if str(model_path or "").strip():
        return "local", True
    if str(api_url or "").strip():
        return "http", True
    if input_path.suffix.lower() in _RASTER_EXTS:
        return "heuristic", True
    return "http", True


def _record_mask_info(info: dict[str, Any], boxes: list[dict[str, Any]]) -> None:
    info["mask_box_count"] = int(len(boxes))
    info["mask_reasons"] = [str(item.get("reason") or "") for item in boxes if str(item.get("reason") or "")]


def _collect_mask_boxes_for_path(input_path: Path, info: dict[str, Any]) -> list[dict[str, Any]]:
    with Image.open(input_path) as image:
        boxes = _collect_watermark_mask_boxes(image)
    _record_mask_info(info, boxes)
    return boxes


def _cleanup_watermark_heuristic(
    *,
    input_path: Path,
    output_path: Path,
    info: dict[str, Any],
    auto_selected: bool,
    api_url: str,
) -> tuple[bool, str, dict[str, Any]]:
    if input_path.suffix.lower() not in _RASTER_EXTS:
        return False, "unsupported_input_type", info
    try:
        boxes = _collect_mask_boxes_for_path(input_path, info)
        if not boxes:
            return False, "no_mask_boxes", info
        changed, suppress_meta = suppress_watermark_file(input_path=input_path, output_path=output_path, boxes=boxes)
        info["suppressor"] = suppress_meta
    except Exception as exc:  # noqa: BLE001
        if auto_selected and not str(api_url or "").strip():
            return False, "missing_api_url", info
        return False, f"heuristic_failed:{exc.__class__.__name__}", info
    return changed, "watermark_ok" if changed else "watermark_no_change", info


def _load_watermark_onnx(model_path: str, info: dict[str, Any]) -> Any | None:
    model_ref = str(model_path or "").strip()
    if not model_ref:
        return None
    loaded = get_preprocess_model_loader().load_onnx(name="watermark_removal", model_path=model_ref)
    info["model_backend"] = str(loaded.backend or "")
    info["model_name"] = str(loaded.name or "")
    return loaded


def _cleanup_watermark_local(
    *,
    input_path: Path,
    output_path: Path,
    model_path: str,
    info: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    if not str(model_path or "").strip():
        return False, "missing_model_path", info
    try:
        loaded = _load_watermark_onnx(model_path, info)
    except Exception as exc:  # noqa: BLE001
        return False, f"model_unavailable:{exc.__class__.__name__}", info
    if loaded is None:
        return False, "missing_model_path", info
    if input_path.suffix.lower() not in _RASTER_EXTS:
        return False, "unsupported_input_type", info
    try:
        with Image.open(input_path) as image:
            boxes = _collect_watermark_mask_boxes(image)
            _record_mask_info(info, boxes)
            if not boxes:
                return False, "no_mask_boxes", info
            mask = _mask_image_from_boxes(size=image.size, boxes=boxes)
        changed = _run_local_onnx_inpaint(
            input_path=input_path,
            output_path=output_path,
            session=loaded.handle,
            mask_image=mask,
        )
    except ValueError as exc:
        return False, f"onnx_{exc}", info
    except Exception as exc:  # noqa: BLE001
        return False, f"onnx_failed:{exc.__class__.__name__}", info
    return changed, "watermark_ok" if changed else "watermark_no_change", info


def _cleanup_watermark_http(
    *,
    input_path: Path,
    output_path: Path,
    api_url: str,
    timeout_sec: float,
    info: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
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


def cleanup_watermark_document(
    *,
    input_path: Path,
    output_path: Path,
    backend: str,
    model_path: str = "",
    api_url: str = "",
    timeout_sec: float = 120.0,
) -> tuple[bool, str, dict[str, Any]]:
    normalized_backend, auto_selected = _resolve_watermark_backend(
        backend=backend,
        model_path=model_path,
        api_url=api_url,
        input_path=input_path,
    )
    info: dict[str, Any] = {"backend": normalized_backend}

    if normalized_backend == "skip":
        return False, "skipped", info

    if normalized_backend == "heuristic":
        return _cleanup_watermark_heuristic(
            input_path=input_path,
            output_path=output_path,
            info=info,
            auto_selected=auto_selected,
            api_url=api_url,
        )

    if normalized_backend == "local":
        return _cleanup_watermark_local(
            input_path=input_path,
            output_path=output_path,
            model_path=model_path,
            info=info,
        )

    if normalized_backend != "http":
        return False, "unsupported_backend", info

    return _cleanup_watermark_http(
        input_path=input_path,
        output_path=output_path,
        api_url=api_url,
        timeout_sec=timeout_sec,
        info=info,
    )


__all__ = [
    "cleanup_watermark_document",
    "remove_watermark_via_http",
    "strip_pdf_watermark_annotations",
]
