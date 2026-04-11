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
        normalized_backend = "http" if str(api_url or "").strip() else "local"
        info["backend"] = normalized_backend

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
        return False, "model_loaded_not_implemented", info

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
