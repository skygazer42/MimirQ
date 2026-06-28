from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PIL import Image as PILImage

from app.parsing.enrich.table_cell_schema import TableCell, TableExtraction
from app.rag.core.logging import get_logger


@dataclass(frozen=True, slots=True)
class TableRotationResult:
    angle: int
    confidence: float
    candidates: dict[int, float]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "angle": int(self.angle),
            "confidence": round(float(self.confidence), 6),
            "candidates": {str(k): round(float(v), 6) for k, v in self.candidates.items()},
        }


@dataclass(frozen=True, slots=True)
class TableGridTypeResult:
    table_type: str
    vertical_lines: int
    horizontal_lines: int
    line_density: float

    def to_metadata(self) -> dict[str, Any]:
        return {
            "table_type": self.table_type,
            "vertical_lines": int(self.vertical_lines),
            "horizontal_lines": int(self.horizontal_lines),
            "line_density": round(float(self.line_density), 6),
        }


@dataclass(frozen=True, slots=True)
class CellOcrBindingResult:
    table: TableExtraction
    bound_cells: int
    metadata: dict[str, Any]


def _coerce_score(value: Any) -> float:
    try:
        score = float(value)
    except Exception:
        return 0.0
    if score < 0:
        return 0.0
    if score > 1:
        return 1.0
    return score


def _rapidocr_confidence(image: PILImage.Image) -> float:
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
    except Exception:
        return 0.0

    try:
        import numpy as np

        engine = RapidOCR(**_project_rapidocr_kwargs())
        result, _ = engine(np.asarray(image.convert("RGB")))
    except Exception:
        return 0.0

    scores: list[float] = []
    for line in result or []:
        if not isinstance(line, (list, tuple)) or len(line) < 2:
            continue
        payload = line[1]
        score = None
        if isinstance(payload, (list, tuple)) and len(payload) >= 2:
            score = payload[1]
        elif len(line) >= 3:
            score = line[2]
        score_f = _coerce_score(score)
        if score_f > 0:
            scores.append(score_f)
    return (sum(scores) / len(scores)) if scores else 0.0


def _manifest_metadata_path(metadata: Mapping[str, Any] | None, key: str) -> str | None:
    if not isinstance(metadata, Mapping):
        return None
    nested = metadata.get("metadata")
    if isinstance(nested, Mapping) and nested.get(key) is not None:
        return str(nested.get(key))
    if metadata.get(key) is not None:
        return str(metadata.get(key))
    return None


def _project_rapidocr_kwargs() -> dict[str, str]:
    try:
        from app.parsing.models.runtime import SmallModelRuntime

        runtime = SmallModelRuntime()
        det = runtime.resolve("ocr_detection", model_id="monkt_paddleocr_v5_det_onnx", allow_download=False)
        rec = runtime.resolve("ocr_recognition", model_id="monkt_paddleocr_chinese_rec_onnx", allow_download=False)
        rec_spec = runtime.manifest.get("ocr_recognition", model_id="monkt_paddleocr_chinese_rec_onnx")
        if not (det.available and rec.available and det.path and rec.path):
            return {}
        kwargs = {
            "det_model_path": str(det.path),
            "rec_model_path": str(rec.path),
        }
        rec_keys_path = _manifest_metadata_path({"metadata": dict(rec_spec.metadata or {})}, "rec_keys_path")
        if rec_keys_path:
            kwargs["rec_keys_path"] = rec_keys_path
        return kwargs
    except Exception:
        return {}


def select_table_rotation(
    image: PILImage.Image,
    *,
    confidence_scorer: Callable[[PILImage.Image], float] | None = None,
    angles: Sequence[int] = (0, 90, 180, 270),
) -> TableRotationResult:
    scorer = confidence_scorer or _rapidocr_confidence
    candidates: dict[int, float] = {}
    for raw_angle in angles:
        angle = int(raw_angle) % 360
        rotated = image if angle == 0 else image.rotate(-angle, expand=True)
        candidates[angle] = _coerce_score(scorer(rotated))

    best_angle = 0
    best_score = -1.0
    for angle in (0, 90, 180, 270):
        if angle not in candidates:
            continue
        score = candidates[angle]
        if score > best_score:
            best_angle = angle
            best_score = score
    return TableRotationResult(angle=best_angle, confidence=max(0.0, best_score), candidates=candidates)


def _line_groups(indices: list[int], *, gap: int = 2) -> int:
    if not indices:
        return 0
    groups = 1
    prev = indices[0]
    for idx in indices[1:]:
        if idx - prev > gap:
            groups += 1
        prev = idx
    return groups


def classify_table_grid_type(image: PILImage.Image) -> TableGridTypeResult:
    import numpy as np

    gray = np.asarray(image.convert("L"), dtype="uint8")
    dark = gray < 90
    height, width = dark.shape[:2]
    vertical_indices = [int(i) for i, value in enumerate(dark.mean(axis=0)) if float(value) >= 0.45]
    horizontal_indices = [int(i) for i, value in enumerate(dark.mean(axis=1)) if float(value) >= 0.45]
    vertical_lines = _line_groups(vertical_indices)
    horizontal_lines = _line_groups(horizontal_indices)
    density = float(dark.mean()) if dark.size else 0.0
    table_type = "wired" if vertical_lines >= 3 and horizontal_lines >= 3 else "wireless"
    if width <= 0 or height <= 0:
        table_type = "unknown"
    return TableGridTypeResult(
        table_type=table_type,
        vertical_lines=vertical_lines,
        horizontal_lines=horizontal_lines,
        line_density=density,
    )


def _bbox(raw: Mapping[str, Any] | None) -> tuple[float, float, float, float] | None:
    if not isinstance(raw, Mapping):
        return None
    left = raw.get("left", raw.get("x0"))
    top = raw.get("top", raw.get("y0"))
    right = raw.get("right", raw.get("x1"))
    bottom = raw.get("bottom", raw.get("y1"))
    try:
        return float(left), float(top), float(right), float(bottom)
    except Exception:
        return None


def _overlap_area(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    return max(0.0, right - left) * max(0.0, bottom - top)


def _area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _cell_key(cell: TableCell) -> tuple[int, int]:
    return int(cell.row_index), int(cell.col_index)


def _rows_from_cells(*, cells: list[TableCell], row_count: int, col_count: int) -> list[list[str]]:
    rows = [["" for _ in range(col_count)] for _ in range(row_count)]
    for cell in cells:
        if cell.row_index <= 0:
            continue
        row_index = int(cell.row_index) - 1
        col_index = int(cell.col_index)
        if 0 <= row_index < row_count and 0 <= col_index < col_count:
            rows[row_index][col_index] = str(cell.text or "")
    return rows


def bind_ocr_lines_to_table_cells(
    table: TableExtraction,
    ocr_lines: Sequence[Mapping[str, Any]],
    *,
    min_overlap: float = 0.2,
) -> CellOcrBindingResult:
    cell_boxes = {_cell_key(cell): _bbox(cell.bbox) for cell in table.cells}
    if not any(box is not None for box in cell_boxes.values()):
        return CellOcrBindingResult(
            table=table,
            bound_cells=0,
            metadata={"applied": False, "reason": "missing_cell_bboxes", "bound_cells": 0},
        )

    text_by_cell: dict[tuple[int, int], list[str]] = {}
    confidence_by_cell: dict[tuple[int, int], list[float]] = {}
    for line in ocr_lines:
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        line_box = _bbox(line.get("bbox") if isinstance(line.get("bbox"), Mapping) else line)
        if line_box is None:
            continue
        line_area = max(1.0, _area(line_box))
        best_key: tuple[int, int] | None = None
        best_ratio = 0.0
        for key, cell_box in cell_boxes.items():
            if cell_box is None:
                continue
            ratio = _overlap_area(line_box, cell_box) / line_area
            if ratio > best_ratio:
                best_ratio = ratio
                best_key = key
        if best_key is None or best_ratio < float(min_overlap):
            continue
        text_by_cell.setdefault(best_key, []).append(text)
        confidence_by_cell.setdefault(best_key, []).append(_coerce_score(line.get("confidence") or line.get("score")))

    next_cells: list[TableCell] = []
    bound_cells = 0
    for cell in table.cells:
        key = _cell_key(cell)
        bound_text = " ".join(text_by_cell.get(key) or []).strip()
        if bound_text and not str(cell.text or "").strip():
            bound_cells += 1
            next_cells.append(
                TableCell(
                    row_index=cell.row_index,
                    col_index=cell.col_index,
                    text=bound_text,
                    is_header=cell.is_header,
                    row_span=cell.row_span,
                    col_span=cell.col_span,
                    bbox=cell.bbox,
                )
            )
        else:
            next_cells.append(cell)

    row_count = max(table.row_count, max((cell.row_index for cell in next_cells), default=0))
    next_rows = _rows_from_cells(cells=next_cells, row_count=row_count, col_count=table.col_count)
    metadata = dict(table.metadata or {})
    metadata["cell_ocr_binding"] = {
        "applied": bool(bound_cells),
        "bound_cells": int(bound_cells),
        "ocr_lines": len(list(ocr_lines)),
        "avg_confidence": (
            round(
                sum(score for scores in confidence_by_cell.values() for score in scores)
                / max(1, sum(len(scores) for scores in confidence_by_cell.values())),
                6,
            )
            if confidence_by_cell
            else None
        ),
    }
    next_table = TableExtraction(
        columns=list(table.columns),
        rows=next_rows,
        cells=next_cells,
        page=table.page,
        bbox=table.bbox,
        source_element_id=table.source_element_id,
        header_rows=table.header_rows,
        confidence=table.confidence,
        metadata=metadata,
    )
    return CellOcrBindingResult(table=next_table, bound_cells=bound_cells, metadata=metadata["cell_ocr_binding"])


def extract_ocr_lines_from_image(image: PILImage.Image, *, max_lines: int = 300) -> list[dict[str, Any]]:
    try:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
    except Exception:
        return []

    try:
        engine = RapidOCR(**_project_rapidocr_kwargs())
        result, _ = engine(np.asarray(image.convert("RGB")))
    except Exception:
        return []

    lines: list[dict[str, Any]] = []
    for raw in result or []:
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            continue
        points = raw[0]
        payload = raw[1]
        if not isinstance(points, (list, tuple)) or not points:
            continue
        xy: list[tuple[float, float]] = []
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                xy.append((float(point[0]), float(point[1])))
            except Exception:
                get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
        if not xy:
            continue
        text = ""
        score = None
        if isinstance(payload, (list, tuple)):
            text = str(payload[0] or "").strip() if payload else ""
            score = payload[1] if len(payload) >= 2 else None
        else:
            text = str(payload or "").strip()
            score = raw[2] if len(raw) >= 3 else None
        if not text:
            continue
        xs = [x for x, _y in xy]
        ys = [y for _x, y in xy]
        lines.append(
            {
                "text": text,
                "confidence": _coerce_score(score),
                "bbox": {"left": min(xs), "top": min(ys), "right": max(xs), "bottom": max(ys)},
            }
        )
        if len(lines) >= int(max_lines or 300):
            break
    return lines


def table_cells_with_uniform_bboxes(table: TableExtraction, *, image_size: tuple[int, int]) -> TableExtraction:
    width, height = image_size
    col_count = max(1, table.col_count)
    row_count = max(1, table.row_count + int(table.header_rows or 0))
    next_cells: list[TableCell] = []
    for cell in table.cells:
        if cell.bbox is not None:
            next_cells.append(cell)
            continue
        left = (float(cell.col_index) / col_count) * width
        right = (float(cell.col_index + max(1, cell.col_span)) / col_count) * width
        top = (float(cell.row_index) / row_count) * height
        bottom = (float(cell.row_index + max(1, cell.row_span)) / row_count) * height
        next_cells.append(
            TableCell(
                row_index=cell.row_index,
                col_index=cell.col_index,
                text=cell.text,
                is_header=cell.is_header,
                row_span=cell.row_span,
                col_span=cell.col_span,
                bbox={"left": left, "top": top, "right": right, "bottom": bottom},
            )
        )
    return TableExtraction(
        columns=list(table.columns),
        rows=[list(row) for row in table.rows],
        cells=next_cells,
        page=table.page,
        bbox=table.bbox,
        source_element_id=table.source_element_id,
        header_rows=table.header_rows,
        confidence=table.confidence,
        metadata=dict(table.metadata or {}),
    )


__all__ = [
    "CellOcrBindingResult",
    "TableGridTypeResult",
    "TableRotationResult",
    "bind_ocr_lines_to_table_cells",
    "classify_table_grid_type",
    "extract_ocr_lines_from_image",
    "select_table_rotation",
    "table_cells_with_uniform_bboxes",
]
