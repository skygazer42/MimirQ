from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image


def test_tatr_onnx_predictor_normalizes_detections(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.parsing.models.runtime import LoadedSmallModel
    from app.parsing.models.table_transformer_onnx import predict_table_structure_detections

    (tmp_path / "config.json").write_text(
        json.dumps({"id2label": {"0": "table", "1": "table column", "2": "table row"}}),
        encoding="utf-8",
    )

    class FakeProcessor:
        def __call__(self, *, images, return_tensors: str):  # noqa: ANN001
            np = importlib.import_module("numpy")
            assert return_tensors == "np"
            assert images.mode == "RGB"
            return {"pixel_values": np.zeros((1, 3, 8, 8), dtype="float32")}

    class FakeAutoImageProcessor:
        @staticmethod
        def from_pretrained(path: str, *, local_files_only: bool):  # noqa: ANN205
            assert Path(path) == tmp_path
            assert local_files_only is True
            return FakeProcessor()

    class FakeSession:
        @staticmethod
        def run(outputs, inputs):  # noqa: ANN001, ANN205
            np = importlib.import_module("numpy")
            assert outputs == ["logits", "pred_boxes"]
            assert inputs["pixel_values"].shape == (1, 3, 8, 8)
            logits = np.array(
                [
                    [
                        [0.1, 0.2, 8.0, -1.0, -1.0, -1.0, 0.0],
                        [0.1, 0.2, 0.3, -1.0, -1.0, -1.0, 9.0],
                    ]
                ],
                dtype="float32",
            )
            boxes = np.array([[[0.5, 0.5, 0.5, 0.25], [0.2, 0.2, 0.1, 0.1]]], dtype="float32")
            return [logits, boxes]

    class FakeRuntime:
        @staticmethod
        def load(task: str, *, model_id: str):  # noqa: ANN205
            assert task == "table_structure"
            assert model_id == "tatr_v1_1_all_onnx"
            return LoadedSmallModel(
                task=task,
                model_id=model_id,
                kind="onnx",
                available=True,
                handle=FakeSession(),
                metadata={"metadata": {"preprocessor_path": str(tmp_path)}},
            )

    def fake_require_dependency(module: str, **kwargs):  # noqa: ANN001, ANN202
        if module == "transformers":
            return SimpleNamespace(AutoImageProcessor=FakeAutoImageProcessor)
        return importlib.import_module(module)

    monkeypatch.setattr("app.parsing.models.table_transformer_onnx.require_dependency", fake_require_dependency)

    detections = predict_table_structure_detections(Image.new("RGB", (200, 100)), runtime=FakeRuntime())

    assert len(detections) == 1
    assert detections[0].label == "table row"
    assert detections[0].score > 0.99
    assert detections[0].bbox == {"left": 50.0, "top": 37.5, "right": 150.0, "bottom": 62.5}
