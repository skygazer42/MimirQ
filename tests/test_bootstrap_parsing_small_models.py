from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path("scripts/bootstrap_parsing_small_models.py")
    spec = importlib.util.spec_from_file_location("bootstrap_parsing_small_models", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_manifest(path: Path) -> None:
    path.write_text(
        """
table_structure:
  default: local_tsr
  models:
    local_tsr:
      kind: onnx
      path: local/tsr.onnx
      task: table_structure
    tatr:
      kind: hf_transformers
      repo_id: microsoft/table-transformer-structure-recognition-v1.1-all
      task: object_detection
      optional: true
ocr_recognition:
  default: local_rec
  models:
    local_rec:
      kind: onnx
      path: local/rec.onnx
      task: ocr_recognition
    pp_ocrv5:
      kind: hf_transformers
      repo_id: PaddlePaddle/PP-OCRv5_mobile_rec_safetensors
      task: image-to-text
      optional: true
""",
        encoding="utf-8",
    )


def test_bootstrap_downloads_selected_hf_model_to_project_cache(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    manifest_path = tmp_path / "models.yaml"
    _write_manifest(manifest_path)

    def _fake_download_hf_snapshot(*, repo_id, revision=None, local_dir=None):  # noqa: ANN001, ANN202
        assert repo_id == "microsoft/table-transformer-structure-recognition-v1.1-all"
        assert local_dir is not None
        out = Path(local_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "model.safetensors").write_text("fake", encoding="utf-8")
        return module.HfSnapshotResult(repo_id=repo_id, revision=revision, path=out)

    monkeypatch.setattr(module, "download_hf_snapshot", _fake_download_hf_snapshot)

    result = module.bootstrap_selected_models(
        manifest_path=manifest_path,
        selections=["table_structure:tatr"],
        output_root=tmp_path / "resources",
        convert_onnx=False,
    )

    assert result["downloaded"] == 1
    assert result["converted"] == 0
    item = result["models"][0]
    assert item["task"] == "table_structure"
    assert item["model_id"] == "tatr"
    assert item["status"] == "downloaded"
    assert item["snapshot_path"].endswith("resources/hf/table_structure__tatr__microsoft__table-transformer-structure-recognition-v1.1-all")


def test_bootstrap_converts_when_no_onnx_and_requested(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    manifest_path = tmp_path / "models.yaml"
    _write_manifest(manifest_path)

    def _fake_download_hf_snapshot(*, repo_id, revision=None, local_dir=None):  # noqa: ANN001, ANN202
        out = Path(local_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "config.json").write_text("{}", encoding="utf-8")
        return module.HfSnapshotResult(repo_id=repo_id, revision=revision, path=out)

    def _fake_convert(*, spec, snapshot_path, onnx_path, opset):  # noqa: ANN001, ANN202
        onnx_path.parent.mkdir(parents=True, exist_ok=True)
        onnx_path.write_bytes(b"onnx")
        return {"opset": int(opset), "backend": "fake"}

    monkeypatch.setattr(module, "download_hf_snapshot", _fake_download_hf_snapshot)
    monkeypatch.setattr(module, "_convert_transformers_to_onnx", _fake_convert)

    result = module.bootstrap_selected_models(
        manifest_path=manifest_path,
        selections=["ocr_recognition:pp_ocrv5"],
        output_root=tmp_path / "resources",
        convert_onnx=True,
        onnx_opset=17,
    )

    assert result["downloaded"] == 1
    assert result["converted"] == 1
    item = result["models"][0]
    assert item["status"] == "downloaded_converted"
    assert item["onnx_path"].endswith("resources/hf_onnx/ocr_recognition__pp_ocrv5__PaddlePaddle__PP-OCRv5_mobile_rec_safetensors/model.onnx")
    assert Path(item["onnx_path"]).read_bytes() == b"onnx"


def test_bootstrap_records_optional_conversion_failure_without_fake_onnx(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    manifest_path = tmp_path / "models.yaml"
    _write_manifest(manifest_path)

    def _fake_download_hf_snapshot(*, repo_id, revision=None, local_dir=None):  # noqa: ANN001, ANN202
        out = Path(local_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "config.json").write_text("{}", encoding="utf-8")
        return module.HfSnapshotResult(repo_id=repo_id, revision=revision, path=out)

    def _fake_convert(*, spec, snapshot_path, onnx_path, opset):  # noqa: ANN001, ANN202
        raise RuntimeError("unsupported architecture")

    monkeypatch.setattr(module, "download_hf_snapshot", _fake_download_hf_snapshot)
    monkeypatch.setattr(module, "_convert_transformers_to_onnx", _fake_convert)

    result = module.bootstrap_selected_models(
        manifest_path=manifest_path,
        selections=["ocr_recognition:pp_ocrv5"],
        output_root=tmp_path / "resources",
        convert_onnx=True,
    )

    item = result["models"][0]
    assert result["downloaded"] == 1
    assert result["converted"] == 0
    assert item["status"] == "downloaded_conversion_failed"
    assert item["onnx_path"] is None
    assert "unsupported architecture" in item["conversion_error"]


def test_bootstrap_skips_cpu_infeasible_hf_model_without_download(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    manifest_path = tmp_path / "models.yaml"
    manifest_path.write_text(
        """
layout:
  default: local
  models:
    local:
      kind: onnx
      path: local.onnx
      task: document_layout
    vlm:
      kind: hf_transformers
      repo_id: example/too-large-vlm
      task: image-to-text
      optional: true
      cpu_feasible: false
""",
        encoding="utf-8",
    )

    def _fail_download(**_kwargs):  # noqa: ANN202
        raise AssertionError("download should not be called")

    monkeypatch.setattr(module, "download_hf_snapshot", _fail_download)

    result = module.bootstrap_selected_models(
        manifest_path=manifest_path,
        selections=["layout:vlm"],
        output_root=tmp_path / "resources",
    )

    assert result["downloaded"] == 0
    assert result["models"][0]["status"] == "skipped"
    assert result["models"][0]["reason"] == "cpu_inference_not_supported"
