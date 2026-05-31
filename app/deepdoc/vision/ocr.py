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
from huggingface_hub import snapshot_download

from . import operators
from .postprocess import build_post_process

loaded_models = {}

PARALLEL_DEVICES = 1


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 1024) -> int:
    raw = os.environ.get(name)
    try:
        value = int(str(raw).strip()) if raw is not None else int(default)
    except (TypeError, ValueError):
        value = int(default)
    return max(min_value, min(max_value, value))


def _env_float(name: str, default: float, *, min_value: float = 0.0, max_value: float = 1000.0) -> float:
    raw = os.environ.get(name)
    try:
        value = float(str(raw).strip()) if raw is not None else float(default)
    except (TypeError, ValueError):
        value = float(default)
    return max(min_value, min(max_value, value))


def get_default_resource_dir():
    """
    Return the repo-bundled OCR resource directory.

    Upstream DeepDoc defaults to ``app/resources/data_parser/qieci`` and will
    download duplicate models there. MimirQ keeps OCR assets under
    ``app/deepdoc/resources/models/ocr`` so ONNX assets stay in one place.
    """
    resource_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../resources/models/ocr")
    )
    return resource_dir


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


def transform(data, ops=None):
    """ transform """
    if ops is None:
        ops = []
    for op in ops:
        data = op(data)
        if data is None:
            return None
    return data


def create_operators(op_param_list, global_config=None):
    """
    create operators based on the config

    Args:
        params(list): a dict list, used to create some operators
    """
    assert isinstance(
        op_param_list, list), ('operator config should be a list')
    ops = []
    for operator in op_param_list:
        assert isinstance(operator,
                          dict) and len(operator) == 1, "yaml format error"
        op_name = next(iter(operator))
        param = {} if operator[op_name] is None else operator[op_name]
        if global_config is not None:
            param.update(global_config)
        op = getattr(operators, op_name)(**param)
        ops.append(op)
    return ops


def load_model(model_dir, nm, device_id: int | None = None):
    model_file_path = str(resolve_model_file_path(model_dir, nm))

    if not os.path.exists(model_file_path):
        raise ValueError("not find model file path {}".format(
            model_file_path))

    def resolve_cuda_device_id() -> int | None:
        if not _deepdoc_onnx_gpu_enabled():
            return None
        candidate = 0 if device_id is None else int(device_id)
        try:
            if "CUDAExecutionProvider" not in ort.get_available_providers():
                return None
        except Exception:
            return None
        try:
            import torch
            if torch.cuda.is_available() and torch.cuda.device_count() > candidate:
                return candidate
        except Exception:
            return None
        return None

    cuda_device_id = resolve_cuda_device_id()
    model_cached_tag = f"{model_file_path}:cuda:{cuda_device_id}" if cuda_device_id is not None else f"{model_file_path}:cpu"

    global loaded_models
    loaded_model = loaded_models.get(model_cached_tag)
    if loaded_model:
        logging.info(f"load_model {model_file_path} reuses cached model")
        return loaded_model

    options = ort.SessionOptions()
    options.enable_cpu_mem_arena = False
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 2

    def cpu_session():
        cpu_run_options = ort.RunOptions()
        sess_ = ort.InferenceSession(
            model_file_path,
            options=options,
            providers=['CPUExecutionProvider'])
        cpu_run_options.add_run_config_entry("memory.enable_memory_arena_shrinkage", "cpu")
        logging.info(f"load_model {model_file_path} uses CPU")
        return sess_, cpu_run_options

    # https://github.com/microsoft/onnxruntime/issues/9509#issuecomment-951546580
    # Shrink provider memory after execution.
    if cuda_device_id is not None:
        run_options = ort.RunOptions()
        gpu_mem_limit_mb = int(os.environ.get("DEEPDOC_ONNX_GPU_MEM_LIMIT_MB", "2048"))
        cuda_provider_options = {
            "device_id": cuda_device_id,  # Use specific GPU
            "gpu_mem_limit": gpu_mem_limit_mb * 1024 * 1024,  # Limit gpu memory
            "arena_extend_strategy": "kNextPowerOfTwo",  # gpu memory allocation strategy
        }
        try:
            sess = ort.InferenceSession(
                model_file_path,
                options=options,
                providers=['CUDAExecutionProvider', 'CPUExecutionProvider'],
                provider_options=[cuda_provider_options, {}]
            )
            run_options.add_run_config_entry("memory.enable_memory_arena_shrinkage", "gpu:" + str(cuda_device_id))
            logging.info(f"load_model {model_file_path} uses GPU")
        except Exception as exc:
            logging.warning("load_model %s GPU unavailable, falling back to CPU: %s", model_file_path, str(exc)[:200])
            sess, run_options = cpu_session()
    else:
        sess, run_options = cpu_session()
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
        postprocess_params = {
            'name': 'CTCLabelDecode',
            "character_dict_path": os.path.join(model_dir, "ocr.res"),
            "use_space_char": True
        }
        self.postprocess_op = build_post_process(postprocess_params)
        self.predictor, self.run_options = load_model(model_dir, 'rec', device_id)
        self.input_tensor = self.predictor.get_inputs()[0]

    def resize_norm_img(self, img, max_wh_ratio):
        img_c, img_h, img_w = self.rec_image_shape

        assert img_c == img.shape[2]
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
        resized_image = resized_image.astype('float32')
        resized_image = resized_image.transpose((2, 0, 1)) / 255
        resized_image -= 0.5
        resized_image /= 0.5
        padding_im = np.zeros((img_c, img_h, img_w), dtype=np.float32)
        padding_im[:, :, 0:resized_w] = resized_image
        return padding_im

    def resize_norm_img_vl(self, img, image_shape):

        _img_c, img_h, img_w = image_shape
        img = img[:, :, ::-1]  # bgr2rgb
        resized_image = cv2.resize(
            img, (img_w, img_h), interpolation=cv2.INTER_LINEAR)
        resized_image = resized_image.astype('float32')
        resized_image = resized_image.transpose((2, 0, 1)) / 255
        return resized_image

    def resize_norm_img_srn(self, img, image_shape):
        _img_c, img_h, img_w = image_shape

        img_black = np.zeros((img_h, img_w))
        im_hei = img.shape[0]
        im_wid = img.shape[1]

        if im_wid <= im_hei * 1:
            img_new = cv2.resize(img, (img_h * 1, img_h))
        elif im_wid <= im_hei * 2:
            img_new = cv2.resize(img, (img_h * 2, img_h))
        elif im_wid <= im_hei * 3:
            img_new = cv2.resize(img, (img_h * 3, img_h))
        else:
            img_new = cv2.resize(img, (img_w, img_h))

        img_np = np.asarray(img_new)
        img_np = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
        img_black[:, 0:img_np.shape[1]] = img_np
        img_black = img_black[:, :, np.newaxis]

        row, col, c = img_black.shape
        c = 1

        return np.reshape(img_black, (c, row, col)).astype(np.float32)

    def srn_other_inputs(self, image_shape, num_heads, max_text_length):

        _img_c, img_h, img_w = image_shape
        feature_dim = int((img_h / 8) * (img_w / 8))

        encoder_word_pos = np.array(range(0, feature_dim)).reshape(
            (feature_dim, 1)).astype('int64')
        gsrm_word_pos = np.array(range(0, max_text_length)).reshape(
            (max_text_length, 1)).astype('int64')

        gsrm_attn_bias_data = np.ones((1, max_text_length, max_text_length))
        gsrm_slf_attn_bias1 = np.triu(gsrm_attn_bias_data, 1).reshape(
            [-1, 1, max_text_length, max_text_length])
        gsrm_slf_attn_bias1 = np.tile(
            gsrm_slf_attn_bias1,
            [1, num_heads, 1, 1]).astype('float32') * [-1e9]

        gsrm_slf_attn_bias2 = np.tril(gsrm_attn_bias_data, -1).reshape(
            [-1, 1, max_text_length, max_text_length])
        gsrm_slf_attn_bias2 = np.tile(
            gsrm_slf_attn_bias2,
            [1, num_heads, 1, 1]).astype('float32') * [-1e9]

        encoder_word_pos = encoder_word_pos[np.newaxis, :]
        gsrm_word_pos = gsrm_word_pos[np.newaxis, :]

        return [
            encoder_word_pos, gsrm_word_pos, gsrm_slf_attn_bias1,
            gsrm_slf_attn_bias2
        ]

    def process_image_srn(self, img, image_shape, num_heads, max_text_length):
        norm_img = self.resize_norm_img_srn(img, image_shape)
        norm_img = norm_img[np.newaxis, :]

        [encoder_word_pos, gsrm_word_pos, gsrm_slf_attn_bias1, gsrm_slf_attn_bias2] = \
            self.srn_other_inputs(image_shape, num_heads, max_text_length)

        gsrm_slf_attn_bias1 = gsrm_slf_attn_bias1.astype(np.float32)
        gsrm_slf_attn_bias2 = gsrm_slf_attn_bias2.astype(np.float32)
        encoder_word_pos = encoder_word_pos.astype(np.int64)
        gsrm_word_pos = gsrm_word_pos.astype(np.int64)

        return (norm_img, encoder_word_pos, gsrm_word_pos, gsrm_slf_attn_bias1,
                gsrm_slf_attn_bias2)

    def resize_norm_img_sar(self, img, image_shape,
                            width_downsample_ratio=0.25):
        img_c, img_h, img_w_min, img_w_max = image_shape
        h = img.shape[0]
        w = img.shape[1]
        valid_ratio = 1.0
        # make sure new_width is an integral multiple of width_divisor.
        width_divisor = int(1 / width_downsample_ratio)
        # resize
        ratio = w / float(h)
        resize_w = math.ceil(img_h * ratio)
        if resize_w % width_divisor != 0:
            resize_w = round(resize_w / width_divisor) * width_divisor
        if img_w_min is not None:
            resize_w = max(img_w_min, resize_w)
        if img_w_max is not None:
            valid_ratio = min(1.0, 1.0 * resize_w / img_w_max)
            resize_w = min(img_w_max, resize_w)
        resized_image = cv2.resize(img, (resize_w, img_h))
        resized_image = resized_image.astype('float32')
        # norm
        if image_shape[0] == 1:
            resized_image = resized_image / 255
            resized_image = resized_image[np.newaxis, :]
        else:
            resized_image = resized_image.transpose((2, 0, 1)) / 255
        resized_image -= 0.5
        resized_image /= 0.5
        resize_shape = resized_image.shape
        padding_im = -1.0 * np.ones((img_c, img_h, img_w_max), dtype=np.float32)
        padding_im[:, :, 0:resize_w] = resized_image
        pad_shape = padding_im.shape

        return padding_im, resize_shape, pad_shape, valid_ratio

    def resize_norm_img_spin(self, img):
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.resize(img, (100, 32), cv2.INTER_CUBIC)
        img = np.array(img, np.float32)
        img = np.expand_dims(img, -1)
        img = img.transpose((2, 0, 1))
        mean = [127.5]
        std = [127.5]
        mean = np.array(mean, dtype=np.float32)
        std = np.array(std, dtype=np.float32)
        mean = np.float32(mean.reshape(1, -1))
        stdinv = 1 / np.float32(std.reshape(1, -1))
        img -= mean
        img *= stdinv
        return img

    def resize_norm_img_svtr(self, img, image_shape):

        _img_c, img_h, img_w = image_shape
        resized_image = cv2.resize(
            img, (img_w, img_h), interpolation=cv2.INTER_LINEAR)
        resized_image = resized_image.astype('float32')
        resized_image = resized_image.transpose((2, 0, 1)) / 255
        resized_image -= 0.5
        resized_image /= 0.5
        return resized_image

    def resize_norm_img_abinet(self, img, image_shape):

        _img_c, img_h, img_w = image_shape

        resized_image = cv2.resize(
            img, (img_w, img_h), interpolation=cv2.INTER_LINEAR)
        resized_image = resized_image.astype('float32')
        resized_image = resized_image / 255.

        mean = np.array([0.485, 0.456, 0.406])
        std = np.array([0.229, 0.224, 0.225])
        resized_image = (
                                resized_image - mean[None, None, ...]) / std[None, None, ...]
        resized_image = resized_image.transpose((2, 0, 1))
        resized_image = resized_image.astype('float32')

        return resized_image

    def norm_img_can(self, img, image_shape):
        _ = image_shape

        img = cv2.cvtColor(
            img, cv2.COLOR_BGR2GRAY)  # CAN only predict gray scale image

        if self.rec_image_shape[0] == 1:
            h, w = img.shape
            _, img_h, img_w = self.rec_image_shape
            if h < img_h or w < img_w:
                padding_h = max(img_h - h, 0)
                padding_w = max(img_w - w, 0)
                img_padded = np.pad(img, ((0, padding_h), (0, padding_w)),
                                    'constant',
                                    constant_values=(255))
                img = img_padded

        img = np.expand_dims(img, 0) / 255.0  # h,w,c -> c,h,w
        img = img.astype('float32')

        return img

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
                    yield current[start: start + batch_num]
                current = []
            current_bucket = bucket
            current.append(item)
        if current:
            for start in range(0, len(current), batch_num):
                yield current[start: start + batch_num]

    def __call__(self, img_list):
        img_num = len(img_list)
        rec_res = [['', 0.0]] * img_num
        batch_num = _env_int(
            "DEEPDOC_OCR_REC_BATCH_SIZE",
            int(getattr(self, "rec_batch_num", 16) or 16),
            min_value=1,
            max_value=256,
        )
        bucket_ratio = _env_float(
            "DEEPDOC_OCR_REC_WIDTH_BUCKET_RATIO",
            float(getattr(self, "rec_width_bucket_ratio", 1.0) or 1.0),
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
                norm_img = self.resize_norm_img(img_list[original_index],
                                                max_wh_ratio)
                norm_img = norm_img[np.newaxis, :]
                norm_img_batch.append(norm_img)
            norm_img_batch = np.concatenate(norm_img_batch)
            norm_img_batch = norm_img_batch.copy()

            input_dict = {}
            input_dict[self.input_tensor.name] = norm_img_batch
            for i in range(100000):
                try:
                    outputs = self.predictor.run(None, input_dict, self.run_options)
                    break
                except Exception as e:
                    if i >= 3:
                        raise e
                    time.sleep(5)
            preds = outputs[0]
            rec_result = self.postprocess_op(preds)
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
        pre_process_list = [{
            'DetResizeForTest': {
                'limit_side_len': 960,
                'limit_type': "max",
            }
        }, {
            'NormalizeImage': {
                'std': [0.229, 0.224, 0.225],
                'mean': [0.485, 0.456, 0.406],
                'scale': '1./255.',
                'order': 'hwc'
            }
        }, {
            'ToCHWImage': None
        }, {
            'KeepKeys': {
                'keep_keys': ['image', 'shape']
            }
        }]
        postprocess_params = {"name": "DBPostProcess", "thresh": 0.3, "box_thresh": 0.5, "max_candidates": 1000,
                              "unclip_ratio": 1.5, "use_dilation": False, "score_mode": "fast", "box_type": "quad"}

        self.postprocess_op = build_post_process(postprocess_params)
        self.predictor, self.run_options = load_model(model_dir, 'det', device_id)
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
            pre_process_list[0] = {
                'DetResizeForTest': {
                    'image_shape': [img_h, img_w]
                }
            }
        self.preprocess_op = create_operators(pre_process_list)

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

    def filter_tag_det_res_only_clip(self, dt_boxes, image_shape):
        img_height, img_width = image_shape[0:2]
        dt_boxes_new = []
        for box in dt_boxes:
            if isinstance(box, list):
                box = np.array(box)
            box = self.clip_det_res(box, img_height, img_width)
            dt_boxes_new.append(box)
        dt_boxes = np.array(dt_boxes_new)
        return dt_boxes

    def __call__(self, img):
        ori_im = img.copy()
        data = {'image': img}

        st = time.time()
        data = transform(data, self.preprocess_op)
        img, shape_list = data
        if img is None:
            return None, 0
        img = np.expand_dims(img, axis=0)
        shape_list = np.expand_dims(shape_list, axis=0)
        img = img.copy()
        input_dict = {}
        input_dict[self.input_tensor.name] = img
        for i in range(100000):
            try:
                outputs = self.predictor.run(None, input_dict, self.run_options)
                break
            except Exception as e:
                if i >= 3:
                    raise e
                time.sleep(5)

        post_result = self.postprocess_op({"maps": outputs[0]}, shape_list)
        dt_boxes = post_result[0]['points']
        dt_boxes = self.filter_tag_det_res(dt_boxes, ori_im.shape)

        return dt_boxes, time.time() - st


class OCR:
    def __init__(self, model_dir=None):
        """
        If you have trouble downloading HuggingFace models, -_^ this might help!!

        For Linux:
        export HF_ENDPOINT=https://hf-mirror.com

        For Windows:
        Good luck
        ^_-

        """
        if not model_dir:
            try:
                model_dir = get_default_resource_dir()

                # Append muti-gpus task to the list
                if PARALLEL_DEVICES is not None and PARALLEL_DEVICES > 0:
                    self.text_detector = []
                    self.text_recognizer = []
                    for device_id in range(PARALLEL_DEVICES):
                        self.text_detector.append(TextDetector(model_dir, device_id))
                        self.text_recognizer.append(TextRecognizer(model_dir, device_id))
                else:
                    self.text_detector = [TextDetector(model_dir, 0)]
                    self.text_recognizer = [TextRecognizer(model_dir, 0)]

            except Exception:
                model_dir = snapshot_download(repo_id="InfiniFlow/deepdoc",
                                              local_dir=get_default_resource_dir(),
                                              local_dir_use_symlinks=False)

                if PARALLEL_DEVICES is not None:
                    assert PARALLEL_DEVICES > 0, "Number of devices must be >= 1"
                    self.text_detector = []
                    self.text_recognizer = []
                    for device_id in range(PARALLEL_DEVICES):
                        self.text_detector.append(TextDetector(model_dir, device_id))
                        self.text_recognizer.append(TextRecognizer(model_dir, device_id))
                else:
                    self.text_detector = [TextDetector(model_dir, 0)]
                    self.text_recognizer = [TextRecognizer(model_dir, 0)]

        self.drop_score = 0.5
        self.crop_image_res_index = 0
        self.last_recognition_profile: dict[str, object] = {}

    def get_rotate_crop_image(self, img, points):
        '''
        img_height, img_width = img.shape[0:2]
        left = int(np.min(points[:, 0]))
        right = int(np.max(points[:, 0]))
        top = int(np.min(points[:, 1]))
        bottom = int(np.max(points[:, 1]))
        img_crop = img[top:bottom, left:right, :].copy()
        points[:, 0] = points[:, 0] - left
        points[:, 1] = points[:, 1] - top
        '''
        assert len(points) == 4, "shape of points must be 4*2"
        img_crop_width = int(
            max(
                np.linalg.norm(points[0] - points[1]),
                np.linalg.norm(points[2] - points[3])))
        img_crop_height = int(
            max(
                np.linalg.norm(points[0] - points[3]),
                np.linalg.norm(points[1] - points[2])))
        pts_std = np.float32([[0, 0], [img_crop_width, 0],
                              [img_crop_width, img_crop_height],
                              [0, img_crop_height]])
        M = cv2.getPerspectiveTransform(points, pts_std)
        dst_img = cv2.warpPerspective(
            img,
            M, (img_crop_width, img_crop_height),
            borderMode=cv2.BORDER_REPLICATE,
            flags=cv2.INTER_CUBIC)
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
                if abs(_boxes[j + 1][0][1] - _boxes[j][0][1]) < 10 and \
                        (_boxes[j + 1][0][0] < _boxes[j][0][0]):
                    tmp = _boxes[j]
                    _boxes[j] = _boxes[j + 1]
                    _boxes[j + 1] = tmp
                else:
                    break
        return _boxes

    def detect(self, img, device_id: int | None = None):
        if device_id is None:
            device_id = 0

        time_dict = {'det': 0, 'rec': 0, 'cls': 0, 'all': 0}

        if img is None:
            return None, None, time_dict

        start = time.time()
        dt_boxes, elapse = self.text_detector[device_id](img)
        time_dict['det'] = elapse

        if dt_boxes is None:
            end = time.time()
            time_dict['all'] = end - start
            return None, None, time_dict

        return zip(self.sorted_boxes(dt_boxes), [
            ("", 0) for _ in range(len(dt_boxes))], strict=False)

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
        profile = getattr(recognizer, "last_profile", None)
        self.last_recognition_profile = dict(profile) if isinstance(profile, dict) else {}
        texts = []
        for i in range(len(rec_res)):
            text, score = rec_res[i]
            if score < self.drop_score:
                text = ""
            texts.append(text)
        return texts

    def __call__(self, img, device_id=0, cls=True):
        time_dict = {'det': 0, 'rec': 0, 'cls': 0, 'all': 0}
        if device_id is None:
            device_id = 0

        if img is None:
            return None, None, time_dict

        start = time.time()
        ori_im = img.copy()
        dt_boxes, elapse = self.text_detector[device_id](img)
        time_dict['det'] = elapse

        if dt_boxes is None:
            end = time.time()
            time_dict['all'] = end - start
            return None, None, time_dict

        img_crop_list = []

        dt_boxes = self.sorted_boxes(dt_boxes)

        for bno in range(len(dt_boxes)):
            tmp_box = copy.deepcopy(dt_boxes[bno])
            img_crop = self.get_rotate_crop_image(ori_im, tmp_box)
            img_crop_list.append(img_crop)

        recognizer = self.text_recognizer[device_id]
        rec_res, elapse = recognizer(img_crop_list)
        profile = getattr(recognizer, "last_profile", None)
        self.last_recognition_profile = dict(profile) if isinstance(profile, dict) else {}

        time_dict['rec'] = elapse

        filter_boxes, filter_rec_res = [], []
        for box, rec_result in zip(dt_boxes, rec_res, strict=False):
            _text, score = rec_result
            if score >= self.drop_score:
                filter_boxes.append(box)
                filter_rec_res.append(rec_result)
        end = time.time()
        time_dict['all'] = end - start

        return list(zip([a.tolist() for a in filter_boxes], filter_rec_res, strict=False))
