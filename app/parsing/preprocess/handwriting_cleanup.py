"""
Handwriting/noise cleanup helpers for preprocessing.

This stage is feature-flagged and best-effort:
- local backend: validate model availability so the pipeline can surface clear warnings
- http backend: forward the file to a remote cleanup service and store returned bytes
"""


from pathlib import Path
from typing import Any

import httpx

from app.core.async_bridge import run_coroutine_sync as _run_coroutine_sync
from app.parsing.preprocess.model_loader import get_preprocess_model_loader

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
        file_bytes = input_path.read_bytes()
        timeout = float(timeout_sec)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                target_url,
                files={"file": (input_path.name, file_bytes, "application/octet-stream")},
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


def _onnx_input_spec(session: Any) -> tuple[str, Any, str, int]:
    inputs = list(session.get_inputs() or [])
    input_name = str(getattr(inputs[0], "name", "") or "input")
    input_shape = getattr(inputs[0], "shape", None) if inputs else None
    input_layout = _infer_onnx_layout(input_shape)
    input_channels = _infer_onnx_channels(input_shape, layout=input_layout)
    return input_name, input_shape, input_layout, input_channels


def _onnx_target_size(input_shape: Any, *, layout: str) -> tuple[int | None, int | None]:
    dims = list(input_shape or [])
    if len(dims) != 4:
        return None, None
    if layout == "nhwc":
        return _positive_int(dims[2]), _positive_int(dims[1])
    return _positive_int(dims[3]), _positive_int(dims[2])


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
    return np.clip(result, 0, 255).astype("uint8")


def _save_cleaned_output(*, result: Any, output_path: Path, original_size: tuple[int, int]) -> None:
    from PIL import Image

    cleaned = Image.fromarray(result, mode="L" if result.ndim == 2 else "RGB")
    if cleaned.size != original_size:
        cleaned = cleaned.resize(original_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned.save(output_path)


def _run_local_onnx_cleanup(*, input_path: Path, output_path: Path, session: Any) -> bool:
    from PIL import Image

    if input_path.suffix.lower() not in _RASTER_EXTS:
        raise ValueError("unsupported_input_type")

    input_name, input_shape, input_layout, input_channels = _onnx_input_spec(session)
    target_width, target_height = _onnx_target_size(input_shape, layout=input_layout)

    with Image.open(input_path) as image:
        source = image.convert("L" if input_channels == 1 else "RGB")
        original_size = source.size
        prepared = source
        if target_width and target_height and (target_width, target_height) != original_size:
            prepared = source.resize((target_width, target_height))
        tensor = _prepare_onnx_tensor(image=prepared, layout=input_layout, channels=input_channels)

    outputs = list(session.run(None, {input_name: tensor}) or [])
    if not outputs:
        raise ValueError("empty_output")

    result = _normalize_onnx_output(outputs[0])
    _save_cleaned_output(result=result, output_path=output_path, original_size=original_size)

    try:
        return output_path.read_bytes() != input_path.read_bytes()
    except Exception:
        return True


def _resolve_cleanup_backend(*, backend: str, input_path: Path, model_path: str, api_url: str) -> str:
    normalized_backend = str(backend or "auto").strip().lower() or "auto"
    if normalized_backend != "auto":
        return normalized_backend
    if api_url:
        return "http"
    if model_path:
        return "local"
    if input_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
        return "heuristic"
    return "skip"


def _run_heuristic_cleanup(*, input_path: Path, output_path: Path, info: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
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


def _run_local_cleanup(
    *,
    input_path: Path,
    output_path: Path,
    model_path: str,
    info: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
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


def _run_http_cleanup(
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
        model_path=str(model_path or "").strip(),
        api_url=str(api_url or "").strip(),
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
