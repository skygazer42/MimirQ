
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.parsing.enrich.table_cell_schema import TableCell, TableExtraction


@dataclass(frozen=True, slots=True)
class TableStructureDetection:
    label: str
    score: float
    bbox: Mapping[str, Any] | None = None

    def to_metadata(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "label": str(self.label or ""),
            "score": round(float(self.score), 6),
        }
        if isinstance(self.bbox, Mapping):
            out["bbox"] = dict(self.bbox)
        return out


def _normalize_rows(rows: Sequence[Sequence[Any]] | None, col_count: int) -> list[list[str]]:
    out: list[list[str]] = []
    for raw in rows or []:
        row = [str(cell or "").strip() for cell in list(raw)[:col_count]]
        row += [""] * max(0, int(col_count) - len(row))
        if any(row):
            out.append(row)
    return out


def _mean_score(detections: Sequence[TableStructureDetection] | None) -> float | None:
    scores = [float(item.score) for item in (detections or [])]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 6)


def _bbox_xyxy(raw: Mapping[str, Any] | None, *, image_size: tuple[int, int]) -> dict[str, float] | None:
    if not isinstance(raw, Mapping):
        return None
    width, height = image_size
    left = raw.get("left", raw.get("x0"))
    top = raw.get("top", raw.get("y0"))
    right = raw.get("right", raw.get("x1"))
    bottom = raw.get("bottom", raw.get("y1"))
    try:
        values = [float(left), float(top), float(right), float(bottom)]
    except (TypeError, ValueError):
        return None
    if values[2] <= 1.5 and values[3] <= 1.5:
        values = [values[0] * width, values[1] * height, values[2] * width, values[3] * height]
    return {
        "left": round(max(0.0, min(float(width), values[0])), 3),
        "top": round(max(0.0, min(float(height), values[1])), 3),
        "right": round(max(0.0, min(float(width), values[2])), 3),
        "bottom": round(max(0.0, min(float(height), values[3])), 3),
    }


def _intersection(a: Mapping[str, float], b: Mapping[str, float]) -> dict[str, float] | None:
    left = max(float(a["left"]), float(b["left"]))
    top = max(float(a["top"]), float(b["top"]))
    right = min(float(a["right"]), float(b["right"]))
    bottom = min(float(a["bottom"]), float(b["bottom"]))
    if right <= left or bottom <= top:
        return None
    return {
        "left": round(left, 3),
        "top": round(top, 3),
        "right": round(right, 3),
        "bottom": round(bottom, 3),
    }


def _is_row(label: str) -> bool:
    normalized = str(label or "").lower()
    return "row" in normalized and "header" not in normalized and "spanning" not in normalized


def _is_column(label: str) -> bool:
    normalized = str(label or "").lower()
    return "column" in normalized and "header" not in normalized and "spanning" not in normalized


def table_extraction_from_text_grid(
    *,
    columns: Sequence[Any],
    rows: Sequence[Sequence[Any]],
    page: int | None = None,
    bbox: Mapping[str, Any] | None = None,
    source_element_id: str | None = None,
    detections: Sequence[TableStructureDetection] | None = None,
) -> TableExtraction:
    normalized_columns = [str(col or "").strip() for col in columns]
    col_count = len(normalized_columns)
    normalized_rows = _normalize_rows(rows, col_count)
    cells: list[TableCell] = []
    for col_index, col in enumerate(normalized_columns):
        cells.append(TableCell(row_index=0, col_index=col_index, text=col, is_header=True))
    for row_index, row in enumerate(normalized_rows, start=1):
        for col_index, text in enumerate(row):
            cells.append(TableCell(row_index=row_index, col_index=col_index, text=text, is_header=False))
    metadata: dict[str, Any] = {"source": "table_structure_adapter"}
    if detections:
        metadata["structure_detections"] = [item.to_metadata() for item in detections]
    return TableExtraction(
        columns=normalized_columns,
        rows=normalized_rows,
        cells=cells,
        page=page,
        bbox=bbox,
        source_element_id=source_element_id,
        header_rows=1,
        confidence=_mean_score(detections),
        metadata=metadata,
    )


def table_extraction_from_structure_detections(
    detections: Sequence[TableStructureDetection],
    *,
    image_size: tuple[int, int],
    page: int | None = None,
    bbox: Mapping[str, Any] | None = None,
    source_element_id: str | None = None,
    min_score: float = 0.2,
) -> TableExtraction | None:
    rows: list[dict[str, Any]] = []
    columns: list[dict[str, Any]] = []
    for detection in detections or []:
        if float(detection.score) < float(min_score):
            continue
        box = _bbox_xyxy(detection.bbox, image_size=image_size)
        if box is None:
            continue
        label = str(detection.label or "")
        if _is_row(label):
            rows.append({"bbox": box, "detection": detection})
        elif _is_column(label):
            columns.append({"bbox": box, "detection": detection})

    rows.sort(key=lambda item: (float(item["bbox"]["top"]), float(item["bbox"]["left"])))
    columns.sort(key=lambda item: (float(item["bbox"]["left"]), float(item["bbox"]["top"])))
    if not rows or not columns:
        return None

    header_rows = 1 if len(rows) > 1 else 0
    column_names = [f"Column {index + 1}" for index in range(len(columns))]
    body_row_count = max(0, len(rows) - header_rows)
    body_rows = [["" for _ in columns] for _ in range(body_row_count)]
    cells: list[TableCell] = []
    for row_index, row in enumerate(rows):
        target_row_index = 0 if header_rows and row_index == 0 else row_index - header_rows + 1
        is_header = bool(header_rows and row_index == 0)
        for col_index, column in enumerate(columns):
            cell_box = _intersection(row["bbox"], column["bbox"])
            if cell_box is None:
                continue
            cells.append(
                TableCell(
                    row_index=target_row_index,
                    col_index=col_index,
                    text=column_names[col_index] if is_header else "",
                    is_header=is_header,
                    bbox=cell_box,
                )
            )

    return TableExtraction(
        columns=column_names,
        rows=body_rows,
        cells=cells,
        page=page,
        bbox=bbox,
        source_element_id=source_element_id,
        header_rows=header_rows,
        confidence=_mean_score(detections),
        metadata={
            "source": "table_structure_detections",
            "structure_detections": [item.to_metadata() for item in detections],
            "image_size": {"width": int(image_size[0]), "height": int(image_size[1])},
        },
    )


__all__ = [
    "TableStructureDetection",
    "table_extraction_from_structure_detections",
    "table_extraction_from_text_grid",
]
