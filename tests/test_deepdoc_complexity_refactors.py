from __future__ import annotations

import builtins
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import ANY

import numpy as np
import pandas as pd
import pytest
from PIL import Image

import app.deepdoc.parser.figure_parser as figure_parser
import app.deepdoc.vision.layout_recognizer as layout_module
import app.deepdoc.vision.ocr as ocr_module
from app.deepdoc.parser.docx_parser import IntegratedPipelineDocxParser
from app.deepdoc.vision.layout_recognizer import LayoutRecognizer
from app.deepdoc.vision.recognizer import Recognizer


def test_recognizer_postprocess_preserves_threshold_scaling_and_class_order() -> None:
    recognizer = object.__new__(Recognizer)
    recognizer.input_names = ["image"]
    recognizer.label_list = ["text", "title"]

    boxes = np.array(
        [
            [
                [10.0, 11.0, 40.0],
                [10.0, 11.0, 50.0],
                [4.0, 4.0, 6.0],
                [4.0, 4.0, 6.0],
                [0.90, 0.80, 0.10],
                [0.05, 0.10, 0.95],
            ]
        ],
        dtype=np.float32,
    )

    result = recognizer.postprocess(boxes, {"scale_factor": [2.0, 3.0]}, 0.3)

    assert result == [
        {
            "type": "text",
            "bbox": [16.0, 24.0, 24.0, 36.0],
            "score": 0.8999999761581421,
        },
        {
            "type": "title",
            "bbox": [74.0, 141.0, 86.0, 159.0],
            "score": 0.949999988079071,
        },
    ]


def test_layouts_cleanup_mutates_and_keeps_the_more_supported_overlap() -> None:
    boxes = [
        {"x0": 1, "x1": 9, "top": 1, "bottom": 9},
        {"x0": 0, "x1": 12, "top": 0, "bottom": 12},
    ]
    layouts = [
        {"type": "text", "x0": 0, "x1": 10, "top": 0, "bottom": 10},
        {"type": "text", "x0": 1, "x1": 11, "top": 1, "bottom": 11},
        {"type": "title", "x0": 30, "x1": 40, "top": 0, "bottom": 10},
    ]

    cleaned = Recognizer.layouts_cleanup(boxes, layouts, far=2, thr=0.7)

    assert cleaned is layouts
    assert cleaned == [
        {"type": "text", "x0": 1, "x1": 11, "top": 1, "bottom": 11},
        {"type": "title", "x0": 30, "x1": 40, "top": 0, "bottom": 10},
    ]


def test_layout_recognizer_call_preserves_layout_tagging_drop_and_page_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detections = [
        [
            {"type": "header", "score": 0.95, "bbox": [0, 0, 40, 10]},
            {"type": "title", "score": 0.92, "bbox": [0, 20, 80, 30]},
            {"type": "figure", "score": 0.99, "bbox": [10, 50, 90, 90]},
        ]
    ]
    monkeypatch.setattr(layout_module.Recognizer, "__call__", lambda self, images, thr, batch_size: detections)

    recognizer = object.__new__(LayoutRecognizer)
    recognizer.garbage_layouts = ["footer", "header", "reference"]
    image = Image.new("RGB", (100, 100), "white")
    ocr_boxes = [
        [
            {"text": "Header text", "x0": 0, "x1": 40, "top": 0, "bottom": 10},
            {"text": "Document title", "x0": 0, "x1": 80, "top": 20, "bottom": 30},
        ]
    ]

    tagged, page_layout = recognizer([image], ocr_boxes, scale_factor=1, drop=True)

    assert tagged == [
        {
            "text": "Document title",
            "x0": 0,
            "x1": 80,
            "top": 20,
            "bottom": 30,
            "layoutno": "title-0",
            "layout_type": "title",
        },
        {
            "score": 0.99,
            "x0": 10.0,
            "x1": 90.0,
            "top": 50.0,
            "bottom": 90.0,
            "page_number": 0,
            "text": "",
            "layout_type": "figure",
            "layoutno": "figure-0",
        },
    ]
    assert page_layout == [
        [
            {
                "type": "header",
                "score": 0.95,
                "x0": 0.0,
                "x1": 40.0,
                "top": 0.0,
                "bottom": 10.0,
                "page_number": 0,
                "visited": True,
            },
            {
                "type": "title",
                "score": 0.92,
                "x0": 0.0,
                "x1": 80.0,
                "top": 20.0,
                "bottom": 30.0,
                "page_number": 0,
                "visited": True,
            },
            {
                "type": "figure",
                "score": 0.99,
                "x0": 10.0,
                "x1": 90.0,
                "top": 50.0,
                "bottom": 90.0,
                "page_number": 0,
            },
        ]
    ]
    assert ocr_boxes[0] == tagged


def test_load_model_raises_when_the_onnx_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Run `make models` before local parsing"):
        ocr_module.load_model(tmp_path, "det")


def test_load_model_falls_back_to_cpu_and_reuses_the_cached_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "rec.onnx"
    model_path.write_bytes(b"onnx")
    calls: list[dict[str, object]] = []
    session = object()

    class _FakeSessionOptions:
        enable_cpu_mem_arena = True
        execution_mode = None
        intra_op_num_threads = 0
        inter_op_num_threads = 0

    class _FakeRunOptions:
        def __init__(self) -> None:
            self.entries: list[tuple[str, str]] = []

        def add_run_config_entry(self, key: str, value: str) -> None:
            self.entries.append((key, value))

    def _inference_session(
        model_file_path: str,
        *,
        options: object,
        providers: list[str],
        provider_options: list[dict[str, object]] | None = None,
    ) -> object:
        calls.append(
            {
                "path": model_file_path,
                "options": options,
                "providers": providers,
                "provider_options": provider_options,
            }
        )
        if providers[0] == "CUDAExecutionProvider":
            raise RuntimeError("gpu unavailable")
        return session

    fake_ort = SimpleNamespace(
        SessionOptions=_FakeSessionOptions,
        RunOptions=_FakeRunOptions,
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="sequential"),
        get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
        InferenceSession=_inference_session,
    )
    fake_torch = ModuleType("torch")
    fake_torch.cuda = SimpleNamespace(is_available=lambda: True, device_count=lambda: 2)

    monkeypatch.setattr(ocr_module, "ort", fake_ort)
    monkeypatch.setattr(ocr_module, "loaded_models", {})
    monkeypatch.setattr(ocr_module, "_deepdoc_onnx_gpu_enabled", lambda: True)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    first = ocr_module.load_model(tmp_path, "rec", device_id=1)
    second = ocr_module.load_model(tmp_path, "rec", device_id=1)

    assert first is second
    assert first[0] is session
    assert first[1].entries == [("memory.enable_memory_arena_shrinkage", "cpu")]
    assert calls == [
        {
            "path": str(model_path),
            "options": calls[0]["options"],
            "providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
            "provider_options": [
                {
                    "device_id": 1,
                    "gpu_mem_limit": 2147483648,
                    "arena_extend_strategy": "kNextPowerOfTwo",
                },
                {},
            ],
        },
        {
            "path": str(model_path),
            "options": calls[0]["options"],
            "providers": ["CPUExecutionProvider"],
            "provider_options": None,
        },
    ]


def test_docx_table_composition_preserves_wide_and_narrow_return_shapes() -> None:
    parser = IntegratedPipelineDocxParser()
    compose = parser._IntegratedPipelineDocxParser__compose_table_content

    wide = pd.DataFrame(
        [
            ["H1", "H2", "H3", "H4"],
            ["a", "b", "c", "d"],
            ["e", "f", "g", "h"],
        ]
    )
    narrow = pd.DataFrame(
        [
            ["Key", "Value"],
            ["Foo", "1"],
            ["Bar", "2"],
        ]
    )

    assert compose(wide) == [
        "H1: a;H2: b;H3: c;H4: d",
        "H1: e;H2: f;H3: g;H4: h",
    ]
    assert compose(narrow) == ["Key: Foo;Value: 1\nKey: Bar;Value: 2"]


def test_figure_pdf_wrapper_returns_original_non_image_tables_without_runtime_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_imports: list[str] = []
    original_import = builtins.__import__

    def _guarded_import(name: str, *args, **kwargs):
        if name.startswith("app.third_party.integrated_pipeline"):
            seen_imports.append(name)
            raise AssertionError("optional runtime import should not happen")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)
    tables = [("plain text", ["caption"])]

    result = figure_parser.vision_figure_parser_pdf_wrapper(tbls=tables)

    assert result is tables
    assert seen_imports == []


def test_figure_pdf_wrapper_uses_parser_and_preserves_fallback_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = Image.new("RGB", (4, 4), "white")
    tables = figure_parser.vision_figure_parser_figure_data_wraper([("caption", image)])
    callbacks: list[tuple[int, str]] = []
    parser_calls: list[dict[str, object]] = []

    fake_constants = ModuleType("app.third_party.integrated_pipeline.common.constants")
    fake_constants.LLMType = SimpleNamespace(IMAGE2TEXT="image2text")
    fake_llm_service = ModuleType("app.third_party.integrated_pipeline.stubs.llm_service")

    class _FakeBundle:
        def __init__(self, tenant_id: str, llm_type: str) -> None:
            parser_calls.append({"tenant_id": tenant_id, "llm_type": llm_type})

    class _SuccessfulParser:
        def __init__(self, vision_model: object, figures_data: object, **kwargs) -> None:
            parser_calls.append(
                {
                    "vision_model_type": type(vision_model).__name__,
                    "figures_data": figures_data,
                    "kwargs": kwargs,
                }
            )

        def __call__(self, **kwargs):
            parser_calls.append({"call_kwargs": kwargs})
            return [("enriched",)]

    class _FailingParser:
        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("boom")

    fake_llm_service.LLMBundle = _FakeBundle
    monkeypatch.setitem(sys.modules, fake_constants.__name__, fake_constants)
    monkeypatch.setitem(sys.modules, fake_llm_service.__name__, fake_llm_service)
    monkeypatch.setattr(figure_parser, "VisionFigureParser", _SuccessfulParser)

    success = figure_parser.vision_figure_parser_pdf_wrapper(
        tbls=tables,
        tenant_id="tenant-7",
        callback=lambda prog, msg: callbacks.append((prog, msg)),
    )

    monkeypatch.setattr(figure_parser, "VisionFigureParser", _FailingParser)
    failure = figure_parser.vision_figure_parser_pdf_wrapper(
        tbls=tables,
        tenant_id="tenant-7",
        callback=lambda prog, msg: callbacks.append((prog, msg)),
    )

    assert success == [("enriched",)]
    assert failure is tables
    assert parser_calls == [
        {"tenant_id": "tenant-7", "llm_type": "image2text"},
        {
            "vision_model_type": "_FakeBundle",
            "figures_data": tables,
            "kwargs": {"tenant_id": "tenant-7"},
        },
        {"call_kwargs": {"callback": ANY}},
        {"tenant_id": "tenant-7", "llm_type": "image2text"},
    ]
    assert callbacks == [
        (
            -1,
            "Vision enrichment failed; using parsed tables unchanged. (boom)",
        )
    ]
