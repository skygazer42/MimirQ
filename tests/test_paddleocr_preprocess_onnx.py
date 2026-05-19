from __future__ import annotations

import importlib

from PIL import Image

from app.parsing.models.runtime import LoadedSmallModel


class _FakeInput:
    def __init__(self, name: str, shape: list[object]) -> None:
        self.name = name
        self.shape = shape


class _FakeOutput:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeClassificationSession:
    def __init__(self, *, shape: list[object], logits: list[float]) -> None:
        self._shape = shape
        self._logits = logits
        self.inputs_seen: list[tuple[int, ...]] = []

    def get_inputs(self):  # noqa: ANN201
        return [_FakeInput("x", self._shape)]

    def get_outputs(self):  # noqa: ANN201
        return [_FakeOutput("fetch_name_0")]

    def run(self, outputs, inputs):  # noqa: ANN001, ANN201
        np = importlib.import_module("numpy")
        self.inputs_seen.append(tuple(inputs["x"].shape))
        assert outputs == ["fetch_name_0"]
        return [np.asarray([self._logits], dtype="float32")]


class _FakeUnwarpSession:
    def get_inputs(self):  # noqa: ANN201
        return [_FakeInput("image", [1, 3, "h", "w"])]

    def get_outputs(self):  # noqa: ANN201
        return [_FakeOutput("fetch_name_0")]

    def run(self, outputs, inputs):  # noqa: ANN001, ANN201
        assert outputs == ["fetch_name_0"]
        return [inputs["image"]]


class _FakeRuntime:
    def __init__(self) -> None:
        self.doc_session = _FakeClassificationSession(shape=[1, 3, 224, 224], logits=[0.1, 9.0, 0.2, 0.3])
        self.textline_session = _FakeClassificationSession(shape=[1, 3, 80, 160], logits=[0.1, 5.0])
        self.unwarp_session = _FakeUnwarpSession()

    def load(self, task: str, *, model_id: str | None = None):  # noqa: ANN201
        if task == "document_orientation":
            return LoadedSmallModel(task=task, model_id=model_id or "doc", kind="onnx", available=True, handle=self.doc_session)
        if task == "textline_orientation":
            return LoadedSmallModel(task=task, model_id=model_id or "line", kind="onnx", available=True, handle=self.textline_session)
        if task == "document_rectification":
            return LoadedSmallModel(task=task, model_id=model_id or "uvdoc", kind="onnx", available=True, handle=self.unwarp_session)
        raise AssertionError(task)


def test_paddleocr_orientation_predictors_call_onnx_sessions() -> None:
    from app.parsing.models.paddleocr_preprocess_onnx import (
        predict_document_orientation,
        predict_textline_orientation,
    )

    runtime = _FakeRuntime()
    image = Image.new("RGB", (48, 24), "white")

    doc = predict_document_orientation(image, runtime=runtime)
    line = predict_textline_orientation(image, runtime=runtime)

    assert doc.angle == 90
    assert doc.label == "90°"
    assert doc.confidence > 0.99
    assert runtime.doc_session.inputs_seen == [(1, 3, 224, 224)]
    assert line.angle == 180
    assert line.label == "180°"
    assert runtime.textline_session.inputs_seen == [(1, 3, 80, 160)]


def test_paddleocr_unwarp_predictor_returns_rectified_image_metadata() -> None:
    from app.parsing.models.paddleocr_preprocess_onnx import predict_document_unwarp

    runtime = _FakeRuntime()
    image = Image.new("RGB", (320, 160), "white")

    result = predict_document_unwarp(image, runtime=runtime, max_side=160)

    assert result.applied is True
    assert result.output_size == (160, 80)
    assert result.image.size == (160, 80)
    assert result.to_metadata()["output_size"] == {"width": 160, "height": 80}
