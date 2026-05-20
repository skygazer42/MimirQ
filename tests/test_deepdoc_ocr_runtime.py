from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np


def test_deepdoc_load_model_uses_cpu_when_onnxruntime_has_no_cuda_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sys

    from app.deepdoc.vision import ocr

    model_dir = tmp_path / "ocr"
    model_dir.mkdir()
    (model_dir / "det.onnx").write_bytes(b"fake")
    ocr.loaded_models.clear()

    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(ocr.ort, "get_available_providers", lambda: ["CPUExecutionProvider"])

    captured: dict[str, object] = {}

    class FakeSessionOptions:
        pass

    class FakeRunOptions:
        def __init__(self) -> None:
            self.entries: dict[str, str] = {}

        def add_run_config_entry(self, key: str, value: str) -> None:
            self.entries[key] = value

    def fake_session(path, *, options=None, providers=None, provider_options=None):  # noqa: ANN001, ANN202
        captured["path"] = path
        captured["providers"] = providers
        captured["provider_options"] = provider_options
        return object()

    monkeypatch.setattr(ocr.ort, "SessionOptions", FakeSessionOptions)
    monkeypatch.setattr(ocr.ort, "RunOptions", FakeRunOptions)
    monkeypatch.setattr(ocr.ort, "InferenceSession", fake_session)

    _sess, run_options = ocr.load_model(str(model_dir), "det", device_id=0)

    assert captured["providers"] == ["CPUExecutionProvider"]
    assert captured["provider_options"] is None
    assert run_options.entries["memory.enable_memory_arena_shrinkage"] == "cpu"


def test_deepdoc_load_model_prefers_gpu_when_onnxruntime_cuda_provider_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sys

    from app.deepdoc.vision import ocr

    model_dir = tmp_path / "ocr"
    model_dir.mkdir()
    (model_dir / "det.onnx").write_bytes(b"fake")
    ocr.loaded_models.clear()

    monkeypatch.setenv("DEEPDOC_ONNX_USE_GPU", "1")
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(ocr.ort, "get_available_providers", lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"])

    captured: dict[str, object] = {}

    class FakeSessionOptions:
        pass

    class FakeRunOptions:
        def __init__(self) -> None:
            self.entries: dict[str, str] = {}

        def add_run_config_entry(self, key: str, value: str) -> None:
            self.entries[key] = value

    def fake_session(path, *, options=None, providers=None, provider_options=None):  # noqa: ANN001, ANN202
        captured["providers"] = providers
        captured["provider_options"] = provider_options
        return object()

    monkeypatch.setattr(ocr.ort, "SessionOptions", FakeSessionOptions)
    monkeypatch.setattr(ocr.ort, "RunOptions", FakeRunOptions)
    monkeypatch.setattr(ocr.ort, "InferenceSession", fake_session)

    _sess, run_options = ocr.load_model(str(model_dir), "det", device_id=0)

    assert captured["providers"] == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert captured["provider_options"][0]["device_id"] == 0
    assert run_options.entries["memory.enable_memory_arena_shrinkage"] == "gpu:0"


def test_deepdoc_load_model_defaults_to_cpu_even_when_cuda_provider_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sys

    from app.deepdoc.vision import ocr

    model_dir = tmp_path / "layout"
    model_dir.mkdir()
    (model_dir / "layout.onnx").write_bytes(b"fake")
    ocr.loaded_models.clear()

    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(ocr.ort, "get_available_providers", lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"])

    captured: dict[str, object] = {}

    class FakeSessionOptions:
        pass

    class FakeRunOptions:
        def __init__(self) -> None:
            self.entries: dict[str, str] = {}

        def add_run_config_entry(self, key: str, value: str) -> None:
            self.entries[key] = value

    def fake_session(path, *, options=None, providers=None, provider_options=None):  # noqa: ANN001, ANN202
        captured["providers"] = providers
        captured["provider_options"] = provider_options
        return object()

    monkeypatch.setattr(ocr.ort, "SessionOptions", FakeSessionOptions)
    monkeypatch.setattr(ocr.ort, "RunOptions", FakeRunOptions)
    monkeypatch.setattr(ocr.ort, "InferenceSession", fake_session)

    _sess, run_options = ocr.load_model(str(model_dir), "layout")

    assert captured["providers"] == ["CPUExecutionProvider"]
    assert captured["provider_options"] is None
    assert run_options.entries["memory.enable_memory_arena_shrinkage"] == "cpu"


def test_deepdoc_load_model_uses_gpu_zero_for_recognizers_without_device_id_when_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sys

    from app.deepdoc.vision import ocr

    model_dir = tmp_path / "layout"
    model_dir.mkdir()
    (model_dir / "layout.onnx").write_bytes(b"fake")
    ocr.loaded_models.clear()

    monkeypatch.setenv("DEEPDOC_ONNX_USE_GPU", "true")
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(ocr.ort, "get_available_providers", lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"])

    captured: dict[str, object] = {}

    class FakeSessionOptions:
        pass

    class FakeRunOptions:
        def __init__(self) -> None:
            self.entries: dict[str, str] = {}

        def add_run_config_entry(self, key: str, value: str) -> None:
            self.entries[key] = value

    def fake_session(path, *, options=None, providers=None, provider_options=None):  # noqa: ANN001, ANN202
        captured["providers"] = providers
        captured["provider_options"] = provider_options
        return object()

    monkeypatch.setattr(ocr.ort, "SessionOptions", FakeSessionOptions)
    monkeypatch.setattr(ocr.ort, "RunOptions", FakeRunOptions)
    monkeypatch.setattr(ocr.ort, "InferenceSession", fake_session)

    _sess, run_options = ocr.load_model(str(model_dir), "layout")

    assert captured["providers"] == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert captured["provider_options"][0]["device_id"] == 0
    assert run_options.entries["memory.enable_memory_arena_shrinkage"] == "gpu:0"


def test_deepdoc_load_model_falls_back_to_cpu_when_cuda_session_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sys

    from app.deepdoc.vision import ocr

    model_dir = tmp_path / "ocr"
    model_dir.mkdir()
    (model_dir / "det.onnx").write_bytes(b"fake")
    ocr.loaded_models.clear()

    monkeypatch.setenv("DEEPDOC_ONNX_USE_GPU", "1")
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(ocr.ort, "get_available_providers", lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"])

    providers_seen: list[list[str]] = []

    class FakeSessionOptions:
        pass

    class FakeRunOptions:
        def __init__(self) -> None:
            self.entries: dict[str, str] = {}

        def add_run_config_entry(self, key: str, value: str) -> None:
            self.entries[key] = value

    def fake_session(path, *, options=None, providers=None, provider_options=None):  # noqa: ANN001, ANN202
        providers_seen.append(providers)
        if providers and providers[0] == "CUDAExecutionProvider":
            raise RuntimeError("cuda provider failed")
        return object()

    monkeypatch.setattr(ocr.ort, "SessionOptions", FakeSessionOptions)
    monkeypatch.setattr(ocr.ort, "RunOptions", FakeRunOptions)
    monkeypatch.setattr(ocr.ort, "InferenceSession", fake_session)

    _sess, run_options = ocr.load_model(str(model_dir), "det", device_id=0)

    assert providers_seen == [["CUDAExecutionProvider", "CPUExecutionProvider"], ["CPUExecutionProvider"]]
    assert run_options.entries["memory.enable_memory_arena_shrinkage"] == "cpu"


def test_deepdoc_text_recognizer_batches_by_width_bucket(monkeypatch) -> None:
    from app.deepdoc.vision import ocr

    monkeypatch.setenv("DEEPDOC_OCR_REC_BATCH_SIZE", "8")
    monkeypatch.setenv("DEEPDOC_OCR_REC_WIDTH_BUCKET_RATIO", "1.0")

    recognizer = object.__new__(ocr.TextRecognizer)
    recognizer.rec_image_shape = [3, 48, 320]
    recognizer.rec_batch_num = 16
    recognizer.input_tensor = SimpleNamespace(name="image", shape=[None, 3, 48, "dynamic"])
    recognizer.run_options = None
    run_batch_sizes: list[int] = []

    class FakePredictor:
        def run(self, _names, input_dict, _run_options=None):  # noqa: ANN001, ANN202
            batch = input_dict["image"]
            run_batch_sizes.append(int(batch.shape[0]))
            return [np.zeros((batch.shape[0], 1), dtype=np.float32)]

    recognizer.predictor = FakePredictor()
    recognizer.postprocess_op = lambda preds: [(f"text-{idx}", 0.99) for idx in range(int(preds.shape[0]))]

    images = [
        np.zeros((48, 320, 3), dtype=np.uint8),
        np.zeros((48, 700, 3), dtype=np.uint8),
        np.zeros((48, 710, 3), dtype=np.uint8),
        np.zeros((48, 1300, 3), dtype=np.uint8),
    ]

    results, elapsed = recognizer(images)

    assert len(results) == 4
    assert elapsed >= 0
    assert run_batch_sizes == [1, 2, 1]
    assert recognizer.last_profile["schema"] == "mimirq.deepdoc_ocr_recognition_profile.v1"
    assert recognizer.last_profile["image_count"] == 4
    assert recognizer.last_profile["batch_size"] == 8
    assert recognizer.last_profile["bucket_count"] == 3
    assert recognizer.last_profile["batch_count"] == 3
    assert all(isinstance(batch["elapsed_ms"], int) for batch in recognizer.last_profile["batches"])
