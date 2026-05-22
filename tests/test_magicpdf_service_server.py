from __future__ import annotations

import importlib.util
from pathlib import Path


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
