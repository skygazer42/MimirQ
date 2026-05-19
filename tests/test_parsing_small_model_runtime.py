from __future__ import annotations

from pathlib import Path

import pytest


def test_default_small_model_manifest_keeps_deepdoc_onnx_defaults() -> None:
    from app.parsing.models.manifest import load_default_small_model_manifest

    manifest = load_default_small_model_manifest()

    layout = manifest.get_default("layout")
    table = manifest.get_default("table_structure")

    assert layout.model_id == "deepdoc_layout_onnx"
    assert layout.kind == "onnx"
    assert layout.resolved_path().as_posix().endswith("app/deepdoc/resources/models/layout/layout.onnx")
    assert layout.resolved_path().exists()

    assert table.model_id == "deepdoc_tsr_onnx"
    assert table.kind == "onnx"
    assert table.resolved_path().as_posix().endswith("app/deepdoc/resources/models/table/tsr.onnx")
    assert table.resolved_path().exists()


def test_manifest_resolves_huggingface_onnx_ocr_and_preprocess_models() -> None:
    from app.parsing.models.manifest import load_default_small_model_manifest
    from app.parsing.models.runtime import SmallModelRuntime

    runtime = SmallModelRuntime(manifest=load_default_small_model_manifest())

    for task, model_id in [
        ("ocr_detection", "monkt_paddleocr_v5_det_onnx"),
        ("ocr_recognition", "monkt_paddleocr_chinese_rec_onnx"),
        ("document_orientation", "monkt_pp_lcnet_doc_ori_onnx"),
        ("document_rectification", "monkt_uvdoc_onnx"),
        ("textline_orientation", "monkt_pp_lcnet_textline_ori_onnx"),
    ]:
        status = runtime.resolve(task, model_id=model_id, allow_download=False)
        assert status.available is True
        assert status.kind == "onnx"
        assert status.path is not None
        assert status.path.exists()


def test_manifest_reports_optional_hf_models_without_downloading() -> None:
    from app.parsing.models.manifest import load_default_small_model_manifest
    from app.parsing.models.runtime import SmallModelRuntime

    manifest = load_default_small_model_manifest()
    runtime = SmallModelRuntime(manifest=manifest)

    status = runtime.resolve("layout", model_id="pp_doclayout_v3", allow_download=False)

    assert status.model_id == "pp_doclayout_v3"
    assert status.kind == "hf_transformers"
    assert status.available is False
    assert status.reason == "cpu_inference_not_supported"
    assert status.repo_id == "PaddlePaddle/PP-DocLayoutV3_safetensors"
    assert status.to_metadata()["version"] == "unresolved"
    assert isinstance(status.to_metadata()["elapsed_ms"], int)


def test_runtime_resolves_downloaded_hf_snapshot_without_network(tmp_path: Path) -> None:
    from app.parsing.models.manifest import load_small_model_manifest
    from app.parsing.models.runtime import SmallModelRuntime

    snapshot = tmp_path / "hf" / "ocr"
    snapshot.mkdir(parents=True)
    manifest_path = tmp_path / "models.yaml"
    manifest_path.write_text(
        f"""
ocr_recognition:
  default: pp_ocr
  models:
    pp_ocr:
      kind: hf_transformers
      repo_id: PaddlePaddle/PP-OCRv5_mobile_rec_safetensors
      path: {snapshot.as_posix()}
      task: image-to-text
      optional: true
""",
        encoding="utf-8",
    )

    status = SmallModelRuntime(manifest=load_small_model_manifest(manifest_path)).resolve("ocr_recognition")

    assert status.available is True
    assert status.reason is None
    assert status.path == snapshot
    assert status.to_metadata()["version"] == "local"


def test_runtime_loads_onnx_through_lazy_session_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.parsing.models.manifest import load_default_small_model_manifest
    from app.parsing.models.runtime import SmallModelRuntime

    calls: list[str] = []

    class FakeOrt:
        @staticmethod
        def get_available_providers() -> list[str]:
            return ["CPUExecutionProvider"]

        @staticmethod
        def InferenceSession(path: str, providers: list[str] | None = None) -> dict[str, object]:  # noqa: N802
            calls.append(path)
            return {"path": path, "providers": providers}

    monkeypatch.setattr("app.parsing.models.runtime.require_dependency", lambda *args, **kwargs: FakeOrt)

    runtime = SmallModelRuntime(manifest=load_default_small_model_manifest())
    loaded = runtime.load("layout")

    assert loaded.model_id == "deepdoc_layout_onnx"
    assert loaded.kind == "onnx"
    assert loaded.available is True
    assert calls == [str(loaded.path)]
    assert loaded.handle == {"path": str(loaded.path), "providers": ["CPUExecutionProvider"]}
    assert loaded.metadata is not None
    assert loaded.metadata["selected_providers"] == ["CPUExecutionProvider"]


def test_runtime_prefers_cuda_provider_when_available_even_if_manifest_lists_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.parsing.models.manifest import load_default_small_model_manifest
    from app.parsing.models.runtime import SmallModelRuntime

    monkeypatch.setenv("PARSING_SMALL_MODELS_USE_GPU", "1")
    sessions: list[list[str] | None] = []

    class FakeOrt:
        @staticmethod
        def get_available_providers() -> list[str]:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]

        @staticmethod
        def InferenceSession(path: str, providers: list[str] | None = None) -> dict[str, object]:  # noqa: N802
            sessions.append(providers)
            return {"path": path, "providers": providers}

    monkeypatch.setattr("app.parsing.models.runtime.require_dependency", lambda *args, **kwargs: FakeOrt)

    loaded = SmallModelRuntime(manifest=load_default_small_model_manifest()).load(
        "ocr_detection",
        model_id="monkt_paddleocr_v5_det_onnx",
    )

    assert sessions == [["CUDAExecutionProvider", "CPUExecutionProvider"]]
    assert loaded.metadata is not None
    assert loaded.metadata["selected_providers"] == ["CUDAExecutionProvider", "CPUExecutionProvider"]


def test_runtime_defaults_to_cpu_when_cuda_provider_is_available_but_not_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.parsing.models.manifest import load_default_small_model_manifest
    from app.parsing.models.runtime import SmallModelRuntime

    sessions: list[list[str] | None] = []

    class FakeOrt:
        @staticmethod
        def get_available_providers() -> list[str]:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]

        @staticmethod
        def InferenceSession(path: str, providers: list[str] | None = None) -> dict[str, object]:  # noqa: N802
            sessions.append(providers)
            return {"path": path, "providers": providers}

    monkeypatch.delenv("PARSING_SMALL_MODELS_USE_GPU", raising=False)
    monkeypatch.delenv("DEEPDOC_ONNX_USE_GPU", raising=False)
    monkeypatch.setattr("app.parsing.models.runtime.require_dependency", lambda *args, **kwargs: FakeOrt)

    loaded = SmallModelRuntime(manifest=load_default_small_model_manifest()).load(
        "ocr_detection",
        model_id="monkt_paddleocr_v5_det_onnx",
    )

    assert sessions == [["CPUExecutionProvider"]]
    assert loaded.metadata is not None
    assert loaded.metadata["selected_providers"] == ["CPUExecutionProvider"]


def test_runtime_falls_back_to_cpu_if_cuda_session_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.parsing.models.manifest import load_default_small_model_manifest
    from app.parsing.models.runtime import SmallModelRuntime

    monkeypatch.setenv("PARSING_SMALL_MODELS_USE_GPU", "1")
    sessions: list[list[str] | None] = []

    class FakeOrt:
        @staticmethod
        def get_available_providers() -> list[str]:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]

        @staticmethod
        def InferenceSession(path: str, providers: list[str] | None = None) -> dict[str, object]:  # noqa: N802
            sessions.append(providers)
            if providers and providers[0] == "CUDAExecutionProvider":
                raise RuntimeError("cuda init failed")
            return {"path": path, "providers": providers}

    monkeypatch.setattr("app.parsing.models.runtime.require_dependency", lambda *args, **kwargs: FakeOrt)

    loaded = SmallModelRuntime(manifest=load_default_small_model_manifest()).load(
        "table_structure",
        model_id="tatr_v1_1_all_onnx",
    )

    assert sessions == [["CUDAExecutionProvider", "CPUExecutionProvider"], ["CPUExecutionProvider"]]
    assert loaded.metadata is not None
    assert loaded.metadata["selected_providers"] == ["CPUExecutionProvider"]
    assert "cuda init failed" in loaded.metadata["provider_fallback_reason"]


def test_custom_manifest_rejects_missing_required_onnx(tmp_path: Path) -> None:
    from app.parsing.models.manifest import load_small_model_manifest
    from app.parsing.models.runtime import SmallModelRuntime

    manifest_path = tmp_path / "models.yaml"
    manifest_path.write_text(
        """
layout:
  default: missing_layout
  models:
    missing_layout:
      kind: onnx
      path: missing/layout.onnx
      task: document_layout
      optional: false
""",
        encoding="utf-8",
    )

    manifest = load_small_model_manifest(manifest_path)
    status = SmallModelRuntime(manifest=manifest).resolve("layout")

    assert status.available is False
    assert status.reason == "local_model_missing"
    assert status.path == tmp_path / "missing/layout.onnx"


def test_runtime_rejects_models_above_cpu_size_limit(tmp_path: Path) -> None:
    from app.parsing.models.manifest import load_small_model_manifest
    from app.parsing.models.runtime import SmallModelRuntime

    large_model = tmp_path / "large.onnx"
    large_model.write_bytes(b"0")
    with large_model.open("ab") as handle:
        handle.truncate(501 * 1024 * 1024)
    manifest_path = tmp_path / "models.yaml"
    manifest_path.write_text(
        f"""
layout:
  default: large_layout
  models:
    large_layout:
      kind: onnx
      path: {large_model.as_posix()}
      task: document_layout
      optional: true
      max_size_mb: 500
""",
        encoding="utf-8",
    )

    status = SmallModelRuntime(manifest=load_small_model_manifest(manifest_path)).resolve("layout")

    assert status.available is False
    assert status.reason == "model_too_large_for_cpu"
    assert status.to_metadata()["size_mb"] > 500


def test_runtime_rejects_cpu_infeasible_models_before_loading(tmp_path: Path) -> None:
    from app.parsing.models.manifest import load_small_model_manifest
    from app.parsing.models.runtime import SmallModelRuntime

    model = tmp_path / "vlm.onnx"
    model.write_bytes(b"onnx")
    manifest_path = tmp_path / "models.yaml"
    manifest_path.write_text(
        f"""
layout:
  default: vlm
  models:
    vlm:
      kind: onnx
      path: {model.as_posix()}
      task: document_layout
      optional: true
      cpu_feasible: false
""",
        encoding="utf-8",
    )

    status = SmallModelRuntime(manifest=load_small_model_manifest(manifest_path)).resolve("layout")

    assert status.available is False
    assert status.reason == "cpu_inference_not_supported"
