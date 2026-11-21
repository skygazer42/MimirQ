"""
Handwriting/noise cleanup helpers for preprocessing.

This stage is feature-flagged and best-effort:
- local backend: validate model availability so the pipeline can surface clear warnings
- http backend: forward the file to a remote cleanup service and store returned bytes
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack, closing
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from app.infrastructure.runtime.async_bridge import run_coroutine_sync as _run_coroutine_sync
from app.rag.ingestion.parsing.preprocess.model_loader import get_preprocess_model_loader, positive_onnx_dimension

if TYPE_CHECKING:
    from onnxruntime import InferenceSession

_RASTER_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


async def _cleanup_handwriting_via_http_async(
    *,
    input_path: Path,
    output_path: Path,
    target_url: str,
    timeout_sec: float,
    info: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    try:
        file_bytes = await asyncio.to_thread(input_path.read_bytes)
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            response = await client.post(
                target_url,
                files={"file": (input_path.name, file_bytes, "application/octet-stream")},
            )
    except (OSError, httpx.HTTPError) as exc:
        return False, f"http_failed:{exc.__class__.__name__}", info

    if response.status_code >= 400:
        return False, f"http_{response.status_code}", info
    if not response.content:
        return False, "empty_response", info

    try:
        await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(output_path.write_bytes, response.content)
    except OSError as exc:
        return False, f"write_failed:{exc.__class__.__name__}", info

    changed = response.content != file_bytes
    return changed, "cleanup_ok" if changed else "cleanup_no_change", info


def _infer_onnx_layout(shape: Any) -> str:
    dims = list(shape or [])
    if len(dims) != 4:
        raise ValueError("unsupported_input_shape")
    if positive_onnx_dimension(dims[-1]) in {1, 3}:
        return "nhwc"
    return "nchw"


def _infer_onnx_channels(shape: Any, *, layout: str) -> int:
    dims = list(shape or [])
    if layout == "nhwc":
        channels = positive_onnx_dimension(dims[-1])
    else:
        channels = positive_onnx_dimension(dims[1])
    return channels if channels in {1, 3} else 3


def _onnx_input_spec(session: InferenceSession) -> tuple[str, Any, str, int]:
    inputs = session.get_inputs()
    input_info = inputs[0]
    input_name = input_info.name
    input_shape = input_info.shape
    input_layout = _infer_onnx_layout(input_shape)
    input_channels = _infer_onnx_channels(input_shape, layout=input_layout)
    return input_name, input_shape, input_layout, input_channels


def _onnx_target_size(input_shape: Any, *, layout: str) -> tuple[int | None, int | None]:
    dims = list(input_shape or [])
    if layout == "nhwc":
        return positive_onnx_dimension(dims[2]), positive_onnx_dimension(dims[1])
    return positive_onnx_dimension(dims[3]), positive_onnx_dimension(dims[2])


def _prepare_onnx_tensor(*, image: Any, layout: str, channels: int) -> Any:
    import numpy as np

    arr = np.asarray(image, dtype=np.float32)
    if layout == "nhwc":
        if channels == 1 and arr.ndim == 2:
            arr = arr[..., None]
        return (arr / 255.0)[None, ...]
    if channels == 1:
        if arr.ndim == 3:
            arr = arr[..., 0]
        return (arr / 255.0)[None, None, ...]
    return np.transpose(arr / 255.0, (2, 0, 1))[None, ...]


def _normalize_onnx_output(output: Any) -> Any:
    import numpy as np

    result = np.asarray(output)
    if result.dtype.kind not in {"u", "i", "f"} or not np.isfinite(result).all():
        raise ValueError("invalid_output_values")
    if result.ndim == 4:
        if result.shape[0] != 1:
            raise ValueError("unsupported_output_batch")
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
    return np.clip(result, 0, 255).astype("uint8")


def _save_cleaned_output(*, result: Any, output_path: Path, original_size: tuple[int, int]) -> None:
    from PIL import Image

    with ExitStack() as images:
        cleaned = images.enter_context(closing(Image.fromarray(result, mode="L" if result.ndim == 2 else "RGB")))
        if cleaned.size != original_size:
            cleaned = images.enter_context(closing(cleaned.resize(original_size)))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned.save(output_path)


def _run_local_onnx_cleanup(*, input_path: Path, output_path: Path, session: InferenceSession) -> bool:
    from PIL import Image

    if input_path.suffix.lower() not in _RASTER_EXTS:
        raise ValueError("unsupported_input_type")

    input_name, input_shape, input_layout, input_channels = _onnx_input_spec(session)
    target_width, target_height = _onnx_target_size(input_shape, layout=input_layout)

    with ExitStack() as images:
        image = images.enter_context(closing(Image.open(input_path)))
        source = images.enter_context(closing(image.convert("L" if input_channels == 1 else "RGB")))
        original_size = source.size
        prepared = source
        if target_width and target_height and (target_width, target_height) != original_size:
            prepared = images.enter_context(closing(source.resize((target_width, target_height))))
        tensor = _prepare_onnx_tensor(image=prepared, layout=input_layout, channels=input_channels)

    outputs = session.run(None, {input_name: tensor})
    if not outputs:
        raise ValueError("empty_output")

    result = _normalize_onnx_output(outputs[0])
    _save_cleaned_output(result=result, output_path=output_path, original_size=original_size)

    return output_path.read_bytes() != input_path.read_bytes()


def _resolve_cleanup_backend(*, backend: str, input_path: Path, model_path: str, api_url: str) -> str:
    normalized_backend = backend.strip().lower()
    if normalized_backend != "auto":
        return normalized_backend
    if api_url:
        return "http"
    if model_path:
        return "local"
    if input_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
        return "heuristic"
    return "skip"


def _run_heuristic_cleanup(
    *, input_path: Path, output_path: Path, info: dict[str, Any]
) -> tuple[bool, str, dict[str, Any]]:
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps

        with ExitStack() as images:
            image = images.enter_context(closing(Image.open(input_path)))
            gray = images.enter_context(closing(ImageOps.grayscale(image)))
            contrasted = images.enter_context(closing(ImageOps.autocontrast(gray)))
            enhanced = images.enter_context(closing(ImageEnhance.Contrast(contrasted).enhance(1.25)))
            cleaned = images.enter_context(closing(enhanced.filter(ImageFilter.SHARPEN)))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            cleaned.save(output_path)
        changed = output_path.read_bytes() != input_path.read_bytes()
    except Exception as exc:  # noqa: BLE001
        return False, f"heuristic_failed:{exc.__class__.__name__}", info
    return changed, "cleanup_ok" if changed else "cleanup_no_change", info


def _run_local_cleanup(
    *,
    input_path: Path,
    output_path: Path,
    model_path: str,
    info: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    model_ref = model_path.strip()
    if not model_ref:
        return False, "missing_model_path", info
    try:
        loaded = get_preprocess_model_loader().load_onnx(name="handwriting_cleanup", model_path=model_ref)
        info["model_backend"] = loaded.backend
        info["model_name"] = loaded.name
    except Exception as exc:  # noqa: BLE001
        return False, f"model_unavailable:{exc.__class__.__name__}", info
    try:
        changed = _run_local_onnx_cleanup(input_path=input_path, output_path=output_path, session=loaded.handle)
    except ValueError as exc:
        return False, f"onnx_{exc}", info
    except Exception as exc:  # noqa: BLE001
        return False, f"onnx_failed:{exc.__class__.__name__}", info
    return changed, "cleanup_ok" if changed else "cleanup_no_change", info


def _run_http_cleanup(
    *,
    input_path: Path,
    output_path: Path,
    api_url: str,
    timeout_sec: float,
    info: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    target_url = api_url.strip()
    if not target_url:
        return False, "missing_api_url", info
    return _run_coroutine_sync(
        lambda: _cleanup_handwriting_via_http_async(
            input_path=input_path,
            output_path=output_path,
            target_url=target_url,
            timeout_sec=timeout_sec,
            info=info,
        )
    )


def cleanup_handwriting_document(
    *,
    input_path: Path,
    output_path: Path,
    backend: str,
    model_path: str = "",
    api_url: str = "",
    timeout_sec: float = 60.0,
) -> tuple[bool, str, dict[str, Any]]:
    normalized_backend = _resolve_cleanup_backend(
        backend=backend,
        input_path=input_path,
        model_path=model_path.strip(),
        api_url=api_url.strip(),
    )
    info: dict[str, Any] = {"backend": normalized_backend}

    if normalized_backend == "skip":
        return False, "skipped", info

    if normalized_backend == "heuristic":
        return _run_heuristic_cleanup(input_path=input_path, output_path=output_path, info=info)

    if normalized_backend in {"local", "onnx"}:
        return _run_local_cleanup(
            input_path=input_path,
            output_path=output_path,
            model_path=model_path,
            info=info,
        )

    if normalized_backend != "http":
        return False, "unsupported_backend", info

    return _run_http_cleanup(
        input_path=input_path,
        output_path=output_path,
        api_url=api_url,
        timeout_sec=timeout_sec,
        info=info,
    )


__all__ = ["cleanup_handwriting_document"]
