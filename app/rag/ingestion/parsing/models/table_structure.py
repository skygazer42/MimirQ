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
from pathlib import Path

import numpy as np

from app.rag.ingestion.parsing.models.recognizer import Recognizer

_TABLE_COLUMN_LABEL = "table column"
_TABLE_MODEL_DIR = Path(__file__).resolve().parents[1] / "resources" / "models" / "table"


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
        super().__init__(self.labels, "tsr", str(_TABLE_MODEL_DIR))

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
            if not self._align_row_bounds(lts):
                # The caller restores coordinates by the original crop index.
                res.append([])
                continue
            self._align_column_bounds(lts)
            res.append(lts)
        return res
