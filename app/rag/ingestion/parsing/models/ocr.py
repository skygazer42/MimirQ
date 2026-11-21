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

import copy
import logging
import math
import os
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

from app.rag.ingestion.parsing.models.image_operators import DetResizeForTest, KeepKeys, NormalizeImage, ToCHWImage
from app.rag.ingestion.parsing.models.ocr_postprocess import CTCLabelDecode, DBPostProcess

loaded_models = {}

PARALLEL_DEVICES = 1
_OCR_MODEL_DIR = Path(__file__).resolve().parents[1] / "resources" / "models" / "ocr"


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 1024) -> int:
    raw = os.environ.get(name)
    value = int(raw) if raw is not None else default
    return max(min_value, min(max_value, value))


def _env_float(name: str, default: float, *, min_value: float = 0.0, max_value: float = 1000.0) -> float:
    raw = os.environ.get(name)
    value = float(raw) if raw is not None else default
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return max(min_value, min(max_value, value))


def resolve_model_file_path(model_dir, nm):
    model_dir_path = os.path.abspath(str(model_dir))
    direct = os.path.join(model_dir_path, nm + ".onnx")
    if os.path.exists(direct):
        return Path(direct)
    nested = {
        "det": os.path.join(model_dir_path, "PP-OCRv4", "PP-OCRv4", "ch_PP-OCRv4_det_infer.onnx"),
        "rec": os.path.join(model_dir_path, "PP-OCRv4", "PP-OCRv4", "ch_PP-OCRv4_rec_infer.onnx"),
    }.get(str(nm))
    if nested and os.path.exists(nested):
        return Path(nested)
    return Path(direct)


def _deepdoc_onnx_gpu_enabled() -> bool:
    return str(os.environ.get("DEEPDOC_ONNX_USE_GPU", "")).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_cuda_device_id(device_id: int | None) -> int | None:
    if not _deepdoc_onnx_gpu_enabled():
        return None
    candidate = 0 if device_id is None else int(device_id)
    if "CUDAExecutionProvider" not in ort.get_available_providers():
        return None
    return candidate


def _model_cache_tag(model_file_path: str, cuda_device_id: int | None) -> str:
    if cuda_device_id is None:
        return f"{model_file_path}:cpu"
    return f"{model_file_path}:cuda:{cuda_device_id}"


def _base_session_options():
    options = ort.SessionOptions()
    options.enable_cpu_mem_arena = False
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 2
    return options


def _cpu_session(model_file_path: str, options):
    run_options = ort.RunOptions()
    session = ort.InferenceSession(model_file_path, options=options, providers=["CPUExecutionProvider"])
    run_options.add_run_config_entry("memory.enable_memory_arena_shrinkage", "cpu")
    logging.info(f"load_model {model_file_path} uses CPU")
    return session, run_options


def _gpu_session(model_file_path: str, options, cuda_device_id: int):
    run_options = ort.RunOptions()
    gpu_mem_limit_mb = int(os.environ.get("DEEPDOC_ONNX_GPU_MEM_LIMIT_MB", "2048"))
    cuda_provider_options = {
        "device_id": cuda_device_id,
        "gpu_mem_limit": gpu_mem_limit_mb * 1024 * 1024,
        "arena_extend_strategy": "kNextPowerOfTwo",
    }
    session = ort.InferenceSession(
        model_file_path,
        options=options,
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        provider_options=[cuda_provider_options, {}],
    )
    run_options.add_run_config_entry("memory.enable_memory_arena_shrinkage", "gpu:" + str(cuda_device_id))
    logging.info(f"load_model {model_file_path} uses GPU")
    return session, run_options


def _load_inference_session(model_file_path: str, options, cuda_device_id: int | None):
    if cuda_device_id is None:
        return _cpu_session(model_file_path, options)
    try:
        return _gpu_session(model_file_path, options, cuda_device_id)
    except Exception as exc:
        logging.warning("load_model %s GPU unavailable, falling back to CPU: %s", model_file_path, str(exc)[:200])
        return _cpu_session(model_file_path, options)


def load_model(model_dir, nm, device_id: int | None = None):
    model_file_path = str(resolve_model_file_path(model_dir, nm))

    if not os.path.exists(model_file_path):
        raise FileNotFoundError(
            f"DeepDoc model file is missing: {model_file_path}. Run `make models` before local parsing."
        )
    cuda_device_id = _resolve_cuda_device_id(device_id)
    model_cached_tag = _model_cache_tag(model_file_path, cuda_device_id)

    global loaded_models
    loaded_model = loaded_models.get(model_cached_tag)
    if loaded_model:
        logging.info(f"load_model {model_file_path} reuses cached model")
        return loaded_model

    # https://github.com/microsoft/onnxruntime/issues/9509#issuecomment-951546580
    # Shrink provider memory after execution.
    options = _base_session_options()
    sess, run_options = _load_inference_session(model_file_path, options, cuda_device_id)
    loaded_model = (sess, run_options)
    loaded_models[model_cached_tag] = loaded_model
    return loaded_model


class TextRecognizer:
    def __init__(self, model_dir, device_id: int | None = None):
        self.rec_image_shape = [int(v) for v in "3, 48, 320".split(",")]
        self.rec_batch_num = _env_int("DEEPDOC_OCR_REC_BATCH_SIZE", 16, min_value=1, max_value=256)
        self.rec_width_bucket_ratio = _env_float(
            "DEEPDOC_OCR_REC_WIDTH_BUCKET_RATIO",
            1.0,
            min_value=0.0,
            max_value=32.0,
        )
        self.last_profile: dict[str, object] = {}
        self.postprocess_op = CTCLabelDecode(
            character_dict_path=os.path.join(model_dir, "ocr.res"), use_space_char=True
        )
        self.predictor, self.run_options = load_model(model_dir, "rec", device_id)
        self.input_tensor = self.predictor.get_inputs()[0]

    def resize_norm_img(self, img, max_wh_ratio):
        img_c, img_h, img_w = self.rec_image_shape

        if img_c != img.shape[2]:
            raise ValueError("Recognizer image channel count does not match configured shape")
        img_w = int((img_h * max_wh_ratio))
        w = self.input_tensor.shape[3:][0]
        if not isinstance(w, str) and w is not None and w > 0:
            img_w = w
        h, w = img.shape[:2]
        ratio = w / float(h)
        if math.ceil(img_h * ratio) > img_w:
            resized_w = img_w
        else:
            resized_w = int(math.ceil(img_h * ratio))

        resized_image = cv2.resize(img, (resized_w, img_h))
        resized_image = resized_image.astype("float32")
        resized_image = resized_image.transpose((2, 0, 1)) / 255
        resized_image -= 0.5
        resized_image /= 0.5
        padding_im = np.zeros((img_c, img_h, img_w), dtype=np.float32)
        padding_im[:, :, 0:resized_w] = resized_image
        return padding_im

    def _effective_width_ratio(self, img) -> float:
        _img_c, img_h, img_w = self.rec_image_shape[:3]
        base_ratio = img_w / float(img_h or 1)
        h, w = img.shape[:2]
        return max(base_ratio, w / float(h or 1))

    @staticmethod
    def _width_bucket_key(width_ratio: float, bucket_ratio: float) -> float:
        if bucket_ratio <= 0:
            return width_ratio
        return math.ceil(width_ratio / bucket_ratio) * bucket_ratio

    def _recognition_batches(self, img_list, batch_num: int, bucket_ratio: float):
        indexed: list[tuple[int, float, float]] = []
        for index, img in enumerate(img_list):
            ratio = self._effective_width_ratio(img)
            indexed.append((index, ratio, self._width_bucket_key(ratio, bucket_ratio)))
        indexed.sort(key=lambda item: (item[2], item[1], item[0]))

        current_bucket: float | None = None
        current: list[tuple[int, float, float]] = []
        for item in indexed:
            bucket = item[2]
            if current and bucket != current_bucket:
                for start in range(0, len(current), batch_num):
                    yield current[start : start + batch_num]
                current = []
            current_bucket = bucket
            current.append(item)
        if current:
            for start in range(0, len(current), batch_num):
                yield current[start : start + batch_num]

    def __call__(self, img_list):
        img_num = len(img_list)
        rec_res = [["", 0.0] for _ in range(img_num)]
        batch_num = _env_int(
            "DEEPDOC_OCR_REC_BATCH_SIZE",
            self.rec_batch_num,
            min_value=1,
            max_value=256,
        )
        bucket_ratio = _env_float(
            "DEEPDOC_OCR_REC_WIDTH_BUCKET_RATIO",
            self.rec_width_bucket_ratio,
            min_value=0.0,
            max_value=32.0,
        )
        st = time.perf_counter()
        batch_profiles = []
        bucket_keys: set[float] = set()

        for batch in self._recognition_batches(img_list, batch_num, bucket_ratio):
            norm_img_batch = []
            batch_started = time.perf_counter()
            max_wh_ratio = max(item[1] for item in batch)
            bucket_key = batch[0][2] if batch else 0.0
            bucket_keys.add(bucket_key)
            for original_index, _ratio, _bucket in batch:
                norm_img = self.resize_norm_img(img_list[original_index], max_wh_ratio)
                norm_img = norm_img[np.newaxis, :]
                norm_img_batch.append(norm_img)
            norm_img_batch = np.concatenate(norm_img_batch)

            input_dict = {}
            input_dict[self.input_tensor.name] = norm_img_batch
            outputs = self.predictor.run(None, input_dict, self.run_options)
            preds = outputs[0]
            rec_result = self.postprocess_op(preds)
            if len(rec_result) != len(batch):
                raise RuntimeError("OCR recognition result count does not match input batch")
            for rno in range(len(rec_result)):
                rec_res[batch[rno][0]] = rec_result[rno]
            batch_profiles.append(
                {
                    "bucket": round(float(bucket_key), 4),
                    "size": len(batch),
                    "max_width_ratio": round(float(max_wh_ratio), 4),
                    "padded_width": int(norm_img_batch.shape[-1]),
                    "elapsed_ms": max(0, int(round((time.perf_counter() - batch_started) * 1000.0))),
                }
            )

        elapsed = time.perf_counter() - st
        self.last_profile = {
            "schema": "mimirq.deepdoc_ocr_recognition_profile.v1",
            "image_count": int(img_num),
            "batch_size": int(batch_num),
            "bucket_ratio": float(bucket_ratio),
            "bucket_count": len(bucket_keys),
            "batch_count": len(batch_profiles),
            "elapsed_ms": max(0, int(round(elapsed * 1000.0))),
            "batches": batch_profiles,
        }
        return rec_res, elapsed


class TextDetector:
    def __init__(self, model_dir, device_id: int | None = None):
        resize_options = {"limit_side_len": 960, "limit_type": "max"}
        self.postprocess_op = DBPostProcess(
            thresh=0.3,
            box_thresh=0.5,
            max_candidates=1000,
            unclip_ratio=1.5,
            use_dilation=False,
            score_mode="fast",
            box_type="quad",
        )
        self.predictor, self.run_options = load_model(model_dir, "det", device_id)
        self.input_tensor = self.predictor.get_inputs()[0]

        img_h, img_w = self.input_tensor.shape[2:]
        if (
            not isinstance(img_h, str)
            and not isinstance(img_w, str)
            and img_h is not None
            and img_w is not None
            and img_h > 0
            and img_w > 0
        ):
            resize_options = {"image_shape": [img_h, img_w]}
        self.preprocess_op = [
            DetResizeForTest(**resize_options),
            NormalizeImage(
                std=[0.229, 0.224, 0.225],
                mean=[0.485, 0.456, 0.406],
                scale=1.0 / 255.0,
                order="hwc",
            ),
            ToCHWImage(),
            KeepKeys(keep_keys=["image", "shape"]),
        ]

    def order_points_clockwise(self, pts):
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        tmp = np.delete(pts, (np.argmin(s), np.argmax(s)), axis=0)
        diff = np.diff(np.array(tmp), axis=1)
        rect[1] = tmp[np.argmin(diff)]
        rect[3] = tmp[np.argmax(diff)]
        return rect

    def clip_det_res(self, points, img_height, img_width):
        for pno in range(points.shape[0]):
            points[pno, 0] = int(min(max(points[pno, 0], 0), img_width - 1))
            points[pno, 1] = int(min(max(points[pno, 1], 0), img_height - 1))
        return points

    def filter_tag_det_res(self, dt_boxes, image_shape):
        img_height, img_width = image_shape[0:2]
        dt_boxes_new = []
        for box in dt_boxes:
            if isinstance(box, list):
                box = np.array(box)
            box = self.order_points_clockwise(box)
            box = self.clip_det_res(box, img_height, img_width)
            rect_width = int(np.linalg.norm(box[0] - box[1]))
            rect_height = int(np.linalg.norm(box[0] - box[3]))
            if rect_width <= 3 or rect_height <= 3:
                continue
            dt_boxes_new.append(box)
        dt_boxes = np.array(dt_boxes_new)
        return dt_boxes

    def __call__(self, img):
        image_shape = img.shape
        data = {"image": img}

        st = time.time()
        for operation in self.preprocess_op:
            data = operation(data)
        img, shape_list = data
        img = np.expand_dims(img, axis=0)
        shape_list = np.expand_dims(shape_list, axis=0)
        img = img.copy()
        input_dict = {}
        input_dict[self.input_tensor.name] = img
        outputs = self.predictor.run(None, input_dict, self.run_options)

        post_result = self.postprocess_op({"maps": outputs[0]}, shape_list)
        dt_boxes = post_result[0]["points"]
        dt_boxes = self.filter_tag_det_res(dt_boxes, image_shape)

        return dt_boxes, time.time() - st


class OCR:
    def __init__(self, model_dir=None):
        model_dir = model_dir or str(_OCR_MODEL_DIR)
        device_ids = range(PARALLEL_DEVICES) if PARALLEL_DEVICES is not None and PARALLEL_DEVICES > 0 else (0,)
        self.text_detector = [TextDetector(model_dir, device_id) for device_id in device_ids]
        self.text_recognizer = [TextRecognizer(model_dir, device_id) for device_id in device_ids]

        self.drop_score = 0.5
        self.crop_image_res_index = 0
        self.last_recognition_profile: dict[str, object] = {}

    def get_rotate_crop_image(self, img, points):
        """
        img_height, img_width = img.shape[0:2]
        left = int(np.min(points[:, 0]))
        right = int(np.max(points[:, 0]))
        top = int(np.min(points[:, 1]))
        bottom = int(np.max(points[:, 1]))
        img_crop = img[top:bottom, left:right, :].copy()
        points[:, 0] = points[:, 0] - left
        points[:, 1] = points[:, 1] - top
        """
        if len(points) != 4:
            raise ValueError("shape of points must be 4*2")
        img_crop_width = int(max(np.linalg.norm(points[0] - points[1]), np.linalg.norm(points[2] - points[3])))
        img_crop_height = int(max(np.linalg.norm(points[0] - points[3]), np.linalg.norm(points[1] - points[2])))
        pts_std = np.float32([[0, 0], [img_crop_width, 0], [img_crop_width, img_crop_height], [0, img_crop_height]])
        perspective_transform = cv2.getPerspectiveTransform(points, pts_std)
        dst_img = cv2.warpPerspective(
            img,
            perspective_transform,
            (img_crop_width, img_crop_height),
            borderMode=cv2.BORDER_REPLICATE,
            flags=cv2.INTER_CUBIC,
        )
        dst_img_height, dst_img_width = dst_img.shape[0:2]
        if dst_img_height * 1.0 / dst_img_width >= 1.5:
            dst_img = np.rot90(dst_img)
        return dst_img

    def sorted_boxes(self, dt_boxes):
        """
        Sort text boxes in order from top to bottom, left to right
        args:
            dt_boxes(array):detected text boxes with shape [4, 2]
        return:
            sorted boxes(array) with shape [4, 2]
        """
        num_boxes = dt_boxes.shape[0]
        _boxes = sorted(dt_boxes, key=lambda x: (x[0][1], x[0][0]))

        for i in range(num_boxes - 1):
            for j in range(i, -1, -1):
                if abs(_boxes[j + 1][0][1] - _boxes[j][0][1]) < 10 and (_boxes[j + 1][0][0] < _boxes[j][0][0]):
                    tmp = _boxes[j]
                    _boxes[j] = _boxes[j + 1]
                    _boxes[j + 1] = tmp
                else:
                    break
        return _boxes

    def detect(self, img, device_id: int | None = None):
        if device_id is None:
            device_id = 0

        time_dict = {"det": 0, "rec": 0, "cls": 0, "all": 0}

        if img is None:
            return None, None, time_dict

        start = time.time()
        dt_boxes, elapse = self.text_detector[device_id](img)
        time_dict["det"] = elapse

        if dt_boxes is None:
            end = time.time()
            time_dict["all"] = end - start
            return None, None, time_dict

        return zip(self.sorted_boxes(dt_boxes), [("", 0) for _ in range(len(dt_boxes))], strict=False)

    def recognize(self, ori_im, box, device_id: int | None = None):
        if device_id is None:
            device_id = 0

        img_crop = self.get_rotate_crop_image(ori_im, box)

        rec_res, _elapse = self.text_recognizer[device_id]([img_crop])
        text, score = rec_res[0]
        if score < self.drop_score:
            return ""
        return text

    def recognize_batch(self, img_list, device_id: int | None = None):
        if device_id is None:
            device_id = 0
        recognizer = self.text_recognizer[device_id]
        rec_res, _elapse = recognizer(img_list)
        self.last_recognition_profile = dict(recognizer.last_profile)
        texts = []
        for i in range(len(rec_res)):
            text, score = rec_res[i]
            if score < self.drop_score:
                text = ""
            texts.append(text)
        return texts

    def __call__(self, img, device_id=0, cls=True):
        time_dict = {"det": 0, "rec": 0, "cls": 0, "all": 0}
        if device_id is None:
            device_id = 0

        if img is None:
            return None, None, time_dict

        start = time.time()
        ori_im = img.copy()
        dt_boxes, elapse = self.text_detector[device_id](img)
        time_dict["det"] = elapse

        if dt_boxes is None:
            end = time.time()
            time_dict["all"] = end - start
            return None, None, time_dict

        img_crop_list = []

        dt_boxes = self.sorted_boxes(dt_boxes)

        for bno in range(len(dt_boxes)):
            tmp_box = copy.deepcopy(dt_boxes[bno])
            img_crop = self.get_rotate_crop_image(ori_im, tmp_box)
            img_crop_list.append(img_crop)

        recognizer = self.text_recognizer[device_id]
        rec_res, elapse = recognizer(img_crop_list)
        self.last_recognition_profile = dict(recognizer.last_profile)

        time_dict["rec"] = elapse

        filter_boxes, filter_rec_res = [], []
        for box, rec_result in zip(dt_boxes, rec_res, strict=False):
            _text, score = rec_result
            if score >= self.drop_score:
                filter_boxes.append(box)
                filter_rec_res.append(rec_result)
        end = time.time()
        time_dict["all"] = end - start

        return list(zip([a.tolist() for a in filter_boxes], filter_rec_res, strict=False))
