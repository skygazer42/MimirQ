from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from PIL import Image as PILImage

_FORMULA_TEXT_RE = re.compile(r"(\\[a-zA-Z]+|[=∑√∞≈≤≥]|\$[^$]+\$)")
_CHART_TEXT_RE = re.compile(
    r"\b(chart|plot|graph|trend|bar|line|pie)\b|图表|趋势图|柱状图|折线图|饼图|曲线图",
    re.IGNORECASE,
)


def _region_from_element(element: Mapping[str, Any], *, region_type: str) -> dict[str, Any]:
    return {
        "region_type": region_type,
        "source_element_id": str(element.get("id") or element.get("source_element_id") or ""),
        "kind": str(element.get("kind") or ""),
        "text": str(element.get("text") or "")[:500],
        "page": element.get("page"),
        "bbox": dict(element.get("bbox") or {}) if isinstance(element.get("bbox"), Mapping) else None,
    }


def detect_formula_regions(elements: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    regions: list[dict[str, Any]] = []
    for element in elements or []:
        kind = str(element.get("kind") or "").lower()
        text = str(element.get("text") or "")
        if kind in {"equation", "formula"} or _FORMULA_TEXT_RE.search(text):
            regions.append(_region_from_element(element, region_type="formula"))
    return {"schema": "mimirq.formula_regions.v1", "count": len(regions), "regions": regions}


def detect_chart_regions(elements: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    regions: list[dict[str, Any]] = []
    for element in elements or []:
        kind = str(element.get("kind") or "").lower()
        text = str(element.get("text") or "")
        attrs = element.get("attributes") if isinstance(element.get("attributes"), Mapping) else {}
        hint = f"{text} {attrs.get('caption_text') or ''} {attrs.get('source_content_type') or ''}"
        if kind in {"chart", "plot"} or (kind in {"image", "figure"} and _CHART_TEXT_RE.search(hint)):
            regions.append(_region_from_element(element, region_type="chart"))
    return {"schema": "mimirq.chart_regions.v1", "count": len(regions), "regions": regions}


def _dominant_line_angle(image: PILImage.Image) -> float:
    try:
        import cv2  # type: ignore
        import numpy as np

        gray = np.asarray(image.convert("L"), dtype="uint8")
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, math.pi / 180.0, threshold=20, minLineLength=20, maxLineGap=4)
        if lines is None:
            return 0.0
        weighted: list[tuple[float, float]] = []
        for raw in lines[:200]:
            x1, y1, x2, y2 = [float(v) for v in raw[0]]
            dx = x2 - x1
            dy = y2 - y1
            length = math.hypot(dx, dy)
            if length <= 0:
                continue
            angle = math.degrees(math.atan2(dy, dx))
            while angle <= -90:
                angle += 180
            while angle > 90:
                angle -= 180
            weighted.append((angle, length))
        if not weighted:
            return 0.0
        total = sum(length for _angle, length in weighted)
        return sum(angle * length for angle, length in weighted) / max(1.0, total)
    except Exception:
        return 0.0


def _orientation_angle_from_textline(angle: float) -> int:
    abs_angle = abs(float(angle))
    if abs_angle >= 67.5:
        return 90 if angle > 0 else 270
    if abs_angle <= 22.5:
        return 0
    return 0


def profile_document_image(image: PILImage.Image) -> dict[str, Any]:
    width, height = image.size
    textline_angle = _dominant_line_angle(image)
    skew = 0.0 if abs(textline_angle) > 45 else float(textline_angle)
    orientation_angle = _orientation_angle_from_textline(textline_angle)
    perspective_risk = False
    if width > 0 and height > 0:
        ratio = max(width, height) / max(1, min(width, height))
        perspective_risk = bool(ratio > 3.5)
    return {
        "schema": "mimirq.document_image_profile.v1",
        "orientation": {
            "angle": int(orientation_angle),
            "confidence": 0.7 if orientation_angle else 0.55,
        },
        "textline_orientation": {
            "angle": int(_orientation_angle_from_textline(textline_angle)),
            "skew_degrees": round(float(skew), 3),
        },
        "unwarp": {
            "needed": bool(perspective_risk or abs(skew) > 8.0),
            "reason": "perspective_or_skew" if (perspective_risk or abs(skew) > 8.0) else "not_needed",
        },
    }


def profile_document_image_with_models(
    image: PILImage.Image,
    *,
    runtime: Any | None = None,
    run_unwarp: bool = True,
) -> dict[str, Any]:
    profile = profile_document_image(image)
    profile["models"] = {}
    try:
        from app.parsing.models.paddleocr_preprocess_onnx import predict_document_orientation

        orientation = predict_document_orientation(image, runtime=runtime)
        profile["orientation"] = {
            "angle": int(orientation.angle),
            "confidence": round(float(orientation.confidence), 6),
            "source": "onnx",
        }
        profile["models"]["document_orientation"] = orientation.to_metadata()
    except Exception as exc:
        profile["models"]["document_orientation"] = {
            "available": False,
            "reason": f"prediction_failed:{str(exc)[:160]}",
        }

    try:
        from app.parsing.models.paddleocr_preprocess_onnx import predict_textline_orientation

        textline = predict_textline_orientation(image, runtime=runtime)
        profile["textline_orientation"]["angle"] = int(textline.angle)
        profile["textline_orientation"]["confidence"] = round(float(textline.confidence), 6)
        profile["textline_orientation"]["source"] = "onnx"
        profile["models"]["textline_orientation"] = textline.to_metadata()
    except Exception as exc:
        profile["models"]["textline_orientation"] = {
            "available": False,
            "reason": f"prediction_failed:{str(exc)[:160]}",
        }

    if not run_unwarp:
        profile["models"]["document_rectification"] = {"applied": False, "reason": "disabled"}
        return profile

    if not bool(profile.get("unwarp", {}).get("needed")):
        profile["models"]["document_rectification"] = {"applied": False, "reason": "not_needed"}
        return profile

    try:
        from app.parsing.models.paddleocr_preprocess_onnx import predict_document_unwarp

        unwarp = predict_document_unwarp(image, runtime=runtime)
        profile["unwarp"]["source"] = "onnx"
        profile["unwarp"]["output_size"] = {
            "width": int(unwarp.output_size[0]),
            "height": int(unwarp.output_size[1]),
        }
        profile["models"]["document_rectification"] = unwarp.to_metadata()
    except Exception as exc:
        profile["models"]["document_rectification"] = {
            "applied": False,
            "reason": f"prediction_failed:{str(exc)[:160]}",
        }
    return profile


__all__ = [
    "detect_chart_regions",
    "detect_formula_regions",
    "profile_document_image",
    "profile_document_image_with_models",
]
