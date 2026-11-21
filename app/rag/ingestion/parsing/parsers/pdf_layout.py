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

"""Layout, OCR and visual PDF parsing algorithms."""

import logging
import os
import re
import sys
import threading
from contextlib import ExitStack
from copy import deepcopy
from io import BytesIO
from timeit import default_timer as timer

import numpy as np
import pdfplumber
import trio
from PIL import Image
from pypdf import PdfReader as pdf2_read

from app.rag.ingestion.parsing.enrich.image_understanding import compose_context_images
from app.rag.ingestion.parsing.enrich.table_structure_adapter import construct_table_from_ocr_boxes, is_table_caption
from app.rag.ingestion.parsing.enrich.vlm_image_caption import describe_image_with_model, page_transcription_prompt
from app.rag.ingestion.parsing.models.layout import LayoutRecognizer4YOLOv10 as LayoutRecognizer
from app.rag.ingestion.parsing.models.ocr import OCR
from app.rag.ingestion.parsing.models.recognizer import Recognizer
from app.rag.ingestion.parsing.models.table_structure import TableStructureRecognizer
from app.rag.ingestion.parsing.utils import tokenizer as rag_tokenizer
from app.rag.ingestion.parsing.utils.block_schema import remove_pdf_position_tags

LOCK_KEY_pdfplumber = "global_shared_lock_pdfplumber"
if LOCK_KEY_pdfplumber not in sys.modules:
    sys.modules[LOCK_KEY_pdfplumber] = threading.Lock()


def _resolve_ocr_page_concurrency() -> int:
    raw = os.getenv("DEEPDOC_OCR_PAGE_CONCURRENCY")
    if raw is not None:
        try:
            return max(1, min(16, int(raw)))
        except ValueError:
            logging.warning("Invalid DEEPDOC_OCR_PAGE_CONCURRENCY=%r; falling back to serial", raw)
    return 1


def _evenly_sample(values, limit):
    if len(values) <= limit:
        return values
    step = len(values) / float(limit)
    return [values[min(len(values) - 1, int(index * step))] for index in range(limit)]


def _noop_progress(*args, **kwargs):
    return None


class LayoutPdfParser:
    remove_tag = staticmethod(remove_pdf_position_tags)

    def __init__(self, **kwargs):
        """
        If you have trouble downloading HuggingFace models, -_^ this might help!!

        For Linux:
        export HF_ENDPOINT=https://hf-mirror.com

        For Windows:
        Good luck
        ^_-
         Split PDF by pages, extract text boxes, tables, images and other structures.
        """

        self.ocr = OCR()
        self.parallel_limiter = self._build_ocr_parallel_limiters()

        if hasattr(self, "model_speciess"):
            self.layouter = LayoutRecognizer(
                "layout." + self.model_speciess
            )  # Initialize layout recognizer with specified model
        else:
            self.layouter = LayoutRecognizer("layout")  # Initialize layout recognizer with default model
        self.tbl_det = TableStructureRecognizer()  # Initialize table structure recognizer

        # Set page starting number
        self.page_from = 0
        self.page_images = []
        self.page_chars = []
        self.total_page = 0

    def close_images(self):
        """Release backing pages after the last crop consumer; returned crops own their pixels."""
        images, self.page_images = self.page_images, []
        self.page_chars = []
        with ExitStack() as resources:
            for image in images:
                resources.callback(image.close)

    def _build_ocr_parallel_limiters(self):
        page_concurrency = _resolve_ocr_page_concurrency()
        if page_concurrency <= 1:
            return None
        detector_count = len(getattr(self.ocr, "text_detector", []) or [])
        recognizer_count = len(getattr(self.ocr, "text_recognizer", []) or [])
        device_count = max(1, min(detector_count or 1, recognizer_count or 1))
        per_device = max(1, int(np.ceil(page_concurrency / device_count)))
        return [trio.CapacityLimiter(per_device) for _ in range(device_count)]

    def _store_ocr_boxes(self, page_index: int, boxes):
        if page_index < 0:
            return
        while len(self.boxes) <= page_index:
            self.boxes.append(None)
        self.boxes[page_index] = boxes

    # Calculate character width (right - left) / text length

    # Calculate character box height

    # Calculate minimum distance between two boxes in x direction (may overlap)
    def _x_dis(self, a, b):
        return min(abs(a["x1"] - b["x0"]), abs(a["x0"] - b["x1"]), abs(a["x0"] + a["x1"] - b["x0"] - b["x1"]) / 2)

    # Calculate center point difference between two boxes in y direction
    def _y_dis(self, a, b):
        return (b["top"] + b["bottom"] - a["top"] - a["bottom"]) / 2

    # Check if text matches item numbering patterns (e.g., "Chapter X", "1.", "1.1.", etc.)

    # Build features between two text blocks to determine if they should be merged

    @staticmethod
    def sort_x_by_page(arr, threashold):
        # Sort by page number, x coordinate, y coordinate
        arr = sorted(arr, key=lambda r: (r["page_number"], r["x0"], r["top"]))
        for i in range(len(arr) - 1):
            for j in range(i, -1, -1):
                # Swap same-page items when x values are close but the later item is
                # visually higher on the page.
                if (
                    abs(arr[j + 1]["x0"] - arr[j]["x0"]) < threashold
                    and arr[j + 1]["top"] < arr[j]["top"]
                    and arr[j + 1]["page_number"] == arr[j]["page_number"]
                ):
                    tmp = arr[j]
                    arr[j] = arr[j + 1]
                    arr[j + 1] = tmp
        return arr

    def _has_color(self, o):
        # Check if text object has color (mainly for determining if grayscale text is valid)
        if o.get("ncs", "") == "DeviceGray":
            # If both stroke color and fill color are white (1 means white)
            if (
                o["stroking_color"]
                and o["stroking_color"][0] == 1
                and o["non_stroking_color"]
                and o["non_stroking_color"][0] == 1
            ):
                # If text is invalid placeholder characters, e.g., [a-zT_[]()-]
                if re.match(r"[a-zT_\[\]\(\)-]+", o.get("text", "")):
                    return False
        return True

    def _table_layout_crops(self, zoom, margin):
        imgs, pos, tbcnt = [], [], [0]
        with ExitStack() as resources:
            for p, tbls in enumerate(self.page_layout):
                tbls = [f for f in tbls if f["type"] == "table"]
                tbcnt.append(len(tbls))
                for tb in tbls:
                    left, top, right, bott = (
                        tb["x0"] - margin,
                        tb["top"] - margin,
                        tb["x1"] + margin,
                        tb["bottom"] + margin,
                    )
                    left *= zoom
                    top *= zoom
                    right *= zoom
                    bott *= zoom
                    pos.append((left, top))
                    image = self.page_images[p].crop((left, top, right, bott))
                    resources.callback(image.close)
                    imgs.append(image)
            resources.pop_all()
        return imgs, pos, tbcnt

    def _restore_table_component(self, item, page_index, layout_index, offset, zoom):
        item["x0"] = item["x0"] + offset[0]
        item["x1"] = item["x1"] + offset[0]
        item["top"] = item["top"] + offset[1]
        item["bottom"] = item["bottom"] + offset[1]
        for n in ["x0", "x1", "top", "bottom"]:
            item[n] /= zoom
        item["top"] += self.page_cum_height[page_index]
        item["bottom"] += self.page_cum_height[page_index]
        item["pn"] = page_index
        item["layoutno"] = layout_index
        return item

    def _restore_table_components(self, recos, tbcnt, pos, zoom):
        tbcnt = np.cumsum(tbcnt)
        for page_index in range(len(tbcnt) - 1):
            page_components = []
            poss = pos[tbcnt[page_index] : tbcnt[page_index + 1]]
            for layout_index, tb_items in enumerate(recos[tbcnt[page_index] : tbcnt[page_index + 1]]):
                page_components.extend(
                    self._restore_table_component(item, page_index, layout_index, poss[layout_index], zoom)
                    for item in tb_items
                )
            self.tb_cpns.extend(page_components)

    def _table_components_by_label(self, kwd, fzy=10, ption=0.6):
        eles = Recognizer.sort_y_firstly([r for r in self.tb_cpns if re.match(kwd, r["label"])], fzy)
        eles = Recognizer.layouts_cleanup(self.boxes, eles, 5, ption)
        return Recognizer.sort_y_firstly(eles, 0)

    def _table_columns(self):
        columns = sorted(
            [r for r in self.tb_cpns if re.match(r"table column$", r["label"])],
            key=lambda x: (x["pn"], x["layoutno"], x["x0"]),
        )
        return Recognizer.layouts_cleanup(self.boxes, columns, 5, 0.5)

    @staticmethod
    def _apply_table_span(box, span, prefix):
        box[f"{prefix}_top"] = span["top"]
        box[f"{prefix}_bott"] = span["bottom"]
        box[f"{prefix}_left"] = span["x0"]
        box[f"{prefix}_right"] = span["x1"]

    def _match_table_box_metadata(self, box, rows, headers, columns, spans):
        ii = Recognizer.find_overlapped_with_threashold(box, rows, thr=0.3)
        if ii is not None:
            box["R"] = ii
            box["R_top"] = rows[ii]["top"]
            box["R_bott"] = rows[ii]["bottom"]

        ii = Recognizer.find_overlapped_with_threashold(box, headers, thr=0.3)
        if ii is not None:
            self._apply_table_span(box, headers[ii], "H")
            box["H"] = ii

        ii = Recognizer.find_horizontally_tightest_fit(box, columns)
        if ii is not None:
            box["C"] = ii
            box["C_left"] = columns[ii]["x0"]
            box["C_right"] = columns[ii]["x1"]

        ii = Recognizer.find_overlapped_with_threashold(box, spans, thr=0.3)
        if ii is not None:
            self._apply_table_span(box, spans[ii], "H")
            box["SP"] = ii

    def _table_transformer_job(self, zoom):
        # Table structure recognition processing flow
        logging.debug("Table processing...")
        margin = 10  # Margin around table images
        self.tb_cpns = []  # Final recognized table components
        if len(self.page_layout) != len(self.page_images):
            raise RuntimeError("Layout pages must match image pages")
        imgs, pos, tbcnt = self._table_layout_crops(zoom, margin)

        with ExitStack() as resources:
            for image in imgs:
                resources.callback(image.close)
            if len(self.page_images) != len(tbcnt) - 1:
                raise RuntimeError("Table crop page count must match image pages")
            if not imgs:
                return
            recos = self.tbl_det(imgs)
            self._restore_table_components(recos, tbcnt, pos, zoom)

        # Extract header, row, merged cell, column info
        headers = self._table_components_by_label(r".*header$")
        rows = self._table_components_by_label(r".* (row|header)")
        spans = self._table_components_by_label(r".*spanning")
        clmns = self._table_columns()
        for b in self.boxes:
            if b.get("layout_type", "") != "table":
                continue
            self._match_table_box_metadata(b, rows, headers, clmns, spans)

    def _ocr_detect_boxes(self, pagenum, img, zoom, device_id):
        raw_boxes = self.ocr.detect(np.array(img), device_id)
        if not raw_boxes:
            self._store_ocr_boxes(pagenum - 1, [])
            return []
        raw_boxes = [(line[0], line[1][0]) for line in raw_boxes]
        return Recognizer.sort_y_firstly(
            [
                {
                    "x0": b[0][0] / zoom,
                    "x1": b[1][0] / zoom,
                    "top": b[0][1] / zoom,
                    "text": "",
                    "txt": t,
                    "bottom": b[-1][1] / zoom,
                    "page_number": pagenum,
                }
                for b, t in raw_boxes
                if b[0][0] <= b[1][0] and b[0][1] <= b[-1][1]
            ],
            self.mean_height[-1] / 3,
        )

    def _append_char_to_ocr_box(self, char, box):
        ch = char["bottom"] - char["top"]
        bh = box["bottom"] - box["top"]
        if ch <= 0 or bh <= 0:
            return False
        if abs(ch - bh) / max(ch, bh) >= 0.7 and char["text"] != " ":
            return False
        if char["text"] == " " and box["text"]:
            if re.match(r"[0-9a-zA-Zа-яА-Я,.?;:!%]", box["text"][-1]):
                box["text"] += " "
        else:
            box["text"] += char["text"]
        return True

    def _merge_chars_into_ocr_boxes(self, pagenum, chars, boxes):
        for c in Recognizer.sort_y_firstly(chars, self.mean_height[pagenum - 1] // 4):
            ii = Recognizer.find_overlapped(c, boxes)
            if ii is None or not self._append_char_to_ocr_box(c, boxes[ii]):
                self.lefted_chars.append(c)

    def _boxes_requiring_ocr_recognition(self, img, boxes, zoom):
        boxes_to_reg = []
        img_np = np.array(img)
        for b in boxes:
            if not b["text"]:
                left, right, top, bott = b["x0"] * zoom, b["x1"] * zoom, b["top"] * zoom, b["bottom"] * zoom
                b["box_image"] = self.ocr.get_rotate_crop_image(
                    img_np, np.array([[left, top], [right, top], [right, bott], [left, bott]], dtype=np.float32)
                )
                boxes_to_reg.append(b)
            del b["txt"]
        return boxes_to_reg

    def _recognize_empty_ocr_boxes(self, boxes_to_reg, device_id):
        texts = self.ocr.recognize_batch([b["box_image"] for b in boxes_to_reg], device_id)
        for i in range(len(boxes_to_reg)):
            boxes_to_reg[i]["text"] = texts[i]
            del boxes_to_reg[i]["box_image"]

    def _update_page_mean_height(self, boxes):
        if self.mean_height[-1] == 0:
            self.mean_height[-1] = np.median([b["bottom"] - b["top"] for b in boxes])

    def __ocr(self, pagenum, img, chars, zoom=3, device_id: int | None = None):
        # Start timing
        start = timer()
        # Use OCR module to detect text boxes in the image (detection phase)
        bxs = self._ocr_detect_boxes(pagenum, img, zoom, device_id)

        logging.info(f"__ocr detecting boxes of a image cost ({timer() - start}s)")

        start = timer()
        # If no boxes detected, return empty list
        if not bxs:
            return

        # Merge each character into its corresponding box
        self._merge_chars_into_ocr_boxes(pagenum, chars, bxs)

        logging.info(f"__ocr sorting {len(chars)} chars cost {timer() - start}s")
        start = timer()

        # Collect boxes that need text recognition (no text recognized yet)
        boxes_to_reg = self._boxes_requiring_ocr_recognition(img, bxs, zoom)

        # Batch text recognition
        self._recognize_empty_ocr_boxes(boxes_to_reg, device_id)

        logging.info(f"__ocr recognize {len(bxs)} boxes cost {timer() - start}s")

        # Remove boxes that are still empty after recognition
        bxs = [b for b in bxs if b["text"]]

        # If mean height not set, set to median height of boxes on current page
        self._update_page_mean_height(bxs)

        # Add current page's boxes to total box collection
        self._store_ocr_boxes(pagenum - 1, bxs)

    def _layouts_rec(self, zoom, drop=True):
        # Layout recognition: identify layout type (text, image, table, etc.) for each box
        if len(self.page_images) != len(self.boxes):
            raise RuntimeError("Layout recognition requires one box list per page image")
        self.boxes, self.page_layout = self.layouter(self.page_images, self.boxes, zoom, drop=drop)
        # Cumulative height offset: unify box y coordinates to global coordinates
        for i in range(len(self.boxes)):
            self.boxes[i]["top"] += self.page_cum_height[self.boxes[i]["page_number"] - 1]
            self.boxes[i]["bottom"] += self.page_cum_height[self.boxes[i]["page_number"] - 1]

    @staticmethod
    def _box_text_ends_with(box, txt):
        txt = txt.strip()
        text = box.get("text", "").strip()
        return text and text.find(txt) == len(text) - len(txt)

    @staticmethod
    def _box_text_starts_with_any(box, txts):
        text = box.get("text", "").strip()
        return text and any(text.find(t.strip()) == 0 for t in txts)

    @staticmethod
    def _horizontal_merge_disallowed(box, next_box):
        return box.get("layoutno", "0") != next_box.get("layoutno", "1") or box.get("layout_type", "") in [
            "table",
            "figure",
            "equation",
        ]

    @staticmethod
    def _merge_adjacent_text_boxes(box, next_box):
        box["x1"] = next_box["x1"]
        box["top"] = (box["top"] + next_box["top"]) / 2
        box["bottom"] = (box["bottom"] + next_box["bottom"]) / 2
        box["text"] += next_box["text"]

    def _same_row_mergeable(self, box, next_box, mean_height):
        return abs(self._y_dis(box, next_box)) < mean_height / 3

    def _tight_row_distance_threshold(self, box, next_box):
        if box.get("layout_type", "") == "text" and next_box.get("layout_type", "") == "text":
            return 1
        if self._box_text_ends_with(box, "，") or self._box_text_starts_with_any(next_box, "（，"):
            return -8
        return None

    def _tight_row_mergeable(self, box, next_box, mean_height):
        dis_thr = self._tight_row_distance_threshold(box, next_box)
        if dis_thr is None:
            return False
        dis = box["x1"] - next_box["x0"]
        return abs(self._y_dis(box, next_box)) < mean_height / 5 and dis >= dis_thr and box["x1"] < next_box["x1"]

    def _should_merge_horizontal_pair(self, box, next_box, mean_height):
        if self._horizontal_merge_disallowed(box, next_box):
            return False
        return self._same_row_mergeable(box, next_box, mean_height) or self._tight_row_mergeable(
            box, next_box, mean_height
        )

    def _text_merge(self):
        # Merge text boxes in the same row (horizontal merge)
        bxs = self.boxes
        # horizontally merge adjacent box with the same layout
        i = 0
        while i < len(bxs) - 1:
            b = bxs[i]
            b_ = bxs[i + 1]
            mean_height = self.mean_height[bxs[i]["page_number"] - 1]
            if self._should_merge_horizontal_pair(b, b_, mean_height):
                self._merge_adjacent_text_boxes(bxs[i], b_)
                bxs.pop(i + 1)
                continue
            i += 1
        self.boxes = bxs

    # Simple vertical merge of text blocks: merge upper and lower text blocks into paragraphs
    def _naive_vertical_merge(self):
        bxs = Recognizer.sort_y_firstly(self.boxes, np.median(self.mean_height) / 3)
        i = 0
        while i + 1 < len(bxs):
            b = bxs[i]
            b_ = bxs[i + 1]
            # Remove page number rows and other useless info (page numbers typically occupy a single row)
            if b["page_number"] < b_["page_number"] and re.match(r"[0-9 •一—-]+$", b["text"]):
                bxs.pop(i)
                continue
            if not b["text"].strip():
                bxs.pop(i)
                continue
            concatting_feats = [
                b["text"].strip()[-1] in ",;:'\"，、‘“；：-",
                len(b["text"].strip()) > 1 and b["text"].strip()[-2] in ",;:'\"，‘“、；：",
                b_["text"].strip() and b_["text"].strip()[0] in "。；？！?”）),，、：",
            ]
            # features for not concating
            feats = [
                b.get("layoutno", 0) != b_.get("layoutno", 0),
                b["text"].strip()[-1] in "。？！?",
                self.is_english and b["text"].strip()[-1] in ".!?",
                b["page_number"] == b_["page_number"]
                and b_["top"] - b["bottom"] > self.mean_height[b["page_number"] - 1] * 1.5,
                b["page_number"] < b_["page_number"]
                and abs(b["x0"] - b_["x0"]) > self.mean_width[b["page_number"] - 1] * 4,
            ]
            # split features
            detach_feats = [b["x1"] < b_["x0"], b["x0"] > b_["x1"]]
            if (any(feats) and not any(concatting_feats)) or any(detach_feats):
                logging.debug(
                    "Vertical merge skipped: chars=%s/%s split=%s concat=%s",
                    len(b["text"]),
                    len(b_["text"]),
                    any(feats),
                    any(concatting_feats),
                )
                i += 1
                continue
            # merge up and down
            b["bottom"] = b_["bottom"]
            b["text"] += b_["text"]
            b["x0"] = min(b["x0"], b_["x0"])
            b["x1"] = max(b["x1"], b_["x1"])
            bxs.pop(i + 1)
        self.boxes = bxs

    def _mark_in_row_counts(self):
        for i in range(len(self.boxes)):
            mh = self.mean_height[self.boxes[i]["page_number"] - 1]
            self.boxes[i]["in_row"] = 0
            j = max(0, i - 12)
            while j < min(i + 12, len(self.boxes)):
                if j == i:
                    j += 1
                    continue
                ydis = self._y_dis(self.boxes[i], self.boxes[j]) / mh
                if abs(ydis) < 1:
                    self.boxes[i]["in_row"] += 1
                elif ydis > 0:
                    break
                j += 1

    def _downward_scan_should_stop(self, up, down, ydis, mh, concat_between_pages):
        same_page = up["page_number"] == down["page_number"]
        if same_page and ydis > mh * 4:
            return True
        if not same_page and ydis > mh * 16:
            return True
        return not concat_between_pages and down["page_number"] > up["page_number"]

    def _downward_candidate_invalid(self, up, down, mw):
        if up.get("R", "") != down.get("R", "") and up["text"][-1] != "，":
            return True
        if re.match(r"\d{2,3}/\d{3}$", up["text"]) or re.match(r"\d{2,3}/\d{3}$", down["text"]):
            return True
        if not down["text"].strip() or not up["text"].strip():
            return True
        return up["x1"] < down["x0"] - 10 * mw or up["x0"] > down["x1"] + 10 * mw

    @staticmethod
    def _same_text_layout_concat(up, down, offset):
        if offset >= 5 or up.get("layout_type") != "text":
            return None
        return up.get("layoutno", "1") == down.get("layoutno", "2")

    def _downward_concat_action(self, up, down, offset, concat_between_pages):
        ydis = self._y_dis(up, down)
        mh = self.mean_height[up["page_number"] - 1]
        mw = self.mean_width[up["page_number"] - 1]
        if self._downward_scan_should_stop(up, down, ydis, mh, concat_between_pages):
            return "break"
        if self._downward_candidate_invalid(up, down, mw):
            return "skip"

        same_layout = self._same_text_layout_concat(up, down, offset)
        if same_layout is not None:
            return "concat" if same_layout else "skip"
        return "concat"

    def _collect_downward_block(self, boxes, concat_between_pages):
        chunks = []

        def dfs(up, dp):
            chunks.append(up)
            i = dp
            while i < min(dp + 12, len(boxes)):
                action = self._downward_concat_action(up, boxes[i], i - dp, concat_between_pages)
                if action == "break":
                    break
                if action != "concat":
                    i += 1
                    continue
                dfs(boxes[i], i + 1)
                boxes.pop(i)
                return

        dfs(boxes[0], 1)
        boxes.pop(0)
        return chunks

    def _merge_downward_block(self, block):
        if len(block) == 1:
            return block[0]
        t = block[0]
        for c in block[1:]:
            t["text"] = t["text"].strip()
            c["text"] = c["text"].strip()
            if not c["text"]:
                continue
            if t["text"] and re.match(r"[0-9\.a-zA-Z]+$", t["text"][-1] + c["text"][-1]):
                t["text"] += " "
            t["text"] += c["text"]
            t["x0"] = min(t["x0"], c["x0"])
            t["x1"] = max(t["x1"], c["x1"])
            t["page_number"] = min(t["page_number"], c["page_number"])
            t["bottom"] = c["bottom"]
            if not t["layout_type"] and c["layout_type"]:
                t["layout_type"] = c["layout_type"]
        return t

    def _concat_downward(self, concat_between_pages=True):
        # Count number of other boxes in the same row for each box (as a feature)
        self._mark_in_row_counts()

        # Perform cross-row merging (depth-first merge)
        boxes = deepcopy(self.boxes)
        blocks = []
        while boxes:
            chunks = self._collect_downward_block(boxes, concat_between_pages)
            if chunks:
                blocks.append(chunks)

        # Actually merge text boxes within each block
        self.boxes = Recognizer.sort_y_firstly([self._merge_downward_block(b) for b in blocks], 0)

    @staticmethod
    def _is_toc_marker(text):
        normalized = re.sub(r"[ \u3000]+", "", text.lower())
        return re.match(r"(contents|目录|目次|table of contents|致谢|acknowledge)$", normalized)

    @staticmethod
    def _toc_prefix(text, eng):
        stripped = text.strip()
        if eng:
            return " ".join(stripped.split()[:2])
        return stripped[:3]

    def _remove_toc_like_block(self, index):
        eng = re.match(r"[0-9a-zA-Z :'.-]{5,}", self.boxes[index]["text"].strip())
        self.boxes.pop(index)
        if index >= len(self.boxes):
            return False

        prefix = self._toc_prefix(self.boxes[index]["text"], eng)
        while not prefix:
            self.boxes.pop(index)
            if index >= len(self.boxes):
                return False
            prefix = self._toc_prefix(self.boxes[index]["text"], eng)

        self.boxes.pop(index)
        if index >= len(self.boxes) or not prefix:
            return False

        for j in range(index, min(index + 128, len(self.boxes))):
            if not self.boxes[j]["text"].startswith(prefix):
                continue
            for _ in range(index, j):
                self.boxes.pop(index)
            break
        return True

    def _remove_toc_pages(self):
        findit = False
        i = 0
        while i < len(self.boxes):
            if not self._is_toc_marker(self.boxes[i]["text"]):
                i += 1
                continue
            findit = True
            if not self._remove_toc_like_block(i):
                break
        return findit

    def _dirty_dot_leader_pages(self):
        page_dirty = [0] * len(self.page_images)
        for b in self.boxes:
            if re.search(r"··", b["text"]):
                page_dirty[b["page_number"] - 1] += 1
        return {i + 1 for i, t in enumerate(page_dirty) if t > 3}

    def _remove_pages(self, page_numbers):
        i = 0
        while i < len(self.boxes):
            if self.boxes[i]["page_number"] in page_numbers:
                self.boxes.pop(i)
                continue
            i += 1

    def _filter_forpages(self):
        # Remove content boxes from irrelevant pages like "Table of Contents"
        if not self.boxes:
            return
        if self._remove_toc_pages():
            return
        # If table of contents not found, exclude page numbers by detecting abnormal formats like "··"
        page_dirty = self._dirty_dot_leader_pages()
        if not page_dirty:
            return
        self._remove_pages(page_dirty)

    def _merge_with_same_bullet(self):
        # Merge adjacent boxes starting with the same bullet point
        i = 0
        while i + 1 < len(self.boxes):
            b = self.boxes[i]
            b_ = self.boxes[i + 1]
            if not b["text"].strip():
                self.boxes.pop(i)
                continue
            if not b_["text"].strip():
                self.boxes.pop(i + 1)
                continue
            # Merge current box content into next box
            if (
                b["text"].strip()[0] != b_["text"].strip()[0]
                or b["text"].strip()[0].lower() in set("qwertyuopasdfghjklzxcvbnm")
                or rag_tokenizer.is_chinese(b["text"].strip()[0])
                or b["top"] > b_["bottom"]
            ):
                i += 1
                continue
            b_["text"] = b["text"] + "\n" + b_["text"]
            b_["x0"] = min(b["x0"], b_["x0"])
            b_["x1"] = max(b["x1"], b_["x1"])
            b_["top"] = b["top"]
            self.boxes.pop(i)

    @staticmethod
    def _layout_group_key(box):
        return str(box["page_number"]) + "-" + str(box["layoutno"])

    @staticmethod
    def _is_source_note_box(box):
        return re.match(r"(数据|资料|图表)*来源[:： ]", box["text"])

    @staticmethod
    def _is_no_merge_layout_box(box):
        return is_table_caption(box) or box["layout_type"] in [
            "table caption",
            "title",
            "figure caption",
            "reference",
        ]

    @staticmethod
    def _x_overlapped(a, b):
        return not any([a["x1"] < b["x0"], a["x0"] > b["x1"]])

    def _collect_table_figure_groups(self, need_image):
        tables, figures, nomerge_lout_no = {}, {}, []
        i = 0
        lst_lout_no = ""
        while i < len(self.boxes):
            box = self.boxes[i]
            if "layoutno" not in box:
                i += 1
                continue
            lout_no = self._layout_group_key(box)
            if self._is_no_merge_layout_box(box):
                nomerge_lout_no.append(lst_lout_no)

            target = None
            if box["layout_type"] == "table":
                target = tables
            elif need_image and box["layout_type"] == "figure":
                target = figures

            if target is None:
                i += 1
                continue
            if self._is_source_note_box(box):
                self.boxes.pop(i)
                continue
            target.setdefault(lout_no, []).append(box)
            self.boxes.pop(i)
            lst_lout_no = lout_no
        return tables, figures, set(nomerge_lout_no)

    def _table_groups_can_merge(self, k0, bxs0, bxs, nomerge_lout_no):
        if k0 in nomerge_lout_no:
            return False
        if bxs[0]["page_number"] == bxs0[0]["page_number"]:
            return False
        if bxs[0]["page_number"] - bxs0[0]["page_number"] > 1:
            return False
        mh = self.mean_height[bxs[0]["page_number"] - 1]
        return self._y_dis(bxs0[-1], bxs[0]) <= mh * 23

    def _merge_cross_page_tables(self, tables, nomerge_lout_no):
        tbls = sorted(tables.items(), key=lambda x: (x[1][0]["top"], x[1][0]["x0"]))
        i = len(tbls) - 1
        while i - 1 >= 0:
            k0, bxs0 = tbls[i - 1]
            k, bxs = tbls[i]
            i -= 1
            if not self._table_groups_can_merge(k0, bxs0, bxs, nomerge_lout_no):
                continue
            tables[k0].extend(tables[k])
            del tables[k]

    def _nearest_layout_group(self, caption, groups):
        mink = ""
        minv = 1000000000
        for key, boxes in groups.items():
            for box in boxes:
                if box.get("layout_type", "").find("caption") >= 0:
                    continue
                y_dis = self._y_dis(caption, box)
                x_dis = 0 if self._x_overlapped(caption, box) else self._x_dis(caption, box)
                dis = y_dis * y_dis + x_dis * x_dis
                if dis < minv:
                    mink = key
                    minv = dis
        return mink, minv

    def _attach_caption_to_nearest_group(self, caption, tables, figures):
        tk, tv = self._nearest_layout_group(caption, tables)
        fk, fv = self._nearest_layout_group(caption, figures)
        if tv < fv and tk:
            tables[tk].insert(0, caption)
            logging.debug("Attached table caption: chars=%s group=%s", len(caption["text"]), tk)
            return True
        elif fk:
            figures[fk].insert(0, caption)
            logging.debug("Attached figure caption: chars=%s group=%s", len(caption["text"]), fk)
            return True
        return False

    def _attach_table_figure_captions(self, tables, figures):
        i = 0
        while i < len(self.boxes):
            caption = self.boxes[i]
            if not is_table_caption(caption):
                i += 1
                continue
            if self._attach_caption_to_nearest_group(caption, tables, figures):
                self.boxes.pop(i)
            else:
                i += 1

    def _layout_group_bounds(self, boxes, page_index, layout_type):
        height_offset = self.page_cum_height[page_index]
        bounds = {
            "x0": np.min([b["x0"] for b in boxes]),
            "top": np.min([b["top"] for b in boxes]) - height_offset,
            "x1": np.max([b["x1"] for b in boxes]),
            "bottom": np.max([b["bottom"] for b in boxes]) - height_offset,
        }
        layouts = [layout for layout in self.page_layout[page_index] if layout["type"] == layout_type]
        ii = Recognizer.find_overlapped(bounds, layouts, naive=True)
        if ii is not None:
            return layouts[ii]
        logging.warning(f"Missing layout match: {page_index + 1},%s" % (boxes[0].get("layoutno", "")))
        return bounds

    def _crop_single_layout_group(self, boxes, layout_type, positions, zoom):
        page_index = next(iter({b["page_number"] - 1 for b in boxes}))
        bounds = self._layout_group_bounds(boxes, page_index, layout_type)
        left, top, right, bott = bounds["x0"], bounds["top"], bounds["x1"], bounds["bottom"]
        if right < left:
            right = left + 1
        positions.append((page_index + self.page_from, left, right, top, bott))
        return self.page_images[page_index].crop((left * zoom, top * zoom, right * zoom, bott * zoom))

    @staticmethod
    def _boxes_by_page_index(boxes):
        pages = {}
        for box in boxes:
            pages.setdefault(box["page_number"] - 1, []).append(box)
        return sorted(pages.items(), key=lambda x: x[0])

    @staticmethod
    def _compose_vertical_images(images):
        with ExitStack() as resources:
            pic = Image.new(
                "RGB",
                (int(np.max([img.size[0] for img in images])), int(np.sum([img.size[1] for img in images]))),
                (245, 245, 245),
            )
            resources.callback(pic.close)
            height = 0
            for img in images:
                pic.paste(img, (0, int(height)))
                height += img.size[1]
            resources.pop_all()
        return pic

    def _crop_layout_group(self, boxes, layout_type, positions, zoom):
        page_numbers = {b["page_number"] - 1 for b in boxes}
        if len(page_numbers) < 2:
            return self._crop_single_layout_group(boxes, layout_type, positions, zoom)
        with ExitStack() as result_owner:
            with ExitStack() as resources:
                images = []
                for _, arr in self._boxes_by_page_index(boxes):
                    image = self._crop_layout_group(arr, layout_type, positions, zoom)
                    resources.callback(image.close)
                    images.append(image)
                result = self._compose_vertical_images(images)
                result_owner.callback(result.close)
            result_owner.pop_all()
            return result

    def _append_figure_extracts(
        self,
        figures,
        zoom,
        separate_tables_figures,
        res,
        positions,
        figure_results,
        figure_positions,
    ):
        for _key, bxs in figures.items():
            txt = "\n".join([b["text"] for b in bxs])
            if not txt:
                continue

            poss = []
            result = (self._crop_layout_group(bxs, "figure", poss, zoom), [txt])
            if separate_tables_figures:
                figure_results.append(result)
                figure_positions.append(poss)
            else:
                res.append(result)
                positions.append(poss)

    def _append_table_extracts(self, tables, zoom, return_html, res, positions):
        for _key, bxs in tables.items():
            if not bxs:
                continue
            bxs = Recognizer.sort_y_firstly(bxs, np.mean([(b["bottom"] - b["top"]) / 2 for b in bxs]))

            poss = []

            content = construct_table_from_ocr_boxes(bxs, html=return_html, is_english=self.is_english)
            res.append((self._crop_layout_group(bxs, "table", poss, zoom), content))
            positions.append(poss)

    @staticmethod
    def _format_extract_result(
        res,
        positions,
        figure_results,
        figure_positions,
        separate_tables_figures,
        need_position,
    ):
        if separate_tables_figures:
            if len(positions) != len(res) or len(figure_positions) != len(figure_results):
                raise RuntimeError("Extracted table/figure positions must match result counts")
            if need_position:
                return (
                    list(zip(res, positions, strict=True)),
                    list(zip(figure_results, figure_positions, strict=True)),
                )
            return res, figure_results
        if len(positions) != len(res):
            raise RuntimeError("Extracted positions must match result count")
        if need_position:
            return list(zip(res, positions, strict=True))
        return res

    def _extract_table_figure(
        self,
        need_image,
        zoom,
        return_html,
        need_position,
        separate_tables_figures=False,
    ):
        tables, figures, nomerge_lout_no = self._collect_table_figure_groups(need_image)
        self._merge_cross_page_tables(tables, nomerge_lout_no)
        self._attach_table_figure_captions(tables, figures)

        res = []
        positions = []
        figure_results = []
        figure_positions = []
        with ExitStack() as resources:
            try:
                self._append_figure_extracts(
                    figures,
                    zoom,
                    separate_tables_figures,
                    res,
                    positions,
                    figure_results,
                    figure_positions,
                )
                self._append_table_extracts(tables, zoom, return_html, res, positions)
            finally:
                for image, _content in res + figure_results:
                    resources.callback(image.close)
            result = self._format_extract_result(
                res,
                positions,
                figure_results,
                figure_positions,
                separate_tables_figures,
                need_position,
            )
            resources.pop_all()
            return result

    def proj_match(self, line):
        if len(line) <= 2:
            return
        # If the entire line contains only numbers, spaces, punctuation, etc.,
        # consider it not a structured heading.
        if re.match(r"[0-9 ().,%+/-]+$", line):
            return False
        # Define a set of regex patterns and their corresponding labels for recognizing structured heading formats
        for p, j in [
            (r"第[零一二三四五六七八九十百]+章", 1),
            (r"第[零一二三四五六七八九十百]+[条节]", 2),
            (r"[零一二三四五六七八九十百]+[、 　]", 3),
            (r"[\(（][零一二三四五六七八九十百]+[）\)]", 4),
            (r"\d+(、|\.[　 ]|\.[^0-9])", 5),
            (r"\d+\.\d+(、|[. 　]|[^0-9])", 6),
            (r"\d+\.\d+\.\d+(、|[ 　]|[^0-9])", 7),
            (r"\d+\.\d+\.\d+\.\d+(、|[ 　]|[^0-9])", 8),
            (r".{,48}[：:?？]$", 9),
            (r"\d+）", 10),
            (r"[\(（]\d+[）\)]", 11),
            (r"[零一二三四五六七八九十百]+是", 12),
            (r"[⚫•➢✓]", 12),
        ]:
            if re.match(p, line):
                return j

    def _line_tag(self, bx, zoom):
        pn = [bx["page_number"]]
        top = bx["top"] - self.page_cum_height[pn[0] - 1]
        bott = bx["bottom"] - self.page_cum_height[pn[0] - 1]
        page_images_cnt = len(self.page_images)
        if pn[-1] - 1 >= page_images_cnt:
            return ""
        while bott * zoom > self.page_images[pn[-1] - 1].size[1]:
            bott -= self.page_images[pn[-1] - 1].size[1] / zoom
            pn.append(pn[-1] + 1)
            if pn[-1] - 1 >= page_images_cnt:
                return ""

        return "@@{}\t{:.1f}\t{:.1f}\t{:.1f}\t{:.1f}##".format(
            "-".join([str(p) for p in pn]), bx["x0"], bx["x1"], top, bott
        )

    @staticmethod
    def _scrap_box_width(box):
        return box["x1"] - box["x0"]

    @staticmethod
    def _scrap_box_height(box):
        return box["bottom"] - box["top"]

    def _is_useful_scrap_box(self, box, zoom):
        if box.get("layout_type"):
            return True
        if self._scrap_box_width(box) > self.page_images[box["page_number"] - 1].size[0] / zoom / 3:
            return True
        return box["bottom"] - box["top"] > self.mean_height[box["page_number"] - 1]

    def _scrap_scan_should_stop(self, line, box, has_major_project, mh):
        if (box["page_number"] - line["page_number"]) > 0:
            return True
        return not has_major_project and self._y_dis(line, box) >= 3 * mh and self._scrap_box_height(line) < 1.5 * mh

    def _collect_scrap_lines(self, boxes, line, start, lines, widths, mh, pw, zoom):
        lines.append(line)
        widths.append(self._scrap_box_width(line))
        has_major_project = self.proj_match(line["text"]) or line.get("layout_type", "") == "title"
        for i in range(start + 1, min(start + 20, len(boxes))):
            if self._scrap_scan_should_stop(line, boxes[i], has_major_project, mh):
                break
            if not self._is_useful_scrap_box(boxes[i], zoom):
                continue
            if has_major_project or self._x_dis(boxes[i], line) < pw / 10:
                self._collect_scrap_lines(boxes, boxes[i], i, lines, widths, mh, pw, zoom)
                boxes.pop(i)
                break

    def _scrap_group_should_keep(self, first_box, widths, page_width):
        major_project = self.proj_match(first_box["text"]) or first_box.get("layout_type", "") == "title"
        mean_width = np.mean(widths)
        return major_project or mean_width / page_width >= 0.35 or mean_width > 200

    def __filterout_scraps(self, boxes, zoom):
        res = []
        while boxes:
            lines = []
            widths = []
            page_width = self.page_images[boxes[0]["page_number"] - 1].size[0] / zoom
            mean_height = self.mean_height[boxes[0]["page_number"] - 1]
            first_box = boxes[0]
            try:
                if self._is_useful_scrap_box(first_box, zoom):
                    self._collect_scrap_lines(boxes, first_box, 0, lines, widths, mean_height, page_width, zoom)
                else:
                    logging.debug("Discarded PDF scrap: chars=%s", len(first_box["text"]))
            except Exception as exc:
                logging.debug("Failed to collect PDF scrap lines: %s", exc)
            boxes.pop(0)
            if self._scrap_group_should_keep(first_box, widths, page_width):
                res.append("\n".join([c["text"] + self._line_tag(c, zoom) for c in lines]))
            else:
                logging.debug(
                    "Removed PDF scrap group: boxes=%s chars=%s", len(lines), sum(len(c["text"]) for c in lines)
                )

        return "\n\n".join(res)

    def _reset_image_state(self, page_from):
        self.close_images()
        self.total_page = 0
        self.lefted_chars = []
        self.mean_height = []
        self.mean_width = []
        self.boxes = []
        self.garbages = {}
        self.page_cum_height = [0]
        self.page_layout = []
        self.page_from = page_from

    def _load_pdf_page_images_and_chars(self, fnm, zoomin, page_from, page_to):
        pdfplumber_pdf = None
        try:
            with sys.modules[LOCK_KEY_pdfplumber]:
                pdfplumber_pdf = pdfplumber.open(fnm) if isinstance(fnm, str) else pdfplumber.open(BytesIO(fnm))
                pages = pdfplumber_pdf.pages[page_from:page_to]
                for page in pages:
                    self.page_images.append(page.to_image(resolution=72 * zoomin).annotated)
                try:
                    self.page_chars = [[c for c in page.dedupe_chars().chars if self._has_color(c)] for page in pages]
                except Exception as e:
                    logging.warning(f"Failed to extract characters for pages {page_from}-{page_to}: {str(e)}")
                    self.page_chars = [[] for _ in pages]

                self.total_page = len(pdfplumber_pdf.pages)
                self.boxes = [None for _ in self.page_images]
        except BaseException:
            self.close_images()
            raise
        finally:
            if pdfplumber_pdf is not None:
                pdfplumber_pdf.close()

    def _collect_pdf_outline_entries(self, outlines, depth):
        for item in outlines:
            if isinstance(item, dict):
                self.outlines.append((item["/Title"], depth))
                continue
            self._collect_pdf_outline_entries(item, depth + 1)

    def _load_pdf_outlines(self, fnm):
        self.outlines = []
        self.pdf = None
        try:
            self.pdf = pdf2_read(fnm if isinstance(fnm, str) else BytesIO(fnm))
            self._collect_pdf_outline_entries(self.pdf.outline, 0)
        except Exception as e:
            logging.warning(f"Outlines exception: {e}")
        finally:
            if hasattr(self.pdf, "close"):
                self.pdf.close()
        if not self.outlines:
            logging.warning("Miss outlines")

    @staticmethod
    def _page_chars_look_english(page_chars):
        return re.search(
            r"[a-zA-Z0-9,/¸;:'\[\]\(\)!@#$%^&*\"?<>._-]{30,}",
            "".join(_evenly_sample([c["text"] for c in page_chars], min(100, len(page_chars)))),
        )

    def _detect_english_from_chars(self):
        english_pages = [self._page_chars_look_english(self.page_chars[i]) for i in range(len(self.page_chars))]
        return sum([1 if e else 0 for e in english_pages]) > len(self.page_images) / 2

    @staticmethod
    def _insert_ocr_char_spaces(chars):
        j = 0
        while j + 1 < len(chars):
            if (
                chars[j]["text"]
                and chars[j + 1]["text"]
                and re.match(r"[0-9a-zA-Z,.:;!%]+", chars[j]["text"] + chars[j + 1]["text"])
                and chars[j + 1]["x0"] - chars[j]["x1"] >= min(chars[j + 1]["width"], chars[j]["width"]) / 2
            ):
                chars[j]["text"] += " "
            j += 1

    def _prepare_image_ocr_chars(self, index, img, zoomin):
        chars = self.page_chars[index] if not self.is_english else []
        self.mean_height.append(np.median(sorted([c["height"] for c in chars])) if chars else 0)
        self.mean_width.append(np.median(sorted([c["width"] for c in chars])) if chars else 8)
        self.page_cum_height.append(img.size[1] / zoomin)
        return chars

    async def _run_image_ocr(self, index, device_id, img, chars, limiter, zoomin, callback):
        self._insert_ocr_char_spaces(chars)
        if limiter:
            async with limiter:
                await trio.to_thread.run_sync(lambda: self.__ocr(index + 1, img, chars, zoomin, device_id))
        else:
            self.__ocr(index + 1, img, chars, zoomin, device_id)

        if callback and index % 6 == 5:
            callback(prog=(index + 1) * 0.6 / len(self.page_images), msg="")

    async def _launch_parallel_image_ocr(self, zoomin, callback):
        device_count = max(1, len(self.parallel_limiter))
        async with trio.open_nursery() as nursery:
            for index, img in enumerate(self.page_images):
                chars = self._prepare_image_ocr_chars(index, img, zoomin)
                device_id = index % device_count
                nursery.start_soon(
                    self._run_image_ocr,
                    index,
                    device_id,
                    img,
                    chars,
                    self.parallel_limiter[device_id],
                    zoomin,
                    callback,
                )
                await trio.sleep(0.1)

    async def _launch_serial_image_ocr(self, zoomin, callback):
        for index, img in enumerate(self.page_images):
            chars = self._prepare_image_ocr_chars(index, img, zoomin)
            await self._run_image_ocr(index, 0, img, chars, None, zoomin, callback)

    async def _launch_image_ocr(self, zoomin, callback):
        if self.parallel_limiter:
            await self._launch_parallel_image_ocr(zoomin, callback)
        else:
            await self._launch_serial_image_ocr(zoomin, callback)

    def _run_image_ocr_tasks(self, zoomin, callback):
        start = timer()
        trio.run(self._launch_image_ocr, zoomin, callback)
        logging.info(f"__images__ {len(self.page_images)} pages cost {timer() - start}s")

    def _detect_english_from_ocr_boxes(self):
        boxes = [b for page_boxes in self.boxes for b in page_boxes]
        return re.search(
            r"[\na-zA-Z0-9,/¸;:'\[\]\(\)!@#$%^&*\"?<>._-]{30,}",
            "".join([b["text"] for b in _evenly_sample(boxes, min(30, len(boxes)))]),
        )

    def __images__(self, fnm, zoomin=3, page_from=0, page_to=299, callback=None):
        """
        Read PDF file into images;
        Extract characters, OCR results, header/footer structure for each page image;
        Used for subsequent layout analysis, table recognition and text merging.
        Use pdfplumber to extract page images and characters;
        Detect whether document is English (through character analysis);
        Asynchronously call __ocr to perform OCR recognition;
        Calculate average character width/height, accumulate page image heights for cross-page processing.
        """
        self._reset_image_state(page_from)
        start = timer()
        self._load_pdf_page_images_and_chars(fnm, zoomin, page_from, page_to)
        logging.info(f"__images__ dedupe_chars cost {timer() - start}s")

        self._load_pdf_outlines(fnm)

        logging.debug("Images converted.")
        self.is_english = self._detect_english_from_chars()
        self._run_image_ocr_tasks(zoomin, callback)
        self.boxes = [page_boxes or [] for page_boxes in self.boxes]

        if not self.is_english and not any(self.page_chars) and self.boxes:
            self.is_english = self._detect_english_from_ocr_boxes()

        logging.debug("Is it English: %s", self.is_english)

        self.page_cum_height = np.cumsum(self.page_cum_height)
        if len(self.page_cum_height) != len(self.page_images) + 1:
            raise RuntimeError("Cumulative page heights must include a leading zero plus one entry per page")
        if len(self.boxes) == 0 and zoomin < 9:
            self.__images__(fnm, zoomin * 3, page_from, page_to, callback)

    # Entry function, responsible for extracting all structured content from PDF.

    def __call__(self, fnm, need_image=True, zoomin=3, return_html=False):
        """
        Call __images__ to load images and perform OCR;
        _layouts_rec() to get page layout structure;
        _table_transformer_job() to extract table components;
        _text_merge() and _concat_downward() to merge body text;
        _filter_forpages() to remove invalid pages like table of contents;
        _extract_table_figure() to extract final table/image information.
        """
        self.__images__(fnm, zoomin)
        self._layouts_rec(zoomin)
        self._table_transformer_job(zoomin)
        self._text_merge()
        self._concat_downward()
        self._filter_forpages()
        tbls = self._extract_table_figure(need_image, zoomin, return_html, False)
        with ExitStack() as resources:
            for image, _content in tbls:
                resources.callback(image.close)
            result = self.__filterout_scraps(deepcopy(self.boxes), zoomin), tbls
            resources.pop_all()
            return result

    @staticmethod
    def _parse_crop_positions(text):
        positions = []
        for tag in re.findall(r"@@[0-9-]+\t[0-9.\t]+##", text):
            pn, left, right, top, bottom = tag.strip("#").strip("@").split("\t")
            left, right, top, bottom = float(left), float(right), float(top), float(bottom)
            positions.append(([int(p) - 1 for p in pn.split("-")], left, right, top, bottom))
        return positions

    def _add_crop_context_positions(self, positions, gap, zoom):
        pos = positions[0]
        positions.insert(0, ([pos[0][0]], pos[1], pos[2], max(0, pos[3] - 120), max(pos[3] - gap, 0)))
        pos = positions[-1]
        positions.append(
            (
                [pos[0][-1]],
                pos[1],
                pos[2],
                min(self.page_images[pos[0][-1]].size[1] / zoom, pos[4] + gap),
                min(self.page_images[pos[0][-1]].size[1] / zoom, pos[4] + 120),
            )
        )

    def _append_crop_position_images(self, imgs, positions, pns, left, top, bottom, max_width, zoom, is_content):
        right = left + max_width
        bottom *= zoom
        for pn in pns[1:]:
            bottom += self.page_images[pn - 1].size[1]
        imgs.append(
            self.page_images[pns[0]].crop(
                (left * zoom, top * zoom, right * zoom, min(bottom, self.page_images[pns[0]].size[1]))
            )
        )
        if is_content:
            positions.append(
                (pns[0] + self.page_from, left, right, top, min(bottom, self.page_images[pns[0]].size[1]) / zoom)
            )

        bottom -= self.page_images[pns[0]].size[1]
        for pn in pns[1:]:
            imgs.append(
                self.page_images[pn].crop((left * zoom, 0, right * zoom, min(bottom, self.page_images[pn].size[1])))
            )
            if is_content:
                positions.append(
                    (pn + self.page_from, left, right, 0, min(bottom, self.page_images[pn].size[1]) / zoom)
                )
            bottom -= self.page_images[pn].size[1]

    def crop(self, text, zoom=3, need_position=False):
        # Crop corresponding regions from images based on @@...## tags in text
        imgs = []
        poss = self._parse_crop_positions(text)
        if not poss:
            if need_position:
                return None, None
            return

        max_width = max(np.max([right - left for (_, left, right, _, _) in poss]), 6)
        gap = 6
        self._add_crop_context_positions(poss, gap, zoom)

        positions = []
        with ExitStack() as result_owner:
            try:
                for ii, (pns, left, _right, top, bottom) in enumerate(poss):
                    self._append_crop_position_images(
                        imgs,
                        positions,
                        pns,
                        left,
                        top,
                        bottom,
                        max_width,
                        zoom,
                        0 < ii < len(poss) - 1,
                    )

                if not imgs:
                    if need_position:
                        return None, None
                    return
                pic = compose_context_images(imgs, gap)
                result_owner.callback(pic.close)
            finally:
                with ExitStack() as resources:
                    for image in imgs:
                        resources.callback(image.close)
            result_owner.pop_all()

        if need_position:
            return pic, positions
        return pic

    def get_position(self, bx, zoom):
        poss = []
        pn = bx["page_number"]
        top = bx["top"] - self.page_cum_height[pn - 1]
        bott = bx["bottom"] - self.page_cum_height[pn - 1]
        poss.append((pn, bx["x0"], bx["x1"], top, min(bott, self.page_images[pn - 1].size[1] / zoom)))
        while bott * zoom > self.page_images[pn - 1].size[1]:
            bott -= self.page_images[pn - 1].size[1] / zoom
            top = 0
            pn += 1
            poss.append((pn, bx["x0"], bx["x1"], top, min(bott, self.page_images[pn - 1].size[1] / zoom)))
        return poss


class VisionPdfParser(LayoutPdfParser):
    def __init__(self, vision_model):
        self.page_from = 0
        self.vision_model = vision_model
        self.page_images = []
        self.page_chars = []
        self.total_page = 0

    def __images__(self, fnm, zoomin=3, page_from=0, page_to=299, callback=None):
        self._reset_image_state(page_from)
        try:
            with (
                sys.modules[LOCK_KEY_pdfplumber],
                pdfplumber.open(fnm) if isinstance(fnm, str) else pdfplumber.open(BytesIO(fnm)) as pdf,
            ):
                self.pdf = pdf
                for page in self.pdf.pages[page_from:page_to]:
                    self.page_images.append(page.to_image(resolution=72 * zoomin).annotated)
                self.total_page = len(self.pdf.pages)
        except BaseException:
            self.close_images()
            raise

    def __call__(self, filename, from_page=0, to_page=100000, **kwargs):
        callback = kwargs.get("callback")
        if callback is None:
            callback = _noop_progress
        from_page = max(0, from_page)
        self.__images__(fnm=filename, zoomin=3, page_from=from_page, page_to=to_page, **kwargs)

        all_docs = []

        for pdf_page_num, img_binary in enumerate(self.page_images, start=from_page):
            # Use vision model to describe or structurally understand the image
            docs = describe_image_with_model(
                image=img_binary,
                vision_model=self.vision_model,
                prompt=page_transcription_prompt(page=pdf_page_num + 1),
                callback=callback,
            )

            if docs:
                all_docs.append(docs)
        return [(doc, "") for doc in all_docs], []


class GeneralLayoutPdfParser(LayoutPdfParser):
    def __call__(
        self, filename, binary=None, from_page=0, to_page=100000, zoomin=3, callback=None, separate_tables_figures=False
    ):
        if callback is None:
            callback = _noop_progress
        start = timer()
        first_start = start
        callback(msg="OCR started")
        self.__images__(filename if not binary else binary, zoomin, from_page, to_page, callback)
        callback(msg="OCR finished ({:.2f}s)".format(timer() - start))
        logging.info("OCR({}~{}): {:.2f}s".format(from_page, to_page, timer() - start))

        start = timer()
        self._layouts_rec(zoomin)
        callback(0.63, "Layout analysis ({:.2f}s)".format(timer() - start))

        start = timer()
        self._table_transformer_job(zoomin)
        callback(0.65, "Table analysis ({:.2f}s)".format(timer() - start))

        start = timer()
        self._text_merge()
        callback(0.67, "Text merged ({:.2f}s)".format(timer() - start))

        if separate_tables_figures:
            tbls, figures = self._extract_table_figure(True, zoomin, True, True, True)
            with ExitStack() as resources:
                for (image, _content), _positions in tbls + figures:
                    resources.callback(image.close)
                self._concat_downward()
                logging.info("layouts cost: {}s".format(timer() - first_start))
                result = [(b["text"], self._line_tag(b, zoomin)) for b in self.boxes], tbls, figures
                resources.pop_all()
                return result
        else:
            tbls = self._extract_table_figure(True, zoomin, True, True)
            with ExitStack() as resources:
                for (image, _content), _positions in tbls:
                    resources.callback(image.close)
                self._naive_vertical_merge()
                self._concat_downward()
                # self._filter_forpages()
                logging.info("layouts cost: {}s".format(timer() - first_start))
                result = [(b["text"], self._line_tag(b, zoomin)) for b in self.boxes], tbls
                resources.pop_all()
                return result


class BookLayoutPdfParser(LayoutPdfParser):
    def __call__(self, filename, binary=None, from_page=0, to_page=100000, zoomin=3, callback=None):
        from timeit import default_timer as timer

        if callback is None:
            callback = _noop_progress
        start = timer()
        callback(msg="OCR started")
        self.__images__(filename if not binary else binary, zoomin, from_page, to_page, callback)
        callback(msg="OCR finished ({:.2f}s)".format(timer() - start))

        start = timer()
        self._layouts_rec(zoomin)
        callback(0.67, "Layout analysis ({:.2f}s)".format(timer() - start))
        logging.debug("layouts: {}".format(timer() - start))

        start = timer()
        self._table_transformer_job(zoomin)
        callback(0.68, "Table analysis ({:.2f}s)".format(timer() - start))

        start = timer()
        self._text_merge()
        tbls = self._extract_table_figure(True, zoomin, True, True)
        with ExitStack() as resources:
            for (image, _content), _positions in tbls:
                resources.callback(image.close)
            self._naive_vertical_merge()
            self._filter_forpages()
            self._merge_with_same_bullet()
            callback(0.8, "Text extraction ({:.2f}s)".format(timer() - start))
            result = [(b["text"] + self._line_tag(b, zoomin), b.get("layoutno", "")) for b in self.boxes], tbls
            resources.pop_all()
            return result


class LegalLayoutPdfParser(LayoutPdfParser):
    def __init__(self):
        self.model_speciess = "laws"
        super().__init__()

    def __call__(self, filename, binary=None, from_page=0, to_page=100000, zoomin=3, callback=None):
        from timeit import default_timer as timer

        if callback is None:
            callback = _noop_progress
        start = timer()
        callback(msg="OCR started")
        self.__images__(filename if not binary else binary, zoomin, from_page, to_page, callback)
        callback(msg="OCR finished ({:.2f}s)".format(timer() - start))

        start = timer()
        self._layouts_rec(zoomin)
        callback(0.67, "Layout analysis ({:.2f}s)".format(timer() - start))
        logging.debug("layouts:".format())
        self._naive_vertical_merge()

        callback(0.8, "Text extraction ({:.2f}s)".format(timer() - start))

        return [(b["text"], self._line_tag(b, zoomin)) for b in self.boxes], None
