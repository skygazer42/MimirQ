
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


@dataclass(frozen=True, slots=True)
class WatermarkSuppressResult:
    image: Image.Image
    changed: bool
    masked_regions: int
    reasons: list[str] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema": "mimirq.watermark_suppressor.v1",
            "changed": bool(self.changed),
            "masked_regions": int(self.masked_regions),
            "reasons": list(self.reasons),
        }


def _bbox(value: Any, *, width: int, height: int) -> tuple[int, int, int, int] | None:
    raw = value.get("bbox") if isinstance(value, Mapping) else value
    if not isinstance(raw, Sequence) or len(raw) != 4:
        return None
    try:
        x0, y0, x1, y1 = [int(round(float(v))) for v in raw]
    except Exception:
        return None
    x0 = max(0, min(width, x0))
    x1 = max(0, min(width, x1))
    y0 = max(0, min(height, y0))
    y1 = max(0, min(height, y1))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def suppress_watermark_regions(
    image: Image.Image,
    *,
    boxes: Sequence[Mapping[str, Any]] | Sequence[Sequence[float]],
    fill: tuple[int, int, int] = (255, 255, 255),
) -> WatermarkSuppressResult:
    source = image.convert("RGB")
    out = source.copy()
    width, height = out.size
    draw = ImageDraw.Draw(out)
    masked = 0
    reasons: list[str] = []
    for box in boxes or []:
        rect = _bbox(box, width=width, height=height)
        if rect is None:
            continue
        draw.rectangle(rect, fill=fill)
        masked += 1
        if isinstance(box, Mapping) and str(box.get("reason") or "").strip():
            reasons.append(str(box.get("reason")))
    return WatermarkSuppressResult(image=out, changed=masked > 0, masked_regions=masked, reasons=reasons)


def suppress_watermark_file(
    *,
    input_path: Path,
    output_path: Path,
    boxes: Sequence[Mapping[str, Any]] | Sequence[Sequence[float]],
) -> tuple[bool, dict[str, Any]]:
    with Image.open(input_path) as image:
        result = suppress_watermark_regions(image, boxes=boxes)
    if result.changed:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.image.save(output_path)
    return bool(result.changed), result.to_metadata()


__all__ = ["WatermarkSuppressResult", "suppress_watermark_file", "suppress_watermark_regions"]
