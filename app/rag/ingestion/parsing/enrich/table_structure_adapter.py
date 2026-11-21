#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

import logging
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from typing import Any

from app.rag.ingestion.parsing.enrich.table_cell_schema import TableCell, TableExtraction
from app.rag.ingestion.parsing.utils.scalars import coerce_float


@dataclass(frozen=True, slots=True)
class TableStructureDetection:
    label: str
    score: float
    bbox: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        score = coerce_float(self.score)
        if score is None:
            raise ValueError("Table structure detection score must be finite")
        object.__setattr__(self, "score", score)

    def to_metadata(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "label": self.label,
            "score": round(self.score, 6),
        }
        if isinstance(self.bbox, Mapping):
            out["bbox"] = dict(self.bbox)
        return out


def _text_grid_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_rows(rows: Sequence[Sequence[Any]], col_count: int) -> list[list[str]]:
    out: list[list[str]] = []
    for raw in rows:
        row = [_text_grid_cell(cell) for cell in list(raw)[:col_count]]
        row += [""] * max(0, col_count - len(row))
        if any(row):
            out.append(row)
    return out


def _mean_score(detections: Sequence[TableStructureDetection] | None) -> float | None:
    scores = [item.score for item in (detections or [])]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 6)


def _bbox_xyxy(raw: Mapping[str, Any] | None, *, image_size: tuple[int, int]) -> dict[str, float] | None:
    if not isinstance(raw, Mapping):
        return None
    width, height = image_size
    left = coerce_float(raw.get("left", raw.get("x0")))
    top = coerce_float(raw.get("top", raw.get("y0")))
    right = coerce_float(raw.get("right", raw.get("x1")))
    bottom = coerce_float(raw.get("bottom", raw.get("y1")))
    if left is None or top is None or right is None or bottom is None:
        return None
    values = [left, top, right, bottom]
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


def table_extraction_from_text_grid(
    *,
    columns: Sequence[Any],
    rows: Sequence[Sequence[Any]],
    page: int | None = None,
    bbox: Mapping[str, Any] | None = None,
    source_element_id: str | None = None,
    detections: Sequence[TableStructureDetection] | None = None,
) -> TableExtraction:
    normalized_columns = [_text_grid_cell(col) for col in columns]
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
    rows: list[dict[str, float]] = []
    columns: list[dict[str, float]] = []
    for detection in detections:
        if detection.score < min_score:
            continue
        box = _bbox_xyxy(detection.bbox, image_size=image_size)
        if box is None:
            continue
        label = detection.label.lower()
        if "header" in label or "spanning" in label:
            continue
        if "row" in label:
            rows.append(box)
        elif "column" in label:
            columns.append(box)

    rows.sort(key=lambda box: (box["top"], box["left"]))
    columns.sort(key=lambda box: (box["left"], box["top"]))
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
            cell_box = _intersection(row, column)
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
    "construct_table_from_ocr_boxes",
    "is_table_caption",
    "table_extraction_from_structure_detections",
    "table_extraction_from_text_grid",
]


def is_table_caption(bx) -> bool:
    patt = ["[图表]+[ 0-9:：]{2,}"]
    if any((re.match(p, bx["text"].strip()) for p in patt)) or bx["layout_type"].find("caption") >= 0:
        return True
    return False


def _classify_table_block(b):
    from app.rag.ingestion.parsing.utils import tokenizer as rag_tokenizer

    patt = [
        ("^(20|19)\\d{2}[年/-]\\d{1,2}[月/-]\\d{1,2}日*$", "Dt"),
        ("^(20|19)\\d{2}年$", "Dt"),
        ("^(20|19)\\d{2}[年-]\\d{1,2}月*$", "Dt"),
        ("^\\d{1,2}[月-]\\d{1,2}日*$", "Dt"),
        ("^第*[一二三四1-4]季度$", "Dt"),
        ("^(20|19)\\d{2}年*[一二三四1-4]季度$", "Dt"),
        ("^(20|19)\\d{2}[ABCDE]$", "Dt"),
        ("^[0-9.,+%/ -]+$", "Nu"),
        ("^[0-9A-Z/\\._~-]+$", "Ca"),
        ("^[A-Z]*[a-z' -]+$", "En"),
        ("^[0-9.,+-]+[0-9A-Za-z/$￥%<>（）()' -]+$", "NE"),
        ("^.{1}$", "Sg"),
    ]
    for p, n in patt:
        if re.search(p, b["text"].strip()):
            return n
    tks = [t for t in rag_tokenizer.tokenize(b["text"]).split() if len(t) > 1]
    if len(tks) > 3:
        if len(tks) < 12:
            return "Tx"
        else:
            return "Lx"
    if len(tks) == 1 and rag_tokenizer.tag(tks[0]) == "nr":
        return "Nr"
    return "Ot"


def _strip_captions(boxes, is_english):
    cap = ""
    i = 0
    while i < len(boxes):
        if is_table_caption(boxes[i]):
            if is_english:
                cap += " "
            cap += boxes[i]["text"]
            boxes.pop(i)
            i -= 1
        i += 1
    return cap


def _dominant_block_type(boxes):
    max_type = Counter([b["btype"] for b in boxes]).items()
    return max(max_type, key=lambda x: x[1])[0] if max_type else ""


def _sorted_boxes_for_rows(boxes):
    import numpy as np

    from app.rag.ingestion.parsing.models.recognizer import Recognizer

    rowh = [b["R_bott"] - b["R_top"] for b in boxes if "R" in b]
    rowh = np.min(rowh) if rowh else 0
    return Recognizer.sort_r_firstly(boxes, rowh / 2)


def _sorted_boxes_for_cols(boxes):
    import numpy as np

    from app.rag.ingestion.parsing.models.recognizer import Recognizer

    colwm = [b["C_right"] - b["C_left"] for b in boxes if "C" in b]
    colwm = np.min(colwm) if colwm else 0
    crosspage = len({b["page_number"] for b in boxes}) > 1
    if crosspage:
        return Recognizer.sort_x_firstly(boxes, colwm / 2)
    return Recognizer.sort_c_firstly(boxes, colwm / 2)


def _build_rows(boxes):
    boxes = _sorted_boxes_for_rows(boxes)
    boxes[0]["rn"] = 0
    rows = [[boxes[0]]]
    btm = boxes[0]["bottom"]
    for box in boxes[1:]:
        box["rn"] = len(rows) - 1
        last_row = rows[-1]
        is_new_row = last_row[-1].get("R", "") != box.get("R", "") or (
            box["top"] >= btm - 3 and last_row[-1].get("R", "-1") != box.get("R", "-2")
        )
        if is_new_row:
            btm = box["bottom"]
            box["rn"] += 1
            rows.append([box])
            continue
        btm = (btm + box["bottom"]) / 2.0
        rows[-1].append(box)
    return (boxes, rows)


def _build_cols(boxes):
    boxes = _sorted_boxes_for_cols(boxes)
    boxes[0]["cn"] = 0
    cols = [[boxes[0]]]
    right = boxes[0]["x1"]
    for box in boxes[1:]:
        box["cn"] = len(cols) - 1
        last_col = cols[-1]
        is_next_col = (
            int(box.get("C", "1")) - int(last_col[-1].get("C", "1")) == 1
            and box["page_number"] == last_col[-1]["page_number"]
        )
        separated_col = box["x0"] >= right and last_col[-1].get("C", "-1") != box.get("C", "-2")
        if is_next_col or separated_col:
            right = box["x1"]
            box["cn"] += 1
            cols.append([box])
            continue
        right = (right + box["x1"]) / 2.0
        cols[-1].append(box)
    return (boxes, cols)


def _build_grid(boxes, rows, cols):
    tbl = [[[] for _ in range(len(cols))] for _ in range(len(rows))]
    for box in boxes:
        tbl[box["rn"]][box["cn"]].append(box)
    return tbl


def _single_column_cell(tbl, j):
    entries = [(i, row[j]) for i, row in enumerate(tbl) if row[j]]
    if len(entries) != 1:
        return None
    ii, cell = entries[0]
    return (ii, cell[0])


def _column_neighbor_flags(tbl, ii, j):
    has_left = j > 0 and tbl[ii][j - 1] and tbl[ii][j - 1][0].get("text") or j == 0
    has_right = j + 1 < len(tbl[ii]) and tbl[ii][j + 1] and tbl[ii][j + 1][0].get("text") or j + 1 >= len(tbl[ii])
    return (has_left, has_right)


def _column_gap_scores(tbl, ii, j, box, has_left, has_right):
    import numpy as np

    left_gap = right_gap = 100000
    if j > 0 and (not has_left):
        for i in range(len(tbl)):
            if tbl[i][j - 1]:
                left_gap = min(left_gap, np.min([box["x0"] - a["x1"] for a in tbl[i][j - 1]]))
    if j + 1 < len(tbl[0]) and (not has_right):
        for i in range(len(tbl)):
            if tbl[i][j + 1]:
                right_gap = min(right_gap, np.min([a["x0"] - box["x1"] for a in tbl[i][j + 1]]))
    return (left_gap, right_gap)


def _merge_column_left(tbl, ii, j):
    for jj in range(j, len(tbl[0])):
        for i in range(len(tbl)):
            for cell in tbl[i][jj]:
                cell["cn"] -= 1
    if tbl[ii][j - 1]:
        tbl[ii][j - 1].extend(tbl[ii][j])
    else:
        tbl[ii][j - 1] = tbl[ii][j]
    for row in tbl:
        row.pop(j)


def _merge_column_right(tbl, ii, j):
    for jj in range(j + 1, len(tbl[0])):
        for i in range(len(tbl)):
            for cell in tbl[i][jj]:
                cell["cn"] -= 1
    if tbl[ii][j + 1]:
        tbl[ii][j + 1].extend(tbl[ii][j])
    else:
        tbl[ii][j + 1] = tbl[ii][j]
    for row in tbl:
        row.pop(j)


def _collapse_single_columns(tbl, cols):
    if len(cols) < 4:
        return
    j = 0
    while j < len(tbl[0]):
        single_cell = _single_column_cell(tbl, j)
        if not single_cell:
            j += 1
            continue
        ii, box = single_cell
        has_left, has_right = _column_neighbor_flags(tbl, ii, j)
        if has_left and has_right:
            j += 1
            continue
        logging.debug("Relocate column single: " + box["text"])
        left_gap, right_gap = _column_gap_scores(tbl, ii, j, box, has_left, has_right)
        if left_gap >= 100000 and right_gap >= 100000:
            raise RuntimeError("Unable to find adjacent column for table cell merge")
        if left_gap < right_gap:
            _merge_column_left(tbl, ii, j)
        else:
            _merge_column_right(tbl, ii, j)
        cols.pop(j)


def _single_row_cell(tbl, i):
    entries = [(j, cell) for j, cell in enumerate(tbl[i]) if cell]
    if len(entries) != 1:
        return None
    jj, cell = entries[0]
    return (jj, cell[0])


def _row_neighbor_flags(tbl, i, jj):
    has_up = i > 0 and tbl[i - 1][jj] and tbl[i - 1][jj][0].get("text") or i == 0
    has_down = i + 1 < len(tbl) and tbl[i + 1][jj] and tbl[i + 1][jj][0].get("text") or i + 1 >= len(tbl)
    return (has_up, has_down)


def _row_gap_scores(tbl, i, jj, box, has_up, has_down):
    import numpy as np

    up_gap = down_gap = 100000
    if i > 0 and (not has_up):
        for j in range(len(tbl[i - 1])):
            if tbl[i - 1][j]:
                up_gap = min(up_gap, np.min([box["top"] - a["bottom"] for a in tbl[i - 1][j]]))
    if i + 1 < len(tbl) and (not has_down):
        for j in range(len(tbl[i + 1])):
            if tbl[i + 1][j]:
                down_gap = min(down_gap, np.min([a["top"] - box["bottom"] for a in tbl[i + 1][j]]))
    return (up_gap, down_gap)


def _merge_row_up(tbl, i, jj):
    for ii in range(i, len(tbl)):
        for j in range(len(tbl[ii])):
            for cell in tbl[ii][j]:
                cell["rn"] -= 1
    if tbl[i - 1][jj]:
        tbl[i - 1][jj].extend(tbl[i][jj])
    else:
        tbl[i - 1][jj] = tbl[i][jj]
    tbl.pop(i)


def _merge_row_down(tbl, i, jj):
    for ii in range(i + 1, len(tbl)):
        for j in range(len(tbl[ii])):
            for cell in tbl[ii][j]:
                cell["rn"] -= 1
    if tbl[i + 1][jj]:
        tbl[i + 1][jj].extend(tbl[i][jj])
    else:
        tbl[i + 1][jj] = tbl[i][jj]
    tbl.pop(i)


def _collapse_single_rows(tbl, rows):
    if len(tbl) < 4:
        return
    i = 0
    while i < len(tbl):
        single_cell = _single_row_cell(tbl, i)
        if not single_cell:
            i += 1
            continue
        jj, box = single_cell
        has_up, has_down = _row_neighbor_flags(tbl, i, jj)
        if has_up and has_down:
            i += 1
            continue
        logging.debug("Relocate row single: " + box["text"])
        up_gap, down_gap = _row_gap_scores(tbl, i, jj, box, has_up, has_down)
        if up_gap >= 100000 and down_gap >= 100000:
            raise RuntimeError("Unable to find adjacent row for table cell merge")
        if up_gap < down_gap:
            _merge_row_up(tbl, i, jj)
        else:
            _merge_row_down(tbl, i, jj)
        rows.pop(i)


def _header_score(arr, max_type):
    if max_type == "Nu" and arr[0]["btype"] == "Nu":
        return 0
    if any((a.get("H") for a in arr)) or (max_type == "Nu" and arr[0]["btype"] != "Nu"):
        return 1
    return 0


def _detect_header_rows(tbl, max_type):
    hdset = set()
    for i, row in enumerate(tbl):
        populated = [arr for arr in row if arr]
        if not populated:
            continue
        score = sum((_header_score(arr, max_type) for arr in populated))
        if score / len(populated) > 0.5:
            hdset.add(i)
    return hdset


def construct_table_from_ocr_boxes(boxes, is_english=False, html=False, **kwargs) -> list[str] | str:
    cap = _strip_captions(boxes, is_english)
    if not boxes:
        return []
    for b in boxes:
        b["btype"] = _classify_table_block(b)
    max_type = _dominant_block_type(boxes)
    logging.debug("MAXTYPE: " + max_type)
    boxes, rows = _build_rows(boxes)
    boxes, cols = _build_cols(boxes)
    tbl = _build_grid(boxes, rows, cols)
    _collapse_single_columns(tbl, cols)
    if len(cols) != len(tbl[0]):
        raise RuntimeError("Column NO. miss matched: %d vs %d" % (len(cols), len(tbl[0])))
    _collapse_single_rows(tbl, rows)
    hdset = _detect_header_rows(tbl, max_type)
    if html:
        return _render_ocr_table_html(cap, hdset, _calculate_ocr_table_spans(boxes, rows, cols, tbl, True))
    return _describe_ocr_table(cap, hdset, _calculate_ocr_table_spans(boxes, rows, cols, tbl, False), is_english)


def _cell_text(arr):
    import numpy as np

    from app.rag.ingestion.parsing.models.recognizer import Recognizer

    if not arr:
        return ""
    height = min(np.min([c["bottom"] - c["top"] for c in arr]) / 2, 10)
    return " ".join([c["text"] for c in Recognizer.sort_y_firstly(arr, height)])


def _cell_span_attrs(arr):
    attrs = []
    if arr and arr[0].get("colspan"):
        attrs.append("colspan={}".format(arr[0]["colspan"]))
    if arr and arr[0].get("rowspan"):
        attrs.append("rowspan={}".format(arr[0]["rowspan"]))
    return " ".join(attrs)


def _append_html_cell(row, arr, is_header):
    if arr is None:
        return row
    if not arr:
        return row + ("<th></th>" if is_header else "<td></td>")
    txt = escape(_cell_text(arr))
    attrs = _cell_span_attrs(arr)
    cell_tag = "th" if is_header else "td"
    return row + f"<{cell_tag} {attrs} >{txt}</{cell_tag}>"


def _render_ocr_table_html(cap, hdset, tbl):
    html = "<table>"
    if cap:
        html += f"<caption>{escape(cap)}</caption>"
    for i in range(len(tbl)):
        row = "<tr>"
        txts = []
        for arr in tbl[i]:
            if arr is not None and arr:
                txts.append(_cell_text(arr))
            row = _append_html_cell(row, arr, i in hdset)
        if i in hdset:
            if all((t in hdset for t in txts)):
                continue
            for t in txts:
                hdset.add(t)
        if row != "<tr>":
            row += "</tr>"
        else:
            row = ""
        html += "\n" + row
    html += "\n</table>"
    return html


def _row_headers(tbl, hdr_rowno):
    clmno = len(tbl[0])
    headers = {}
    lst_hdr = []
    for r in sorted(hdr_rowno):
        headers[r] = ["" for _ in range(clmno)]
        for i in range(clmno):
            if tbl[r][i]:
                headers[r][i] = " ".join([a["text"].strip() for a in tbl[r][i]])
        if all((not t for t in headers[r])):
            del headers[r]
            hdr_rowno.remove(r)
            continue
        for j in range(clmno):
            if headers[r][j] or j >= len(lst_hdr):
                continue
            headers[r][j] = lst_hdr[j]
        lst_hdr = headers[r]
    return headers


def _merge_headers(headers, hdr_rowno, rowno, clmno, delimiter):
    for i in range(rowno):
        if i not in hdr_rowno:
            continue
        for j in range(i + 1, rowno):
            if j not in hdr_rowno:
                break
            for k in range(clmno):
                if not headers[j - 1][k]:
                    continue
                if headers[j][k].find(headers[j - 1][k]) >= 0:
                    continue
                if len(headers[j][k]) > len(headers[j - 1][k]):
                    headers[j][k] += (delimiter if headers[j][k] else "") + headers[j - 1][k]
                else:
                    headers[j][k] = headers[j - 1][k] + (delimiter if headers[j - 1][k] else "") + headers[j][k]


def _nearest_header_row(headers, row_index):
    header_candidates = [(row_index - header_row, header_row) for header_row in headers if header_row < row_index]
    if not header_candidates:
        return 0
    return min(header_candidates, key=lambda x: x[0])[1]


def _plain_row_text(tbl, row_index, clmno):
    texts = []
    for j in range(clmno):
        if tbl[row_index][j]:
            txt = "".join([a["text"].strip() for a in tbl[row_index][j]])
            if txt:
                texts.append(txt)
    return texts


def _described_row_text(tbl, headers, row_index, header_row, clmno):
    texts = []
    for j in range(clmno):
        if not tbl[row_index][j]:
            continue
        txt = "".join([a["text"].strip() for a in tbl[row_index][j]])
        if not txt:
            continue
        content = headers[header_row][j] if header_row in headers else ""
        if content:
            content += "："
        content += txt
        if content:
            texts.append(content)
    return texts


def _describe_ocr_table(cap, hdr_rowno, tbl, is_english):
    clmno = len(tbl[0])
    rowno = len(tbl)
    de = " of " if is_english else "的"
    headers = _row_headers(tbl, hdr_rowno)
    _merge_headers(headers, hdr_rowno, rowno, clmno, de)
    logging.debug(f">>>>>>>>>>>>>>>>>{cap}：SIZE:{rowno}X{clmno} Header: {hdr_rowno}")
    row_txt = []
    for i in range(rowno):
        if i in hdr_rowno:
            continue
        rtxt = []

        def append(delimer):
            nonlocal rtxt, row_txt
            rtxt = delimer.join(rtxt)
            if row_txt and len(row_txt[-1]) + len(rtxt) < 64:
                row_txt[-1] += "\n" + rtxt
            else:
                row_txt.append(rtxt)

        r = _nearest_header_row(headers, i) if headers else 0
        if r not in headers and clmno <= 2:
            rtxt.extend(_plain_row_text(tbl, i, clmno))
            if rtxt:
                append("：")
            continue
        rtxt.extend(_described_row_text(tbl, headers, i, r, clmno))
        if rtxt:
            row_txt.append("; ".join(rtxt))
    if cap:
        if is_english:
            from_ = " in "
        else:
            from_ = " from "
        row_txt = [t + f"\t——{from_}{cap}" for t in row_txt]
    return row_txt


def _column_bounds(cols):
    import numpy as np

    return (
        [np.mean([c.get("C_left", c["x0"]) for c in cln]) for cln in cols],
        [np.mean([c.get("C_right", c["x1"]) for c in cln]) for cln in cols],
    )


def _row_bounds(rows):
    import numpy as np

    return (
        [np.mean([c.get("R_top", c["top"]) for c in row]) for row in rows],
        [np.mean([c.get("R_btm", c["bottom"]) for c in row]) for row in rows],
    )


def _span_columns(box, clft, crgt):
    for j in range(len(clft)):
        if j == box["cn"]:
            continue
        if clft[j] + (crgt[j] - clft[j]) / 2 < box["H_left"]:
            continue
        if crgt[j] - (crgt[j] - clft[j]) / 2 > box["H_right"]:
            continue
        box["colspan"].append(j)


def _span_rows(box, rtop, rbtm):
    for j in range(len(rtop)):
        if j == box["rn"]:
            continue
        if rtop[j] + (rbtm[j] - rtop[j]) / 2 < box["H_top"]:
            continue
        if rbtm[j] - (rbtm[j] - rtop[j]) / 2 > box["H_bott"]:
            continue
        box["rowspan"].append(j)


def _assign_span_indices(boxes, clft, crgt, rtop, rbtm):
    for box in boxes:
        if "SP" not in box:
            continue
        box["colspan"] = [box["cn"]]
        box["rowspan"] = [box["rn"]]
        _span_columns(box, clft, crgt)
        _span_rows(box, rtop, rbtm)


def _join_cell_text(arr):
    if not arr:
        return ""
    return "".join([t["text"] for t in arr])


def _span_indices(arr):
    rowspan, colspan = ([], [])
    for item in arr:
        if isinstance(item.get("rowspan", 0), list):
            rowspan.extend(item["rowspan"])
        if isinstance(item.get("colspan", 0), list):
            colspan.extend(item["colspan"])
    return (set(rowspan), set(colspan))


def _clear_small_spans(arr):
    for item in arr:
        if "rowspan" in item:
            del item["rowspan"]
        if "colspan" in item:
            del item["colspan"]


def _set_span_values(arr, rowspan, colspan):
    for item in arr:
        if len(rowspan) > 1:
            item["rowspan"] = len(rowspan)
        elif "rowspan" in item:
            del item["rowspan"]
        if len(colspan) > 1:
            item["colspan"] = len(colspan)
        elif "colspan" in item:
            del item["colspan"]


def _merge_spanning_cell(tbl, i, j, arr, html):
    rowspan, colspan = _span_indices(arr)
    if len(rowspan) < 2 and len(colspan) < 2:
        _clear_small_spans(arr)
        return
    rowspan, colspan = (sorted(rowspan), sorted(colspan))
    rowspan = list(range(rowspan[0], rowspan[-1] + 1))
    colspan = list(range(colspan[0], colspan[-1] + 1))
    if i not in rowspan:
        raise RuntimeError(str(rowspan))
    if j not in colspan:
        raise RuntimeError(str(colspan))
    merged = []
    for r in rowspan:
        for c in colspan:
            merged_txt = _join_cell_text(merged)
            if tbl[r][c] and _join_cell_text(tbl[r][c]) != merged_txt:
                merged.extend(tbl[r][c])
            tbl[r][c] = None if html else merged
    _set_span_values(merged, rowspan, colspan)
    tbl[rowspan[0]][colspan[0]] = merged


def _calculate_ocr_table_spans(boxes, rows, cols, tbl, html=True):
    clft, crgt = _column_bounds(cols)
    rtop, rbtm = _row_bounds(rows)
    _assign_span_indices(boxes, clft, crgt, rtop, rbtm)
    for i in range(len(tbl)):
        for j, arr in enumerate(tbl[i]):
            if not arr:
                continue
            if all(("rowspan" not in a and "colspan" not in a for a in arr)):
                continue
            _merge_spanning_cell(tbl, i, j, arr, html)
    return tbl
