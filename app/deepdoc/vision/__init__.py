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
import io
import os
import sys
import threading

import pdfplumber

from .layout_recognizer import LayoutRecognizer4YOLOv10 as LayoutRecognizer
from .ocr import OCR
from .recognizer import Recognizer
from .table_structure_recognizer import TableStructureRecognizer

LOCK_KEY_pdfplumber = "global_shared_lock_pdfplumber"
if LOCK_KEY_pdfplumber not in sys.modules:
    sys.modules[LOCK_KEY_pdfplumber] = threading.Lock()


def traversal_files(base):
    for root, ds, fs in os.walk(base):
        for f in fs:
            fullname = os.path.join(root, f)
            yield fullname


def _render_pdf_pages(fnm, zoomin=3):
    pdf = None
    try:
        with sys.modules[LOCK_KEY_pdfplumber]:
            pdf = pdfplumber.open(fnm)
            return [page.to_image(resolution=72 * zoomin).annotated for page in pdf.pages]
    finally:
        if pdf is not None:
            pdf.close()


def _read_image(fnm, image_module, traceback_module):
    try:
        with open(fnm, "rb") as fp:
            binary = fp.read()
        return image_module.open(io.BytesIO(binary)).convert("RGB")
    except Exception:
        traceback_module.print_exc()
        return None


def _append_input(fnm, images, outputs, image_module, traceback_module):
    if fnm.split(".")[-1].lower() == "pdf":
        images = _render_pdf_pages(fnm)
        outputs.extend(os.path.split(fnm)[-1] + f"_{index}.jpg" for index in range(len(images)))
        return images

    image = _read_image(fnm, image_module, traceback_module)
    if image is not None:
        images.append(image)
        outputs.append(os.path.split(fnm)[-1])
    return images


def init_in_out(args):
    import traceback

    from PIL import Image

    images = []
    outputs = []

    if not os.path.exists(args.output_dir):
        os.mkdir(args.output_dir)

    if os.path.isdir(args.inputs):
        input_files = traversal_files(args.inputs)
    else:
        input_files = (args.inputs,)

    for fnm in input_files:
        images = _append_input(fnm, images, outputs, Image, traceback)

    outputs = [os.path.join(args.output_dir, output) for output in outputs]

    return images, outputs


__all__ = [
    "OCR",
    "Recognizer",
    "LayoutRecognizer",
    "TableStructureRecognizer",
    "init_in_out",
]
