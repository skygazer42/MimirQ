from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image as PILImage

from app.core.optional_deps import require_dependency
from app.parsing.enrich.table_structure_adapter import TableStructureDetection
from app.parsing.models.runtime import LoadedSmallModel, SmallModelRuntime

_DEFAULT_TATR_ONNX_MODEL_ID = "tatr_v1_1_all_onnx"


def _metadata_value(loaded: LoadedSmallModel, key: str) -> str | None:
    metadata = loaded.metadata or {}
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        value = nested.get(key)
        if value is not None:
            return str(value)
    value = metadata.get(key)
    if value is not None:
        return str(value)
    return None


def _preprocessor_path(loaded: LoadedSmallModel) -> Path:
    explicit = _metadata_value(loaded, "preprocessor_path")
    if explicit:
        return Path(explicit).resolve()
    if loaded.path is not None:
        return loaded.path.parent
    raise RuntimeError(f"Missing preprocessor path for table structure model: {loaded.model_id}")


def _load_id2label(model_dir: Path) -> dict[int, str]:
    config_path = model_dir / "config.json"
    if not config_path.exists():
        return {}
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    id2label = raw.get("id2label")
    if not isinstance(id2label, dict):
        return {}
    out: dict[int, str] = {}
    for key, value in id2label.items():
        try:
            out[int(key)] = str(value)
        except (TypeError, ValueError):
            continue
    return out


def _softmax(values: Any) -> Any:
    np = require_dependency("numpy", feature="table_transformer_onnx", pip_name="numpy")
    arr = np.asarray(values, dtype="float32")
    arr = arr - np.max(arr, axis=-1, keepdims=True)
    exp = np.exp(arr)
    return exp / np.sum(exp, axis=-1, keepdims=True)


def _box_cxcywh_to_xyxy(box: Any, *, width: int, height: int) -> dict[str, float]:
    cx, cy, bw, bh = [float(x) for x in list(box)[:4]]
    left = max(0.0, (cx - bw / 2.0) * float(width))
    top = max(0.0, (cy - bh / 2.0) * float(height))
    right = min(float(width), (cx + bw / 2.0) * float(width))
    bottom = min(float(height), (cy + bh / 2.0) * float(height))
    return {
        "left": round(left, 3),
        "top": round(top, 3),
        "right": round(right, 3),
        "bottom": round(bottom, 3),
    }


def _patch_detr_processor_size(processor: Any) -> None:
    size = getattr(processor, "size", None)
    if not isinstance(size, dict):
        return
    if "longest_edge" not in size or "shortest_edge" in size:
        return
    try:
        longest_edge = int(size["longest_edge"])
    except (TypeError, ValueError):
        return
    if longest_edge <= 0:
        return
    processor.size = {"shortest_edge": longest_edge, "longest_edge": longest_edge}


def predict_table_structure_detections(
    image: PILImage.Image,
    *,
    runtime: SmallModelRuntime | None = None,
    task: str = "table_structure",
    model_id: str = _DEFAULT_TATR_ONNX_MODEL_ID,
    threshold: float = 0.5,
    max_detections: int = 64,
) -> list[TableStructureDetection]:
    """Run the converted TATR ONNX model and return normalized structure detections."""
    if not isinstance(image, PILImage.Image):
        raise TypeError("image must be a PIL.Image.Image")

    rt = runtime or SmallModelRuntime()
    loaded = rt.load(task, model_id=model_id)
    model_dir = _preprocessor_path(loaded)

    transformers = require_dependency("transformers", feature="table_transformer_onnx", pip_name="transformers")
    processor = transformers.AutoImageProcessor.from_pretrained(str(model_dir), local_files_only=True)
    _patch_detr_processor_size(processor)
    encoded = processor(images=image.convert("RGB"), return_tensors="np")
    pixel_values = encoded["pixel_values"]

    logits, pred_boxes = loaded.handle.run(["logits", "pred_boxes"], {"pixel_values": pixel_values})
    probs = _softmax(logits)[0]
    boxes = pred_boxes[0]
    id2label = _load_id2label(model_dir)
    no_object_index = probs.shape[-1] - 1
    width, height = image.size
    detections: list[TableStructureDetection] = []
    for row_index, row in enumerate(probs):
        label_index = int(row[:-1].argmax()) if row.shape[-1] > 1 else int(row.argmax())
        if label_index == no_object_index:
            continue
        score = float(row[label_index])
        if score < float(threshold):
            continue
        label = id2label.get(label_index, f"label_{label_index}")
        detections.append(
            TableStructureDetection(
                label=label,
                score=score,
                bbox=_box_cxcywh_to_xyxy(boxes[row_index], width=width, height=height),
            )
        )
    detections.sort(key=lambda item: item.score, reverse=True)
    return detections[: max(0, int(max_detections))]


__all__ = ["predict_table_structure_detections"]
