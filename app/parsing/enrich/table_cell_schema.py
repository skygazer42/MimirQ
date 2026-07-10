
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TableCell:
    row_index: int
    col_index: int
    text: str
    is_header: bool = False
    row_span: int = 1
    col_span: int = 1
    bbox: Mapping[str, Any] | None = None

    def to_metadata(self) -> dict[str, Any]:
        out = {
            "row_index": int(self.row_index),
            "col_index": int(self.col_index),
            "text": str(self.text or ""),
            "is_header": bool(self.is_header),
            "row_span": int(self.row_span),
            "col_span": int(self.col_span),
        }
        if isinstance(self.bbox, Mapping):
            out["bbox"] = dict(self.bbox)
        return out


@dataclass(frozen=True, slots=True)
class TableExtraction:
    columns: list[str]
    rows: list[list[str]]
    cells: list[TableCell]
    page: int | None = None
    bbox: Mapping[str, Any] | None = None
    source_element_id: str | None = None
    header_rows: int = 1
    confidence: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def col_count(self) -> int:
        return len(self.columns)

    def to_metadata(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema": "mimirq.table_extraction.v1",
            "columns": list(self.columns),
            "row_count": int(self.row_count),
            "col_count": int(self.col_count),
            "header_rows": int(self.header_rows),
            "cells": [cell.to_metadata() for cell in self.cells],
            "rows": [list(row) for row in self.rows],
        }
        if self.page is not None:
            out["source_page"] = int(self.page)
        if isinstance(self.bbox, Mapping):
            out["source_bbox"] = dict(self.bbox)
        if self.source_element_id:
            out["source_element_id"] = str(self.source_element_id)
        if self.confidence is not None:
            out["confidence"] = float(self.confidence)
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out


__all__ = ["TableCell", "TableExtraction"]
