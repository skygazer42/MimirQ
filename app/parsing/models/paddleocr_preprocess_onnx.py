
import math
import time
from dataclasses import dataclass
from typing import Any

from PIL import Image as PILImage

from app.core.optional_deps import require_dependency
from app.parsing.models.runtime import LoadedSmallModel, SmallModelRuntime

_DOC_ORIENTATION_MODEL_ID = "monkt_pp_lcnet_doc_ori_onnx"
_TEXTLINE_ORIENTATION_MODEL_ID = "monkt_pp_lcnet_textline_ori_onnx"
_UNWARP_MODEL_ID = "monkt_uvdoc_onnx"


@dataclass(frozen=True, slots=True)
class OrientationPrediction:
    task: str
    model_id: str
    label: str
    angle: int
    confidence: float
    scores: dict[str, float]
    elapsed_ms: int

    def to_metadata(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "model_id": self.model_id,
            "label": self.label,
            "angle": int(self.angle),
            "confidence": round(float(self.confidence), 6),
            "scores": {key: round(float(value), 6) for key, value in self.scores.items()},
            "elapsed_ms": int(self.elapsed_ms),
        }


@dataclass(frozen=True, slots=True)
class DocumentUnwarpPrediction:
    task: str
    model_id: str
    applied: bool
    image: PILImage.Image
    source_size: tuple[int, int]
    output_size: tuple[int, int]
    elapsed_ms: int

    def to_metadata(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "model_id": self.model_id,
            "applied": bool(self.applied),
            "source_size": {"width": int(self.source_size[0]), "height": int(self.source_size[1])},
            "output_size": {"width": int(self.output_size[0]), "height": int(self.output_size[1])},
            "elapsed_ms": int(self.elapsed_ms),
        }


def _input_shape(loaded: LoadedSmallModel, *, default_height: int, default_width: int) -> tuple[str, int, int]:
    inputs = loaded.handle.get_inputs()
    if not inputs:
        raise RuntimeError(f"ONNX model has no inputs: {loaded.model_id}")
    shape = list(getattr(inputs[0], "shape", []) or [])
    height = default_height
    width = default_width
    if len(shape) >= 4:
        if isinstance(shape[2], int) and shape[2] > 0:
            height = int(shape[2])
        if isinstance(shape[3], int) and shape[3] > 0:
            width = int(shape[3])
    return str(inputs[0].name), height, width


def _output_names(loaded: LoadedSmallModel) -> list[str]:
    outputs = loaded.handle.get_outputs()
    return [str(item.name) for item in outputs]


def _resize_for_max_side(image: PILImage.Image, *, max_side: int) -> PILImage.Image:
    width, height = image.size
    limit = max(1, int(max_side or 640))
    largest = max(width, height)
    if largest <= limit:
        return image.convert("RGB")
    scale = float(limit) / float(largest)
    next_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return image.convert("RGB").resize(next_size, PILImage.Resampling.BICUBIC)


def _image_to_nchw(image: PILImage.Image, *, height: int, width: int) -> Any:
    np = require_dependency("numpy", feature="paddleocr_preprocess_onnx", pip_name="numpy")
    resized = image.convert("RGB").resize((int(width), int(height)), PILImage.Resampling.BICUBIC)
    arr = np.asarray(resized, dtype="float32") / 255.0
    # PaddleOCR classification preprocess is close to ImageNet-style normalization.
    mean = np.asarray([0.485, 0.456, 0.406], dtype="float32")
    std = np.asarray([0.229, 0.224, 0.225], dtype="float32")
    arr = (arr - mean) / std
    return arr.transpose(2, 0, 1)[None, ...].astype("float32")


def _image_to_unwarp_nchw(image: PILImage.Image) -> Any:
    np = require_dependency("numpy", feature="paddleocr_preprocess_onnx", pip_name="numpy")
    arr = np.asarray(image.convert("RGB"), dtype="float32") / 255.0
    return arr.transpose(2, 0, 1)[None, ...].astype("float32")


def _softmax(logits: Any) -> list[float]:
    np = require_dependency("numpy", feature="paddleocr_preprocess_onnx", pip_name="numpy")
    arr = np.asarray(logits, dtype="float32")
    if arr.ndim > 1:
        arr = arr[0]
    arr = arr - np.max(arr)
    exp = np.exp(arr)
    probs = exp / max(float(np.sum(exp)), 1e-12)
    return [float(value) for value in probs.tolist()]


def _predict_orientation(
    image: PILImage.Image,
    *,
    runtime: SmallModelRuntime | None,
    task: str,
    model_id: str,
    labels: tuple[str, ...],
    angles: tuple[int, ...],
    default_height: int,
    default_width: int,
) -> OrientationPrediction:
    started = time.perf_counter()
    rt = runtime or SmallModelRuntime()
    loaded = rt.load(task, model_id=model_id)
    input_name, height, width = _input_shape(loaded, default_height=default_height, default_width=default_width)
    outputs = loaded.handle.run(_output_names(loaded), {input_name: _image_to_nchw(image, height=height, width=width)})
    probs = _softmax(outputs[0])
    if not probs:
        raise RuntimeError(f"ONNX model returned empty logits: {loaded.model_id}")
    best_index = max(range(len(probs)), key=lambda idx: probs[idx])
    label = labels[best_index] if best_index < len(labels) else str(best_index)
    angle = angles[best_index] if best_index < len(angles) else 0
    elapsed_ms = max(0, int(round((time.perf_counter() - started) * 1000)))
    return OrientationPrediction(
        task=task,
        model_id=loaded.model_id,
        label=label,
        angle=int(angle),
        confidence=float(probs[best_index]),
        scores={labels[index] if index < len(labels) else str(index): score for index, score in enumerate(probs)},
        elapsed_ms=elapsed_ms,
    )


def predict_document_orientation(
    image: PILImage.Image,
    *,
    runtime: SmallModelRuntime | None = None,
    model_id: str = _DOC_ORIENTATION_MODEL_ID,
) -> OrientationPrediction:
    return _predict_orientation(
        image,
        runtime=runtime,
        task="document_orientation",
        model_id=model_id,
        labels=("0°", "90°", "180°", "270°"),
        angles=(0, 90, 180, 270),
        default_height=224,
        default_width=224,
    )


def predict_textline_orientation(
    image: PILImage.Image,
    *,
    runtime: SmallModelRuntime | None = None,
    model_id: str = _TEXTLINE_ORIENTATION_MODEL_ID,
) -> OrientationPrediction:
    return _predict_orientation(
        image,
        runtime=runtime,
        task="textline_orientation",
        model_id=model_id,
        labels=("0°", "180°"),
        angles=(0, 180),
        default_height=80,
        default_width=160,
    )


def _tensor_to_image(tensor: Any) -> PILImage.Image:
    np = require_dependency("numpy", feature="paddleocr_preprocess_onnx", pip_name="numpy")
    arr = np.asarray(tensor, dtype="float32")
    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim != 3:
        raise RuntimeError(f"Unexpected UVDoc output shape: {arr.shape}")
    if arr.shape[0] == 3:
        arr = arr.transpose(1, 2, 0)
    if math.isfinite(float(arr.max())) and float(arr.max()) <= 1.5:
        arr = arr * 255.0
    arr = np.clip(arr, 0, 255).astype("uint8")
    return PILImage.fromarray(arr, mode="RGB")


def predict_document_unwarp(
    image: PILImage.Image,
    *,
    runtime: SmallModelRuntime | None = None,
    model_id: str = _UNWARP_MODEL_ID,
    max_side: int = 640,
) -> DocumentUnwarpPrediction:
    started = time.perf_counter()
    rt = runtime or SmallModelRuntime()
    loaded = rt.load("document_rectification", model_id=model_id)
    input_name = str(loaded.handle.get_inputs()[0].name)
    source_size = image.size
    inference_image = _resize_for_max_side(image, max_side=max_side)
    outputs = loaded.handle.run(_output_names(loaded), {input_name: _image_to_unwarp_nchw(inference_image)})
    output_image = _tensor_to_image(outputs[0])
    elapsed_ms = max(0, int(round((time.perf_counter() - started) * 1000)))
    return DocumentUnwarpPrediction(
        task="document_rectification",
        model_id=loaded.model_id,
        applied=True,
        image=output_image,
        source_size=source_size,
        output_size=output_image.size,
        elapsed_ms=elapsed_ms,
    )


__all__ = [
    "DocumentUnwarpPrediction",
    "OrientationPrediction",
    "predict_document_orientation",
    "predict_document_unwarp",
    "predict_textline_orientation",
]
