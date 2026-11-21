import logging
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from math import isfinite
from typing import Any

from PIL import Image as PILImage

from app.rag.ingestion.parsing.enrich.table_cell_schema import TableCell, TableExtraction
from app.rag.ingestion.parsing.utils.scalars import coerce_float


class TableImageBackendError(RuntimeError):
    """An expected optional table OCR dependency/model/inference failure."""


class TableImageModelUnavailableError(TableImageBackendError):
    """The explicitly selected local table OCR backend is unavailable."""


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
    if value is None:
        return 0.0
    if isinstance(value, bool):
        raise ValueError("Table OCR confidence must be a finite number")
    score = float(value)
    if not isfinite(score):
        raise ValueError("Table OCR confidence must be a finite number")
    if score < 0:
        return 0.0
    if score > 1:
        return 1.0
    return score


class _TableOcrBackend:
    """One selected OCR engine reused within a table operation."""

    def __init__(self) -> None:
        kwargs = _project_rapidocr_kwargs()
        try:
            from onnxruntime.capi.onnxruntime_pybind11_state import (
                EngineError,
                EPFail,
                Fail,
                InvalidArgument,
                InvalidGraph,
                InvalidProtobuf,
                NoModel,
                NoSuchFile,
                NotFound,
                RuntimeException,
            )
            from onnxruntime.capi.onnxruntime_pybind11_state import NotImplemented as OrtNotImplemented
            from rapidocr_onnxruntime import LoadImageError, RapidOCR  # type: ignore
            from rapidocr_onnxruntime.ch_ppocr_det.utils import ResizeImgError as DetectionResizeError
            from rapidocr_onnxruntime.utils.infer_engine import ONNXRuntimeError
            from rapidocr_onnxruntime.utils.process_img import ResizeImgError as ProcessingResizeError
        except ImportError as exc:
            raise TableImageModelUnavailableError("The selected table OCR dependency is unavailable") from exc
        self._backend_errors = (
            OSError,
            EPFail,
            EngineError,
            Fail,
            InvalidArgument,
            InvalidGraph,
            InvalidProtobuf,
            NoModel,
            NoSuchFile,
            NotFound,
            OrtNotImplemented,
            RuntimeException,
            LoadImageError,
            DetectionResizeError,
            ProcessingResizeError,
            ONNXRuntimeError,
        )
        try:
            self._engine = RapidOCR(**kwargs)
        except self._backend_errors as exc:
            raise TableImageBackendError(f"The selected table OCR engine could not load: {str(exc)[:300]}") from exc

    def __call__(self, image: PILImage.Image) -> Any:
        import numpy as np

        with closing(image.convert("RGB")) as converted:
            pixels = np.asarray(converted)
            try:
                output = self._engine(pixels)
            except self._backend_errors as exc:
                raise TableImageBackendError(f"The selected table OCR inference failed: {str(exc)[:300]}") from exc
        result, _elapsed = output
        return result


def _rapidocr_confidence(image: PILImage.Image, *, backend: _TableOcrBackend | None = None) -> float:
    reader = _TableOcrBackend() if backend is None else backend
    result = reader(image)

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


def _project_rapidocr_kwargs() -> dict[str, str]:
    from app.rag.ingestion.parsing.models.runtime import SmallModelRuntime

    runtime = SmallModelRuntime()
    det = runtime.resolve("ocr_detection", model_id="monkt_paddleocr_v5_det_onnx", allow_download=False)
    rec = runtime.resolve("ocr_recognition", model_id="monkt_paddleocr_chinese_rec_onnx", allow_download=False)
    missing = [
        f"{status.task}.{status.model_id}: {status.reason}"
        for status in (det, rec)
        if not status.available or status.path is None
    ]
    if missing:
        raise TableImageModelUnavailableError("Selected table OCR models unavailable: " + "; ".join(missing))
    rec_spec = runtime.manifest.get("ocr_recognition", model_id="monkt_paddleocr_chinese_rec_onnx")
    kwargs = {
        "det_model_path": str(det.path),
        "rec_model_path": str(rec.path),
    }
    rec_keys_path = rec_spec.metadata.get("rec_keys_path")
    if rec_keys_path is not None:
        if not isinstance(rec_keys_path, str):
            raise TypeError("Selected table OCR rec_keys_path must be a string")
        if rec_keys_path:
            kwargs["rec_keys_path"] = rec_keys_path
    return kwargs


def select_table_rotation(
    image: PILImage.Image,
    *,
    confidence_scorer: Callable[[PILImage.Image], float] | None = None,
    angles: Sequence[int] = (0, 90, 180, 270),
) -> TableRotationResult:
    if not angles:
        return TableRotationResult(angle=0, confidence=0.0, candidates={})
    if confidence_scorer is None:
        backend = _TableOcrBackend()

        def scorer(candidate: PILImage.Image) -> float:
            return _rapidocr_confidence(candidate, backend=backend)
    else:
        scorer = confidence_scorer
    candidates: dict[int, float] = {}
    for raw_angle in angles:
        angle = int(raw_angle) % 360
        if angle == 0:
            candidates[angle] = _coerce_score(scorer(image))
        else:
            with closing(image.rotate(-angle, expand=True)) as rotated:
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

    with closing(image.convert("L")) as converted:
        gray = np.asarray(converted, dtype="uint8")
    dark = gray < 90
    height, width = dark.shape[:2]
    vertical_indices = [i for i, value in enumerate(dark.mean(axis=0)) if float(value) >= 0.45]
    horizontal_indices = [i for i, value in enumerate(dark.mean(axis=1)) if float(value) >= 0.45]
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
    left = coerce_float(raw.get("left", raw.get("x0")))
    top = coerce_float(raw.get("top", raw.get("y0")))
    right = coerce_float(raw.get("right", raw.get("x1")))
    bottom = coerce_float(raw.get("bottom", raw.get("y1")))
    if left is None or top is None or right is None or bottom is None:
        return None
    return left, top, right, bottom


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
            rows[row_index][col_index] = cell.text
    return rows


def _bind_ocr_content(
    *,
    cell_boxes: dict[tuple[int, int], tuple[float, float, float, float] | None],
    ocr_lines: Sequence[Mapping[str, Any]],
    min_overlap: float,
) -> tuple[dict[tuple[int, int], list[str]], dict[tuple[int, int], list[float]]]:
    text_by_cell: dict[tuple[int, int], list[str]] = {}
    confidence_by_cell: dict[tuple[int, int], list[float]] = {}
    for line in ocr_lines:
        raw_text = line.get("text")
        text = "" if raw_text is None else str(raw_text).strip()
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
        if best_key is None or best_ratio < min_overlap:
            continue
        text_by_cell.setdefault(best_key, []).append(text)
        confidence = line.get("confidence")
        if confidence is None:
            confidence = line.get("score")
        confidence_by_cell.setdefault(best_key, []).append(_coerce_score(confidence))
    return text_by_cell, confidence_by_cell


def _average_bound_confidence(confidence_by_cell: dict[tuple[int, int], list[float]]) -> float | None:
    if not confidence_by_cell:
        return None
    total = sum(score for scores in confidence_by_cell.values() for score in scores)
    count = sum(len(scores) for scores in confidence_by_cell.values())
    return round(total / max(1, count), 6)


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

    text_by_cell, confidence_by_cell = _bind_ocr_content(
        cell_boxes=cell_boxes,
        ocr_lines=ocr_lines,
        min_overlap=float(min_overlap),
    )

    next_cells: list[TableCell] = []
    bound_cells = 0
    for cell in table.cells:
        key = _cell_key(cell)
        bound_text = " ".join(text_by_cell.get(key, [])).strip()
        if bound_text and not cell.text.strip():
            bound_cells += 1
            next_cells.append(replace(cell, text=bound_text))
        else:
            next_cells.append(cell)

    row_count = max(table.row_count, max((cell.row_index for cell in next_cells), default=0))
    next_rows = _rows_from_cells(cells=next_cells, row_count=row_count, col_count=table.col_count)
    metadata = dict(table.metadata)
    metadata["cell_ocr_binding"] = {
        "applied": bool(bound_cells),
        "bound_cells": bound_cells,
        "ocr_lines": len(ocr_lines),
        "avg_confidence": _average_bound_confidence(confidence_by_cell),
    }
    next_table = replace(
        table,
        columns=list(table.columns),
        rows=next_rows,
        cells=next_cells,
        metadata=metadata,
    )
    return CellOcrBindingResult(table=next_table, bound_cells=bound_cells, metadata=metadata["cell_ocr_binding"])


def _coerce_ocr_line(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    points = raw[0]
    payload = raw[1]
    if not isinstance(points, (list, tuple)) or not points:
        return None

    xy: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            xy.append((float(point[0]), float(point[1])))
        except (OverflowError, TypeError, ValueError):
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
    if not xy:
        return None

    if isinstance(payload, (list, tuple)):
        value = payload[0] if payload else None
        score = payload[1] if len(payload) >= 2 else None
    else:
        value = payload
        score = raw[2] if len(raw) >= 3 else None
    text = "" if value is None else str(value).strip()
    if not text:
        return None

    xs = [x for x, _y in xy]
    ys = [y for _x, y in xy]
    return {
        "text": text,
        "confidence": _coerce_score(score),
        "bbox": {"left": min(xs), "top": min(ys), "right": max(xs), "bottom": max(ys)},
    }


def extract_ocr_lines_from_image(image: PILImage.Image, *, max_lines: int = 300) -> list[dict[str, Any]]:
    limit = max(0, int(max_lines))
    if limit == 0:
        return []
    result = _TableOcrBackend()(image)

    lines: list[dict[str, Any]] = []
    for raw in result or []:
        line = _coerce_ocr_line(raw)
        if line is None:
            continue
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def table_cells_with_uniform_bboxes(table: TableExtraction, *, image_size: tuple[int, int]) -> TableExtraction:
    width, height = image_size
    col_count = max(1, table.col_count)
    row_count = max(1, table.row_count + table.header_rows)
    next_cells: list[TableCell] = []
    for cell in table.cells:
        if cell.bbox is not None:
            next_cells.append(cell)
            continue
        left = (float(cell.col_index) / col_count) * width
        right = (float(cell.col_index + max(1, cell.col_span)) / col_count) * width
        row_index = cell.row_index if table.header_rows else cell.row_index - 1
        top = (float(row_index) / row_count) * height
        bottom = (float(row_index + max(1, cell.row_span)) / row_count) * height
        next_cells.append(
            replace(
                cell,
                bbox={"left": left, "top": top, "right": right, "bottom": bottom},
            )
        )
    return replace(
        table,
        columns=list(table.columns),
        rows=[list(row) for row in table.rows],
        cells=next_cells,
        metadata=dict(table.metadata),
    )


__all__ = [
    "CellOcrBindingResult",
    "TableGridTypeResult",
    "TableImageBackendError",
    "TableImageModelUnavailableError",
    "TableRotationResult",
    "bind_ocr_lines_to_table_cells",
    "classify_table_grid_type",
    "extract_ocr_lines_from_image",
    "select_table_rotation",
    "table_cells_with_uniform_bboxes",
]
