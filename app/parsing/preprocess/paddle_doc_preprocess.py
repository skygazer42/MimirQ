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
    info: dict[str, Any] = {
        "backend": normalized_backend,
        "device": str(device or "cpu"),
        "lang": str(lang or "ch"),
        "use_doc_orientation_classify": bool(use_doc_orientation_classify),
        "use_doc_unwarping": bool(use_doc_unwarping),
        "use_textline_orientation": bool(use_textline_orientation),
    }

    if normalized_backend == "skip":
        return False, "skipped", info

    if input_path.suffix.lower() not in _RASTER_EXTS:
        return False, "unsupported_input_type", info

    try:
        pipeline = get_paddle_doc_preprocessor(
            device=str(device or "cpu"),
            lang=str(lang or "ch"),
            use_doc_orientation_classify=bool(use_doc_orientation_classify),
            use_doc_unwarping=bool(use_doc_unwarping),
            use_textline_orientation=bool(use_textline_orientation),
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"backend_unavailable:{exc.__class__.__name__}", info

    try:
        outputs = list(pipeline.predict(str(input_path)) or [])
    except Exception as exc:  # noqa: BLE001
        return False, f"predict_failed:{exc.__class__.__name__}", info
    if not outputs:
        return False, "empty_output", info

    result = outputs[0]
    payload = _extract_result_json(result)
    preprocessed = _extract_preprocessed_image(result)
    if preprocessed is None:
        return False, "missing_preprocessed_img", info

    angle = payload.get("angle")
    if angle is not None:
        info["angle"] = angle
    model_settings = payload.get("model_settings")
    if isinstance(model_settings, dict):
        for key in ("use_doc_orientation_classify", "use_doc_unwarping", "use_textline_orientation"):
            if key in model_settings:
                info[key] = bool(model_settings.get(key))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    preprocessed.save(output_path)
    try:
        changed = output_path.read_bytes() != input_path.read_bytes()
    except Exception:
        changed = True
    return changed, "paddle_ocr_ok" if changed else "paddle_ocr_no_change", info


__all__ = ["get_paddle_doc_preprocessor", "preprocess_with_paddle_doc"]
