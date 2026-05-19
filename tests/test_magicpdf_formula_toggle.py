from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.parsing.parsers.magic_pdf_parser import MagicPDFParser, resolve_magicpdf_models_dir


def _write_required_models(models_dir: Path) -> None:
    for rel in MagicPDFParser.required_model_files():
        target = models_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stub", encoding="utf-8")


def test_magicpdf_tools_config_respects_formula_toggle(tmp_path: Path, monkeypatch) -> None:
    # Ensure MagicPDF per-run config is written under a temp HOME (no pollution).
    models_dir = tmp_path / "models"
    _write_required_models(models_dir)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MINERU_TOOLS_CONFIG_JSON", raising=False)
    monkeypatch.setattr(settings, "MINERU_TOOLS_CONFIG_JSON", "", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_MODELS_DIR", str(models_dir), raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_FORMULA_ENABLED", True, raising=False)

    parser = MagicPDFParser()
    artifact_root = tmp_path / "magic"
    artifact_root.mkdir(parents=True, exist_ok=True)
    cfg_path = parser._ensure_tools_config(artifact_root)

    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert (data.get("formula-config") or {}).get("enable") is True


def test_magicpdf_tools_config_uses_configured_models_dir(tmp_path: Path, monkeypatch) -> None:
    models_dir = tmp_path / "models"
    _write_required_models(models_dir)

    monkeypatch.setattr(settings, "MAGIC_PDF_MODELS_DIR", str(models_dir), raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_DEVICE_MODE", "cpu", raising=False)
    monkeypatch.setattr(settings, "MINERU_TOOLS_CONFIG_JSON", "", raising=False)
    monkeypatch.delenv("MINERU_TOOLS_CONFIG_JSON", raising=False)

    parser = MagicPDFParser()
    artifact_root = tmp_path / "artifact"
    artifact_root.mkdir(parents=True, exist_ok=True)
    cfg_path = parser._ensure_tools_config(artifact_root)

    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert data["models-dir"] == str(models_dir)
    assert data["device-mode"] == "cpu"
    assert (data.get("table-config") or {}).get("enable") is False


def test_magicpdf_model_dir_resolver_requires_expected_files(tmp_path: Path) -> None:
    models_dir = tmp_path / "snapshots" / "abc" / "models"
    models_dir.mkdir(parents=True)
    assert resolve_magicpdf_models_dir(str(models_dir)) is None

    _write_required_models(models_dir)

    assert resolve_magicpdf_models_dir(str(models_dir)) == models_dir
