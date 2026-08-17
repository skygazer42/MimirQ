import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from app.parsing.models.manifest import SmallModelSpec
from scripts import bootstrap_parsing_small_models as bootstrap


def _install_module(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    *,
    package: bool = False,
    **attrs: Any,
) -> ModuleType:
    module = ModuleType(name)
    if package:
        module.__dict__["__path__"] = []
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _spec(*, pipeline_task: str = "image-classification") -> SmallModelSpec:
    return SmallModelSpec(
        task="layout",
        model_id="demo",
        kind="hf_transformers",
        repo_id="org/demo",
        pipeline_task=pipeline_task,
    )


def test_convert_uses_optimum_and_normalizes_output_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    def main_export(**kwargs: Any) -> None:
        calls.append(kwargs)
        output = Path(kwargs["output"])
        output.mkdir(parents=True, exist_ok=True)
        (output / "generated.onnx").write_bytes(b"onnx")

    _install_module(monkeypatch, "optimum", package=True)
    _install_module(monkeypatch, "optimum.exporters", package=True)
    _install_module(monkeypatch, "optimum.exporters.onnx", main_export=main_export)
    destination = tmp_path / "output" / "model.onnx"

    result = bootstrap._convert_transformers_to_onnx(
        spec=_spec(pipeline_task="image_classification"),
        snapshot_path=tmp_path / "snapshot",
        onnx_path=destination,
        opset=17,
    )

    assert result == {"backend": "optimum", "task": "image-classification", "opset": 17}
    assert destination.read_bytes() == b"onnx"
    assert calls == [
        {
            "model_name_or_path": str(tmp_path / "snapshot"),
            "output": str(destination.parent),
            "task": "image-classification",
            "opset": 17,
            "device": "cpu",
        }
    ]


def test_convert_falls_back_to_transformers_and_first_working_preprocessor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_module(monkeypatch, "optimum", package=True)
    _install_module(monkeypatch, "optimum.exporters", package=True)
    _install_module(monkeypatch, "optimum.exporters.onnx")
    load_order: list[str] = []
    export_calls: list[dict[str, Any]] = []

    class _AutoConfig:
        @staticmethod
        def from_pretrained(_path: str) -> SimpleNamespace:
            return SimpleNamespace(model_type="demo")

    class _FailingImageProcessor:
        @staticmethod
        def from_pretrained(_path: str) -> object:
            load_order.append("image")
            raise ValueError("not an image model")

    class _FeatureExtractor:
        @staticmethod
        def from_pretrained(_path: str) -> str:
            load_order.append("feature")
            return "feature-extractor"

    class _UnexpectedTokenizer:
        @staticmethod
        def from_pretrained(_path: str) -> object:
            raise AssertionError("tokenizer should not be loaded")

    class _Model:
        @staticmethod
        def from_pretrained(path: str) -> tuple[str, str]:
            return ("model", path)

    class _FeaturesManager:
        @staticmethod
        def get_supported_features_for_model_type(_model_type: str) -> dict[str, object]:
            return {"default": object()}

        @staticmethod
        def get_model_class_for_feature(task: str, *, framework: str) -> type[_Model]:
            assert (task, framework) == ("default", "pt")
            return _Model

        @staticmethod
        def get_config(model_type: str, task: str):
            assert (model_type, task) == ("demo", "default")
            return lambda config: ("onnx-config", config.model_type)

    def export(**kwargs: Any) -> None:
        export_calls.append(kwargs)

    _install_module(
        monkeypatch,
        "transformers",
        package=True,
        AutoConfig=_AutoConfig,
        AutoFeatureExtractor=_FeatureExtractor,
        AutoImageProcessor=_FailingImageProcessor,
        AutoTokenizer=_UnexpectedTokenizer,
    )
    _install_module(monkeypatch, "transformers.onnx", FeaturesManager=_FeaturesManager, export=export)
    destination = tmp_path / "output" / "model.onnx"

    result = bootstrap._convert_transformers_to_onnx(
        spec=_spec(pipeline_task="auto"),
        snapshot_path=tmp_path / "snapshot",
        onnx_path=destination,
        opset=18,
    )

    assert result == {"backend": "transformers.onnx", "task": "default", "opset": 18}
    assert load_order == ["image", "feature"]
    assert export_calls == [
        {
            "preprocessor": "feature-extractor",
            "model": ("model", str(tmp_path / "snapshot")),
            "config": ("onnx-config", "demo"),
            "opset": 18,
            "output": destination,
            "device": "cpu",
        }
    ]
