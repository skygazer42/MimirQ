from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


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
