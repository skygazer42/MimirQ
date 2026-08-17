"""
PaddleOCR DocPreprocessor integration for raster-image preprocessing.

Current scope:
- Local Python integration via `paddleocr.DocPreprocessor`
- Raster images only
- Best-effort orientation / unwarping before downstream parsing
"""


from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image

_RASTER_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


@lru_cache(maxsize=8)
def get_paddle_doc_preprocessor(
    *,
    device: str,
    lang: str,
    use_doc_orientation_classify: bool,
    use_doc_unwarping: bool,
    use_textline_orientation: bool,
):
    from paddleocr import DocPreprocessor  # type: ignore

    return DocPreprocessor(
        device=str(device or "cpu"),
        lang=str(lang or "ch"),
        use_doc_orientation_classify=bool(use_doc_orientation_classify),
        use_doc_unwarping=bool(use_doc_unwarping),
        use_textline_orientation=bool(use_textline_orientation),
    )


def _extract_preprocessed_image(result: Any) -> Image.Image | None:
    img_payload = getattr(result, "img", None)
    if isinstance(img_payload, dict):
        candidate = img_payload.get("preprocessed_img")
        if isinstance(candidate, Image.Image):
            return candidate
    return None


def _extract_result_json(result: Any) -> dict[str, Any]:
    payload = getattr(result, "json", None)
    return dict(payload) if isinstance(payload, dict) else {}


def _preprocess_info(
    *,
    backend: str,
    device: str,
    lang: str,
    use_doc_orientation_classify: bool,
    use_doc_unwarping: bool,
    use_textline_orientation: bool,
) -> dict[str, Any]:
    return {
        "backend": backend,
        "device": str(device or "cpu"),
        "lang": str(lang or "ch"),
        "use_doc_orientation_classify": bool(use_doc_orientation_classify),
        "use_doc_unwarping": bool(use_doc_unwarping),
        "use_textline_orientation": bool(use_textline_orientation),
    }


def _resolve_preprocessor(
    *,
    device: str,
    lang: str,
    use_doc_orientation_classify: bool,
    use_doc_unwarping: bool,
    use_textline_orientation: bool,
) -> tuple[Any | None, str | None]:
    try:
        pipeline = get_paddle_doc_preprocessor(
            device=str(device or "cpu"),
            lang=str(lang or "ch"),
            use_doc_orientation_classify=bool(use_doc_orientation_classify),
            use_doc_unwarping=bool(use_doc_unwarping),
            use_textline_orientation=bool(use_textline_orientation),
        )
    except Exception as exc:
        return None, f"backend_unavailable:{exc.__class__.__name__}"
    return pipeline, None


def _predict_first_result(pipeline: Any, input_path: Path) -> tuple[Any | None, str | None]:
    try:
        outputs = list(pipeline.predict(str(input_path)) or [])
    except Exception as exc:
        return None, f"predict_failed:{exc.__class__.__name__}"
    if not outputs:
        return None, "empty_output"
    return outputs[0], None


def _update_info_from_payload(info: dict[str, Any], payload: dict[str, Any]) -> None:
    angle = payload.get("angle")
    if angle is not None:
        info["angle"] = angle
    model_settings = payload.get("model_settings")
    if isinstance(model_settings, dict):
        for key in ("use_doc_orientation_classify", "use_doc_unwarping", "use_textline_orientation"):
            if key in model_settings:
                info[key] = bool(model_settings.get(key))


def preprocess_with_paddle_doc(
    *,
    input_path: Path,
    output_path: Path,
    backend: str,
    device: str = "cpu",
    lang: str = "ch",
    use_doc_orientation_classify: bool = True,
    use_doc_unwarping: bool = True,
    use_textline_orientation: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    normalized_backend = str(backend or "local").strip().lower() or "local"
    info = _preprocess_info(
        backend=normalized_backend,
        device=device,
        lang=lang,
        use_doc_orientation_classify=use_doc_orientation_classify,
        use_doc_unwarping=use_doc_unwarping,
        use_textline_orientation=use_textline_orientation,
    )
    if normalized_backend == "skip":
        return False, "skipped", info
    if input_path.suffix.lower() not in _RASTER_EXTS:
        return False, "unsupported_input_type", info
    pipeline, error = _resolve_preprocessor(
        device=device,
        lang=lang,
        use_doc_orientation_classify=use_doc_orientation_classify,
        use_doc_unwarping=use_doc_unwarping,
        use_textline_orientation=use_textline_orientation,
    )
    if error is not None or pipeline is None:
        return False, error or "backend_unavailable", info
    result, error = _predict_first_result(pipeline, input_path)
    if error is not None or result is None:
        return False, error or "empty_output", info
    payload = _extract_result_json(result)
    preprocessed = _extract_preprocessed_image(result)
    if preprocessed is None:
        return False, "missing_preprocessed_img", info
    _update_info_from_payload(info, payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    preprocessed.save(output_path)
    try:
        changed = output_path.read_bytes() != input_path.read_bytes()
    except Exception:
        changed = True
    return changed, "paddle_ocr_ok" if changed else "paddle_ocr_no_change", info


__all__ = ["get_paddle_doc_preprocessor", "preprocess_with_paddle_doc"]
