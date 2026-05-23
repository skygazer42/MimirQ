from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml


def _load_magicpdf_service_module():
    server_path = Path(__file__).resolve().parents[1] / "docker" / "magicpdf" / "server.py"
    spec = importlib.util.spec_from_file_location("mimirq_magicpdf_service_test", server_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_magicpdf_service_resolves_pdf_extract_kit_models_from_shared_cache(tmp_path: Path) -> None:
    service = _load_magicpdf_service_module()
    models_dir = (
        tmp_path
        / "huggingface"
        / "hub"
        / "models--opendatalab--PDF-Extract-Kit-1.0"
        / "snapshots"
        / "abc123"
        / "models"
    )
    for rel in service._REQUIRED_MODEL_FILES:
        target = models_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stub", encoding="utf-8")

    assert service._resolve_models_dir(str(tmp_path)) == models_dir


def test_magicpdf_service_patches_ch_doc_model_mapping_when_only_v5_rec_exists(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    service = _load_magicpdf_service_module()
    models_dir = tmp_path / "models"
    for rel in service._REQUIRED_MODEL_FILES:
        target = models_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stub", encoding="utf-8")

    cfg_path = tmp_path / "models_config.yml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "lang": {
                    "ch": {
                        "det": "ch_PP-OCRv3_det_infer.pth",
                        "rec": "ch_PP-OCRv4_rec_server_doc_infer.pth",
                        "dict": "ppocrv4_doc_dict.txt",
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(service, "_models_config_path", lambda: cfg_path)

    service._ensure_ch_doc_model_compat(models_dir)

    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert data["lang"]["ch"]["rec"] == "ch_PP-OCRv5_rec_infer.pth"
    assert data["lang"]["ch"]["dict"] == "ppocrv5_dict.txt"


def test_magicpdf_service_keeps_doc_model_mapping_when_expected_model_exists(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    service = _load_magicpdf_service_module()
    models_dir = tmp_path / "models"
    for rel in service._REQUIRED_MODEL_FILES:
        target = models_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stub", encoding="utf-8")
    expected = models_dir / "OCR" / "paddleocr_torch" / "ch_PP-OCRv4_rec_server_doc_infer.pth"
    expected.write_text("doc-stub", encoding="utf-8")

    cfg_path = tmp_path / "models_config.yml"
    original = {
        "lang": {
            "ch": {
                "det": "ch_PP-OCRv3_det_infer.pth",
                "rec": "ch_PP-OCRv4_rec_server_doc_infer.pth",
                "dict": "ppocrv4_doc_dict.txt",
            }
        }
    }
    cfg_path.write_text(yaml.safe_dump(original, sort_keys=False), encoding="utf-8")

    monkeypatch.setattr(service, "_models_config_path", lambda: cfg_path)

    service._ensure_ch_doc_model_compat(models_dir)

    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert data == original


def test_magicpdf_service_defaults_to_cuda_device(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("MAGIC_PDF_DEVICE_MODE", raising=False)

    service = _load_magicpdf_service_module()

    assert service._DEFAULT_DEVICE_MODE == "cuda"


def test_magicpdf_service_health_requires_cuda_when_cuda_is_default(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.delenv("MAGIC_PDF_DEVICE_MODE", raising=False)
    service = _load_magicpdf_service_module()

    monkeypatch.setattr(service.shutil, "which", lambda _cli: "/usr/local/bin/magic-pdf")
    monkeypatch.setattr(service, "_resolve_models_dir", lambda _configured: tmp_path / "models")
    monkeypatch.setattr(service, "_cuda_available", lambda: False)

    health = service.health()

    assert health["ok"] is False
    assert health["default_device_mode"] == "cuda"
    assert health["cuda_available"] is False


def test_magicpdf_service_health_allows_cpu_without_cuda(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.setenv("MAGIC_PDF_DEVICE_MODE", "cpu")
    service = _load_magicpdf_service_module()

    monkeypatch.setattr(service.shutil, "which", lambda _cli: "/usr/local/bin/magic-pdf")
    monkeypatch.setattr(service, "_resolve_models_dir", lambda _configured: tmp_path / "models")
    monkeypatch.setattr(service, "_cuda_available", lambda: False)

    health = service.health()

    assert health["ok"] is True
    assert health["default_device_mode"] == "cpu"
    assert health["cuda_available"] is False
