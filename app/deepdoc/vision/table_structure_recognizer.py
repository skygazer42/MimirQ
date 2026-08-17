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
import os
import re
from collections import Counter

import numpy as np

from ..src.model import rag_tokenizer
from .recognizer import Recognizer

_TABLE_COLUMN_LABEL = "table column"


def get_default_resource_dir():
    """
    Return the repo-bundled table-structure model directory.
    """
    resource_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../resources/models/table"))
    return resource_dir


class TableStructureRecognizer(Recognizer):
    labels = [
        "table",
        _TABLE_COLUMN_LABEL,
        "table row",
        "table column header",
        "table projected row header",
        "table spanning cell",
    ]

    def __init__(self):
        super().__init__(self.labels, "tsr", get_default_resource_dir())

    @staticmethod
    def _is_row_like_label(label):
        return label.find("row") > 0 or label.find("header") > 0

    @staticmethod
    def _layout_to_table_box(block):
        return {
            "label": block["type"],
            "score": block["score"],
            "x0": block["bbox"][0],
            "x1": block["bbox"][2],
            "top": block["bbox"][1],
            "bottom": block["bbox"][-1],
        }

    @classmethod
    def _align_row_bounds(cls, boxes):
        left = [b["x0"] for b in boxes if cls._is_row_like_label(b["label"])]
        right = [b["x1"] for b in boxes if cls._is_row_like_label(b["label"])]
        if not left:
            return False
        left = np.mean(left) if len(left) > 4 else np.min(left)
        right = np.mean(right) if len(right) > 4 else np.max(right)
        for box in boxes:
            if not cls._is_row_like_label(box["label"]):
                continue
            if box["x0"] > left:
                box["x0"] = left
            if box["x1"] < right:
                box["x1"] = right
        return True

    @staticmethod
    def _align_column_bounds(boxes):
        top = [b["top"] for b in boxes if b["label"] == _TABLE_COLUMN_LABEL]
        bottom = [b["bottom"] for b in boxes if b["label"] == _TABLE_COLUMN_LABEL]
        if not top:
            return
        top = np.median(top) if len(top) > 4 else np.min(top)
        bottom = np.median(bottom) if len(bottom) > 4 else np.max(bottom)
        for box in boxes:
            if box["label"] != _TABLE_COLUMN_LABEL:
                continue
            if box["top"] > top:
                box["top"] = top
            if box["bottom"] < bottom:
                box["bottom"] = bottom

    def __call__(self, images, thr=0.2):
        tbls = super().__call__(images, thr)
        res = []
        # align left&right for rows, align top&bottom for columns
        for tbl in tbls:
            lts = [self._layout_to_table_box(block) for block in tbl]
            if not lts:
                continue
            if not self._align_row_bounds(lts):
                continue
            self._align_column_bounds(lts)
            res.append(lts)
        return res

    @staticmethod
    def is_caption(bx):
        patt = [r"[图表]+[ 0-9:：]{2,}"]
        if any(re.match(p, bx["text"].strip()) for p in patt) or bx["layout_type"].find("caption") >= 0:
            return True
        return False

    @staticmethod
    def blockType(b):
        patt = [
            ("^(20|19)\\d{2}[年/-]\\d{1,2}[月/-]\\d{1,2}日*$", "Dt"),
            (r"^(20|19)\d{2}年$", "Dt"),
            (r"^(20|19)\d{2}[年-]\d{1,2}月*$", "Dt"),
            ("^\\d{1,2}[月-]\\d{1,2}日*$", "Dt"),
            (r"^第*[一二三四1-4]季度$", "Dt"),
            (r"^(20|19)\d{2}年*[一二三四1-4]季度$", "Dt"),
            (r"^(20|19)\d{2}[ABCDE]$", "Dt"),
            ("^[0-9.,+%/ -]+$", "Nu"),
            (r"^[0-9A-Z/\._~-]+$", "Ca"),
            (r"^[A-Z]*[a-z' -]+$", "En"),
            (r"^[0-9.,+-]+[0-9A-Za-z/$￥%<>（）()' -]+$", "NE"),
            (r"^.{1}$", "Sg"),
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

    @staticmethod
    def _strip_captions(boxes, is_english):
        cap = ""
        i = 0
        while i < len(boxes):
            if TableStructureRecognizer.is_caption(boxes[i]):
                if is_english:
                    cap += " "
                cap += boxes[i]["text"]
                boxes.pop(i)
                i -= 1
            i += 1
        return cap

    @staticmethod
    def _dominant_block_type(boxes):
        max_type = Counter([b["btype"] for b in boxes]).items()
        return max(max_type, key=lambda x: x[1])[0] if max_type else ""

    @staticmethod
    def _sorted_boxes_for_rows(boxes):
        rowh = [b["R_bott"] - b["R_top"] for b in boxes if "R" in b]
        rowh = np.min(rowh) if rowh else 0
        return Recognizer.sort_r_firstly(boxes, rowh / 2)

    @staticmethod
    def _sorted_boxes_for_cols(boxes):
        colwm = [b["C_right"] - b["C_left"] for b in boxes if "C" in b]
        colwm = np.min(colwm) if colwm else 0
        crosspage = len({b["page_number"] for b in boxes}) > 1
        if crosspage:
            return Recognizer.sort_x_firstly(boxes, colwm / 2)
        return Recognizer.sort_c_firstly(boxes, colwm / 2)

    @classmethod
    def _build_rows(cls, boxes):
        boxes = cls._sorted_boxes_for_rows(boxes)
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
        return boxes, rows

    @classmethod
    def _build_cols(cls, boxes):
        boxes = cls._sorted_boxes_for_cols(boxes)
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
        return boxes, cols

    @staticmethod
    def _build_grid(boxes, rows, cols):
        tbl = [[[] for _ in range(len(cols))] for _ in range(len(rows))]
        for box in boxes:
            tbl[box["rn"]][box["cn"]].append(box)
        return tbl

    @staticmethod
    def _single_column_cell(tbl, j):
        entries = [(i, row[j]) for i, row in enumerate(tbl) if row[j]]
        if len(entries) != 1:
            return None
        ii, cell = entries[0]
        return ii, cell[0]

    @staticmethod
    def _column_neighbor_flags(tbl, ii, j):
        has_left = (j > 0 and tbl[ii][j - 1] and tbl[ii][j - 1][0].get("text")) or j == 0
        has_right = (j + 1 < len(tbl[ii]) and tbl[ii][j + 1] and tbl[ii][j + 1][0].get("text")) or j + 1 >= len(tbl[ii])
        return has_left, has_right

    @staticmethod
    def _column_gap_scores(tbl, ii, j, box, has_left, has_right):
        left_gap = right_gap = 100000
        if j > 0 and not has_left:
            for i in range(len(tbl)):
                if tbl[i][j - 1]:
                    left_gap = min(left_gap, np.min([box["x0"] - a["x1"] for a in tbl[i][j - 1]]))
        if j + 1 < len(tbl[0]) and not has_right:
            for i in range(len(tbl)):
                if tbl[i][j + 1]:
                    right_gap = min(right_gap, np.min([a["x0"] - box["x1"] for a in tbl[i][j + 1]]))
        return left_gap, right_gap

    @staticmethod
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

    @staticmethod
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

    @classmethod
    def _collapse_single_columns(cls, tbl, cols):
        if len(cols) < 4:
            return
        j = 0
        while j < len(tbl[0]):
            single_cell = cls._single_column_cell(tbl, j)
            if not single_cell:
                j += 1
                continue
            ii, box = single_cell
            has_left, has_right = cls._column_neighbor_flags(tbl, ii, j)
            if has_left and has_right:
                j += 1
                continue
            logging.debug("Relocate column single: " + box["text"])
            left_gap, right_gap = cls._column_gap_scores(tbl, ii, j, box, has_left, has_right)
            if left_gap >= 100000 and right_gap >= 100000:
                raise RuntimeError("Unable to find adjacent column for table cell merge")
            if left_gap < right_gap:
                cls._merge_column_left(tbl, ii, j)
            else:
                cls._merge_column_right(tbl, ii, j)
            cols.pop(j)

    @staticmethod
    def _single_row_cell(tbl, i):
        entries = [(j, cell) for j, cell in enumerate(tbl[i]) if cell]
        if len(entries) != 1:
            return None
        jj, cell = entries[0]
        return jj, cell[0]

    @staticmethod
    def _row_neighbor_flags(tbl, i, jj):
        has_up = (i > 0 and tbl[i - 1][jj] and tbl[i - 1][jj][0].get("text")) or i == 0
        has_down = (i + 1 < len(tbl) and tbl[i + 1][jj] and tbl[i + 1][jj][0].get("text")) or i + 1 >= len(tbl)
        return has_up, has_down

    @staticmethod
    def _row_gap_scores(tbl, i, jj, box, has_up, has_down):
        up_gap = down_gap = 100000
        if i > 0 and not has_up:
            for j in range(len(tbl[i - 1])):
                if tbl[i - 1][j]:
                    up_gap = min(up_gap, np.min([box["top"] - a["bottom"] for a in tbl[i - 1][j]]))
        if i + 1 < len(tbl) and not has_down:
            for j in range(len(tbl[i + 1])):
                if tbl[i + 1][j]:
                    down_gap = min(down_gap, np.min([a["top"] - box["bottom"] for a in tbl[i + 1][j]]))
        return up_gap, down_gap

    @staticmethod
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

    @staticmethod
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

    @classmethod
    def _collapse_single_rows(cls, tbl, rows):
        if len(tbl) < 4:
            return
        i = 0
        while i < len(tbl):
            single_cell = cls._single_row_cell(tbl, i)
            if not single_cell:
                i += 1
                continue
            jj, box = single_cell
            has_up, has_down = cls._row_neighbor_flags(tbl, i, jj)
            if has_up and has_down:
                i += 1
                continue

            logging.debug("Relocate row single: " + box["text"])
            up_gap, down_gap = cls._row_gap_scores(tbl, i, jj, box, has_up, has_down)
            if up_gap >= 100000 and down_gap >= 100000:
                raise RuntimeError("Unable to find adjacent row for table cell merge")
            if up_gap < down_gap:
                cls._merge_row_up(tbl, i, jj)
            else:
                cls._merge_row_down(tbl, i, jj)
            rows.pop(i)

    @staticmethod
    def _header_score(arr, max_type):
        if max_type == "Nu" and arr[0]["btype"] == "Nu":
            return 0
        if any(a.get("H") for a in arr) or (max_type == "Nu" and arr[0]["btype"] != "Nu"):
            return 1
        return 0

    @classmethod
    def _detect_header_rows(cls, tbl, max_type):
        hdset = set()
        for i, row in enumerate(tbl):
            populated = [arr for arr in row if arr]
            if not populated:
                continue
            score = sum(cls._header_score(arr, max_type) for arr in populated)
            if score / len(populated) > 0.5:
                hdset.add(i)
        return hdset

    @staticmethod
    def construct_table(boxes, is_english=False, html=False, **kwargs):
        cap = TableStructureRecognizer._strip_captions(boxes, is_english)
        if not boxes:
            return []
        for b in boxes:
            b["btype"] = TableStructureRecognizer.blockType(b)
        max_type = TableStructureRecognizer._dominant_block_type(boxes)
        logging.debug("MAXTYPE: " + max_type)

        boxes, rows = TableStructureRecognizer._build_rows(boxes)
        boxes, cols = TableStructureRecognizer._build_cols(boxes)
        tbl = TableStructureRecognizer._build_grid(boxes, rows, cols)
        TableStructureRecognizer._collapse_single_columns(tbl, cols)
        if len(cols) != len(tbl[0]):
            raise RuntimeError("Column NO. miss matched: %d vs %d" % (len(cols), len(tbl[0])))
        TableStructureRecognizer._collapse_single_rows(tbl, rows)
        hdset = TableStructureRecognizer._detect_header_rows(tbl, max_type)

        if html:
            return TableStructureRecognizer.__html_table(
                cap,
                hdset,
                TableStructureRecognizer.__cal_spans(boxes, rows, cols, tbl, True),
            )

        return TableStructureRecognizer.__desc_table(
            cap,
            hdset,
            TableStructureRecognizer.__cal_spans(boxes, rows, cols, tbl, False),
            is_english,
        )

    @staticmethod
    def _cell_text(arr):
        if not arr:
            return ""
        height = min(np.min([c["bottom"] - c["top"] for c in arr]) / 2, 10)
        return " ".join([c["text"] for c in Recognizer.sort_y_firstly(arr, height)])

    @staticmethod
    def _cell_span_attrs(arr):
        attrs = []
        if arr and arr[0].get("colspan"):
            attrs.append("colspan={}".format(arr[0]["colspan"]))
        if arr and arr[0].get("rowspan"):
            attrs.append("rowspan={}".format(arr[0]["rowspan"]))
        return " ".join(attrs)

    @staticmethod
    def _append_html_cell(row, arr, is_header):
        if arr is None:
            return row
        if not arr:
            return row + ("<th></th>" if is_header else "<td></td>")
        txt = TableStructureRecognizer._cell_text(arr)
        attrs = TableStructureRecognizer._cell_span_attrs(arr)
        cell_tag = "th" if is_header else "td"
        return row + f"<{cell_tag} {attrs} >{txt}</{cell_tag}>"

    @staticmethod
    def __html_table(cap, hdset, tbl):
        # constrcut HTML
        html = "<table>"
        if cap:
            html += f"<caption>{cap}</caption>"
        for i in range(len(tbl)):
            row = "<tr>"
            txts = []
            for arr in tbl[i]:
                if arr is not None and arr:
                    txts.append(TableStructureRecognizer._cell_text(arr))
                row = TableStructureRecognizer._append_html_cell(row, arr, i in hdset)

            if i in hdset:
                if all(t in hdset for t in txts):
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

    @staticmethod
    def _row_headers(tbl, hdr_rowno):
        clmno = len(tbl[0])
        headers = {}
        lst_hdr = []
        for r in sorted(hdr_rowno):
            headers[r] = ["" for _ in range(clmno)]
            for i in range(clmno):
                if tbl[r][i]:
                    headers[r][i] = " ".join([a["text"].strip() for a in tbl[r][i]])
            if all(not t for t in headers[r]):
                del headers[r]
                hdr_rowno.remove(r)
                continue
            for j in range(clmno):
                if headers[r][j] or j >= len(lst_hdr):
                    continue
                headers[r][j] = lst_hdr[j]
            lst_hdr = headers[r]
        return headers

    @staticmethod
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

    @staticmethod
    def _nearest_header_row(headers, row_index):
        header_candidates = [(row_index - header_row, header_row) for header_row in headers if header_row < row_index]
        if not header_candidates:
            return 0
        return min(header_candidates, key=lambda x: x[0])[1]

    @staticmethod
    def _plain_row_text(tbl, row_index, clmno):
        texts = []
        for j in range(clmno):
            if tbl[row_index][j]:
                txt = "".join([a["text"].strip() for a in tbl[row_index][j]])
                if txt:
                    texts.append(txt)
        return texts

    @staticmethod
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

    @staticmethod
    def __desc_table(cap, hdr_rowno, tbl, is_english):
        # get text of every colomn in header row to become header text
        clmno = len(tbl[0])
        rowno = len(tbl)
        de = " of " if is_english else "的"
        headers = TableStructureRecognizer._row_headers(tbl, hdr_rowno)
        TableStructureRecognizer._merge_headers(headers, hdr_rowno, rowno, clmno, de)

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

            r = TableStructureRecognizer._nearest_header_row(headers, i) if headers else 0

            if r not in headers and clmno <= 2:
                rtxt.extend(TableStructureRecognizer._plain_row_text(tbl, i, clmno))
                if rtxt:
                    append("：")
                continue

            rtxt.extend(TableStructureRecognizer._described_row_text(tbl, headers, i, r, clmno))
            if rtxt:
                row_txt.append("; ".join(rtxt))

        if cap:
            if is_english:
                from_ = " in "
            else:
                from_ = " from "
            row_txt = [t + f"\t——{from_}{cap}" for t in row_txt]
        return row_txt

    @staticmethod
    def _column_bounds(cols):
        return [np.mean([c.get("C_left", c["x0"]) for c in cln]) for cln in cols], [
            np.mean([c.get("C_right", c["x1"]) for c in cln]) for cln in cols
        ]

    @staticmethod
    def _row_bounds(rows):
        return [np.mean([c.get("R_top", c["top"]) for c in row]) for row in rows], [
            np.mean([c.get("R_btm", c["bottom"]) for c in row]) for row in rows
        ]

    @staticmethod
    def _span_columns(box, clft, crgt):
        for j in range(len(clft)):
            if j == box["cn"]:
                continue
            if clft[j] + (crgt[j] - clft[j]) / 2 < box["H_left"]:
                continue
            if crgt[j] - (crgt[j] - clft[j]) / 2 > box["H_right"]:
                continue
            box["colspan"].append(j)

    @staticmethod
    def _span_rows(box, rtop, rbtm):
        for j in range(len(rtop)):
            if j == box["rn"]:
                continue
            if rtop[j] + (rbtm[j] - rtop[j]) / 2 < box["H_top"]:
                continue
            if rbtm[j] - (rbtm[j] - rtop[j]) / 2 > box["H_bott"]:
                continue
            box["rowspan"].append(j)

    @classmethod
    def _assign_span_indices(cls, boxes, clft, crgt, rtop, rbtm):
        for box in boxes:
            if "SP" not in box:
                continue
            box["colspan"] = [box["cn"]]
            box["rowspan"] = [box["rn"]]
            cls._span_columns(box, clft, crgt)
            cls._span_rows(box, rtop, rbtm)

    @staticmethod
    def _join_cell_text(arr):
        if not arr:
            return ""
        return "".join([t["text"] for t in arr])

    @staticmethod
    def _span_indices(arr):
        rowspan, colspan = [], []
        for item in arr:
            if isinstance(item.get("rowspan", 0), list):
                rowspan.extend(item["rowspan"])
            if isinstance(item.get("colspan", 0), list):
                colspan.extend(item["colspan"])
        return set(rowspan), set(colspan)

    @staticmethod
    def _clear_small_spans(arr):
        for item in arr:
            if "rowspan" in item:
                del item["rowspan"]
            if "colspan" in item:
                del item["colspan"]

    @staticmethod
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

    @classmethod
    def _merge_spanning_cell(cls, tbl, i, j, arr, html):
        rowspan, colspan = cls._span_indices(arr)
        if len(rowspan) < 2 and len(colspan) < 2:
            cls._clear_small_spans(arr)
            return
        rowspan, colspan = sorted(rowspan), sorted(colspan)
        rowspan = list(range(rowspan[0], rowspan[-1] + 1))
        colspan = list(range(colspan[0], colspan[-1] + 1))
        if i not in rowspan:
            raise RuntimeError(str(rowspan))
        if j not in colspan:
            raise RuntimeError(str(colspan))
        merged = []
        for r in rowspan:
            for c in colspan:
                merged_txt = cls._join_cell_text(merged)
                if tbl[r][c] and cls._join_cell_text(tbl[r][c]) != merged_txt:
                    merged.extend(tbl[r][c])
                tbl[r][c] = None if html else merged
        cls._set_span_values(merged, rowspan, colspan)
        tbl[rowspan[0]][colspan[0]] = merged

    @staticmethod
    def __cal_spans(boxes, rows, cols, tbl, html=True):
        # caculate span
        clft, crgt = TableStructureRecognizer._column_bounds(cols)
        rtop, rbtm = TableStructureRecognizer._row_bounds(rows)
        TableStructureRecognizer._assign_span_indices(boxes, clft, crgt, rtop, rbtm)
        for i in range(len(tbl)):
            for j, arr in enumerate(tbl[i]):
                if not arr:
                    continue
                if all("rowspan" not in a and "colspan" not in a for a in arr):
                    continue
                TableStructureRecognizer._merge_spanning_cell(tbl, i, j, arr, html)

        return tbl
