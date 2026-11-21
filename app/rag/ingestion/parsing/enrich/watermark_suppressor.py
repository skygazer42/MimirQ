from collections.abc import Mapping, Sequence
from contextlib import closing
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
            "changed": self.changed,
            "masked_regions": self.masked_regions,
            "reasons": list(self.reasons),
        }


def _bbox(value: Any, *, width: int, height: int) -> tuple[int, int, int, int] | None:
    raw = value.get("bbox") if isinstance(value, Mapping) else value
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 4:
        return None
    try:
        x0, y0, x1, y1 = [int(round(float(v))) for v in raw]
    except (TypeError, ValueError, OverflowError):
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
    out = image.convert("RGB")
    width, height = out.size
    masked = 0
    reasons: list[str] = []
    try:
        draw = ImageDraw.Draw(out)
        for box in boxes:
            rect = _bbox(box, width=width, height=height)
            if rect is None:
                continue
            draw.rectangle(rect, fill=fill)
            masked += 1
            reason = box.get("reason") if isinstance(box, Mapping) else None
            if reason is not None and str(reason).strip():
                reasons.append(str(reason))
    except BaseException:
        out.close()
        raise
    return WatermarkSuppressResult(image=out, changed=masked > 0, masked_regions=masked, reasons=reasons)


def suppress_watermark_file(
    *,
    input_path: Path,
    output_path: Path,
    boxes: Sequence[Mapping[str, Any]] | Sequence[Sequence[float]],
) -> tuple[bool, dict[str, Any]]:
    with closing(Image.open(input_path)) as image:
        result = suppress_watermark_regions(image, boxes=boxes)
    try:
        if result.changed:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            result.image.save(output_path)
        return result.changed, result.to_metadata()
    finally:
        result.image.close()


__all__ = ["WatermarkSuppressResult", "suppress_watermark_file", "suppress_watermark_regions"]
