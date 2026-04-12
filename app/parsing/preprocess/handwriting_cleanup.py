"""
Handwriting/noise cleanup helpers for preprocessing.

This stage is feature-flagged and best-effort:
- local backend: validate model availability so the pipeline can surface clear warnings
- http backend: forward the file to a remote cleanup service and store returned bytes
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from app.parsing.preprocess.model_loader import get_preprocess_model_loader

_RASTER_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


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
    if _positive_int(dims[-1]) in {1, 3}:
        return "nhwc"
    if _positive_int(dims[1]) in {1, 3}:
        return "nchw"
    return "nchw"


def _infer_onnx_channels(shape: Any, *, layout: str) -> int:
    dims = list(shape or [])
    if len(dims) != 4:
        return 3
    if layout == "nhwc":
        channels = _positive_int(dims[-1])
    else:
        channels = _positive_int(dims[1])
    return channels if channels in {1, 3} else 3


def _run_local_onnx_cleanup(*, input_path: Path, output_path: Path, session: Any) -> bool:
    import numpy as np
    from PIL import Image

    if input_path.suffix.lower() not in _RASTER_EXTS:
        raise ValueError("unsupported_input_type")

    inputs = list(session.get_inputs() or [])
    input_name = str(getattr(inputs[0], "name", "") or "input")
    input_shape = getattr(inputs[0], "shape", None) if inputs else None
    input_layout = _infer_onnx_layout(input_shape)
    input_channels = _infer_onnx_channels(input_shape, layout=input_layout)

    target_width: int | None = None
    target_height: int | None = None
    dims = list(input_shape or [])
    if len(dims) == 4:
        if input_layout == "nhwc":
            target_height = _positive_int(dims[1])
            target_width = _positive_int(dims[2])
        else:
            target_height = _positive_int(dims[2])
            target_width = _positive_int(dims[3])

    with Image.open(input_path) as image:
        source = image.convert("L" if input_channels == 1 else "RGB")
        original_size = source.size
        prepared = source
        if target_width and target_height and (target_width, target_height) != original_size:
            prepared = source.resize((target_width, target_height))

        arr = np.asarray(prepared, dtype=np.float32)
        if input_layout == "nhwc":
            if input_channels == 1:
                if arr.ndim == 2:
                    arr = arr[..., None]
                tensor = (arr / 255.0)[None, ...]
            else:
                tensor = (arr / 255.0)[None, ...]
        else:
            if input_channels == 1:
                if arr.ndim == 3:
                    arr = arr[..., 0]
                tensor = (arr / 255.0)[None, None, ...]
            else:
                tensor = np.transpose(arr / 255.0, (2, 0, 1))[None, ...]

    outputs = list(session.run(None, {input_name: tensor}) or [])
    if not outputs:
        raise ValueError("empty_output")

    result = np.asarray(outputs[0])
    if result.ndim == 4:
        result = result[0]
    if result.ndim == 3 and result.shape[0] in {1, 3} and result.shape[-1] not in {1, 3}:
        result = np.transpose(result, (1, 2, 0))
    if result.ndim == 3 and result.shape[-1] == 1:
        result = result[..., 0]
    if result.ndim not in {2, 3}:
        raise ValueError("unsupported_output_shape")

    if result.dtype.kind in {"f", "c"}:
        if float(result.min()) < 0.0:
            result = (result + 1.0) / 2.0
        if float(result.max()) <= 1.5:
            result = result * 255.0
    result = np.clip(result, 0, 255).astype("uint8")

    if result.ndim == 2:
        cleaned = Image.fromarray(result, mode="L")
    else:
        cleaned = Image.fromarray(result, mode="RGB")
    if cleaned.size != original_size:
        cleaned = cleaned.resize(original_size)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned.save(output_path)

    try:
        return output_path.read_bytes() != input_path.read_bytes()
    except Exception:
        return True


def cleanup_handwriting_document(
    *,
    input_path: Path,
    output_path: Path,
    backend: str,
    model_path: str = "",
    api_url: str = "",
    timeout_sec: float = 60.0,
) -> tuple[bool, str, dict[str, Any]]:
    normalized_backend = str(backend or "auto").strip().lower() or "auto"
    info: dict[str, Any] = {"backend": normalized_backend}

    if normalized_backend == "skip":
        return False, "skipped", info

    if normalized_backend == "auto":
        has_api = bool(str(api_url or "").strip())
        has_model = bool(str(model_path or "").strip())
        if has_api:
            normalized_backend = "http"
        elif has_model:
            normalized_backend = "local"
        elif input_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            normalized_backend = "heuristic"
        else:
            normalized_backend = "skip"
        info["backend"] = normalized_backend

    if normalized_backend == "skip":
        return False, "skipped", info

    if normalized_backend == "heuristic":
        try:
            from PIL import Image, ImageEnhance, ImageFilter, ImageOps

            with Image.open(input_path) as image:
                cleaned = ImageOps.autocontrast(ImageOps.grayscale(image))
                cleaned = ImageEnhance.Contrast(cleaned).enhance(1.25)
                cleaned = cleaned.filter(ImageFilter.SHARPEN)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                cleaned.save(output_path)
        except Exception as exc:  # noqa: BLE001
            return False, f"heuristic_failed:{exc.__class__.__name__}", info

        try:
            changed = output_path.read_bytes() != input_path.read_bytes()
        except Exception:
            changed = True
        return changed, "cleanup_ok" if changed else "cleanup_no_change", info

    if normalized_backend in {"local", "onnx"}:
        model_ref = str(model_path or "").strip()
        if not model_ref:
            return False, "missing_model_path", info
        try:
            loaded = get_preprocess_model_loader().load_onnx(name="handwriting_cleanup", model_path=model_ref)
            info["model_backend"] = str(loaded.backend or "")
            info["model_name"] = str(loaded.name or "")
        except Exception as exc:  # noqa: BLE001
            return False, f"model_unavailable:{exc.__class__.__name__}", info
        try:
            changed = _run_local_onnx_cleanup(input_path=input_path, output_path=output_path, session=loaded.handle)
        except ValueError as exc:
            return False, f"onnx_{exc}", info
        except Exception as exc:  # noqa: BLE001
            return False, f"onnx_failed:{exc.__class__.__name__}", info
        return changed, "cleanup_ok" if changed else "cleanup_no_change", info

    if normalized_backend != "http":
        return False, "unsupported_backend", info

    target_url = str(api_url or "").strip()
    if not target_url:
        return False, "missing_api_url", info

    try:
        file_bytes = input_path.read_bytes()
        response = requests.post(
            target_url,
            files={"file": (input_path.name, file_bytes, "application/octet-stream")},
            timeout=float(timeout_sec),
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"http_failed:{exc.__class__.__name__}", info

    if int(response.status_code) >= 400:
        return False, f"http_{int(response.status_code)}", info
    if not response.content:
        return False, "empty_response", info

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
    except Exception as exc:  # noqa: BLE001
        return False, f"write_failed:{exc.__class__.__name__}", info

    changed = response.content != file_bytes
    return changed, "cleanup_ok" if changed else "cleanup_no_change", info


__all__ = ["cleanup_handwriting_document"]
