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

import os
import re
from collections import Counter
from copy import deepcopy

import cv2
import numpy as np

from .operators import nms
from .recognizer import Recognizer

_FIGURE_CAPTION_LABEL = "Figure caption"
_TABLE_CAPTION_LABEL = "Table caption"


def get_default_resource_dir():
    """
    Return the repo-bundled layout model directory.
    """
    resource_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../resources/models/layout"))
    return resource_dir


class LayoutRecognizer(Recognizer):
    labels = [
        "_background_",
        "Text",
        "Title",
        "Figure",
        _FIGURE_CAPTION_LABEL,
        "Table",
        _TABLE_CAPTION_LABEL,
        "Header",
        "Footer",
        "Reference",
        "Equation",
    ]

    def __init__(self, domain):
        super().__init__(self.labels, domain, get_default_resource_dir())
        self.garbage_layouts = ["footer", "header", "reference"]

    @staticmethod
    def _is_garbage_box(box):
        patterns = [
            r"^•+$",
            "^\\d{1,2} / ?\\d{1,2}$",
            r"^\d{1,2} of \d{1,2}$",
            "^http://[^ ]{12,}",
            "\\(cid *: *\\d+ *\\)",
        ]
        return any(re.search(pattern, box["text"]) for pattern in patterns)

    @staticmethod
    def _build_page_layouts(layouts, page_number, scale_factor, garbage_layouts):
        return [
            {
                "type": box["type"],
                "score": float(box["score"]),
                "x0": box["bbox"][0] / scale_factor,
                "x1": box["bbox"][2] / scale_factor,
                "top": box["bbox"][1] / scale_factor,
                "bottom": box["bbox"][-1] / scale_factor,
                "page_number": page_number,
            }
            for box in layouts
            if float(box["score"]) >= 0.4 or box["type"] not in garbage_layouts
        ]

    def _keep_garbage_layout_box(self, layout, box, image_height, scale_factor):
        return any(
            [
                layout["type"] == "footer" and box["bottom"] < image_height * 0.9 / scale_factor,
                layout["type"] == "header" and box["top"] > image_height * 0.1 / scale_factor,
            ]
        )

    def _assign_layout_type(self, boxes, layouts, image_height, scale_factor, garbages, ty, drop):
        layouts_of_type = [layout for layout in layouts if layout["type"] == ty]
        index = 0
        while index < len(boxes):
            if boxes[index].get("layout_type"):
                index += 1
                continue
            if self._is_garbage_box(boxes[index]):
                boxes.pop(index)
                continue

            match_index = self.find_overlapped_with_threashold(boxes[index], layouts_of_type, thr=0.4)
            if match_index is None:
                boxes[index]["layout_type"] = ""
                index += 1
                continue

            layout = layouts_of_type[match_index]
            layout["visited"] = True
            if (
                drop
                and layout["type"] in self.garbage_layouts
                and not self._keep_garbage_layout_box(layout, boxes[index], image_height, scale_factor)
            ):
                garbages.setdefault(layout["type"], []).append(boxes[index]["text"])
                boxes.pop(index)
                continue

            boxes[index]["layoutno"] = f"{ty}-{match_index}"
            boxes[index]["layout_type"] = "figure" if layout["type"] == "equation" else layout["type"]
            index += 1

    @staticmethod
    def _append_unvisited_figure_layouts(boxes, layouts):
        for index, layout in enumerate([lt for lt in layouts if lt["type"] in ["figure", "equation"]]):
            if layout.get("visited"):
                continue
            figure_layout = deepcopy(layout)
            del figure_layout["type"]
            figure_layout["text"] = ""
            figure_layout["layout_type"] = "figure"
            figure_layout["layoutno"] = f"figure-{index}"
            boxes.append(figure_layout)

    @staticmethod
    def _deduplicate_garbage_texts(garbages):
        garbage_set = set()
        for key, values in garbages.items():
            garbages[key] = Counter(values)
            for value, count in garbages[key].items():
                if count > 1:
                    garbage_set.add(value)
        return garbage_set

    def __call__(self, image_list, ocr_res, scale_factor=3, thr=0.2, batch_size=16, drop=True):
        layouts = super().__call__(image_list, thr, batch_size)
        # save_results(image_list, layouts, self.labels, output_dir='output/', threshold=0.7)
        if len(image_list) != len(ocr_res):
            raise ValueError("Image list and OCR result counts must match")
        # Tag layout type
        boxes = []
        if len(image_list) != len(layouts):
            raise RuntimeError("Image list and detected layout counts must match")
        garbages = {}
        page_layout = []
        for pn, lts in enumerate(layouts):
            bxs = ocr_res[pn]
            lts = self._build_page_layouts(lts, pn, scale_factor, self.garbage_layouts)
            lts = self.sort_y_firstly(lts, np.mean([lt["bottom"] - lt["top"] for lt in lts]) / 2)
            lts = self.layouts_cleanup(bxs, lts)
            page_layout.append(lts)

            for lt in [
                "footer",
                "header",
                "reference",
                "figure caption",
                "table caption",
                "title",
                "table",
                "text",
                "figure",
                "equation",
            ]:
                self._assign_layout_type(
                    bxs,
                    lts,
                    image_list[pn].size[1],
                    scale_factor,
                    garbages,
                    lt,
                    drop,
                )
            self._append_unvisited_figure_layouts(bxs, lts)

            boxes.extend(bxs)

        ocr_res = boxes

        garbag_set = self._deduplicate_garbage_texts(garbages)
        ocr_res = [b for b in ocr_res if b["text"].strip() not in garbag_set]
        return ocr_res, page_layout

    def forward(self, image_list, thr=0.7, batch_size=16):
        return super().__call__(image_list, thr, batch_size)


class LayoutRecognizer4YOLOv10(LayoutRecognizer):
    labels = [
        "title",
        "Text",
        "Reference",
        "Figure",
        _FIGURE_CAPTION_LABEL,
        "Table",
        _TABLE_CAPTION_LABEL,
        _TABLE_CAPTION_LABEL,
        "Equation",
        _FIGURE_CAPTION_LABEL,
    ]

    def __init__(self, domain):
        _ = domain
        super().__init__("layout")
        self.auto = False
        self.scaleFill = False
        self.scaleup = True
        self.stride = 32
        self.center = True

    def preprocess(self, image_list):
        inputs = []
        new_shape = self.input_shape  # height, width
        for img in image_list:
            shape = img.shape[:2]  # current shape [height, width]
            # Scale ratio (new / old)
            r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
            # Compute padding
            new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
            dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]  # wh padding
            dw /= 2  # divide padding into 2 sides
            dh /= 2
            ww, hh = new_unpad
            img = np.array(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).astype(np.float32)
            img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
            top, bottom = int(round(dh - 0.1)) if self.center else 0, int(round(dh + 0.1))
            left, right = int(round(dw - 0.1)) if self.center else 0, int(round(dw + 0.1))
            img = cv2.copyMakeBorder(
                img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114)
            )  # add border
            img /= 255.0
            img = img.transpose(2, 0, 1)
            img = img[np.newaxis, :, :, :].astype(np.float32)
            inputs.append({self.input_names[0]: img, "scale_factor": [shape[1] / ww, shape[0] / hh, dw, dh]})

        return inputs

    def postprocess(self, boxes, inputs, thr):
        _ = thr
        effective_thr = 0.08
        boxes = np.squeeze(boxes)
        scores = boxes[:, 4]
        boxes = boxes[scores > effective_thr, :]
        scores = scores[scores > effective_thr]
        if len(boxes) == 0:
            return []
        class_ids = boxes[:, -1].astype(int)
        boxes = boxes[:, :4]
        boxes[:, 0] -= inputs["scale_factor"][2]
        boxes[:, 2] -= inputs["scale_factor"][2]
        boxes[:, 1] -= inputs["scale_factor"][3]
        boxes[:, 3] -= inputs["scale_factor"][3]
        input_shape = np.array(
            [inputs["scale_factor"][0], inputs["scale_factor"][1], inputs["scale_factor"][0], inputs["scale_factor"][1]]
        )
        boxes = np.multiply(boxes, input_shape, dtype=np.float32)

        unique_class_ids = np.unique(class_ids)
        indices = []
        for class_id in unique_class_ids:
            class_indices = np.nonzero(class_ids == class_id)[0]
            class_boxes = boxes[class_indices, :]
            class_scores = scores[class_indices]
            class_keep_boxes = nms(class_boxes, class_scores, 0.45)
            indices.extend(class_indices[class_keep_boxes])

        return [
            {
                "type": self.label_list[class_ids[i]].lower(),
                "bbox": [float(t) for t in boxes[i].tolist()],
                "score": float(scores[i]),
            }
            for i in indices
        ]
