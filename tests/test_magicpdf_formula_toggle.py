from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.parsing.parsers.magic_pdf_parser import MagicPDFParser


def test_magicpdf_tools_config_respects_formula_toggle(tmp_path: Path, monkeypatch) -> None:
    # Ensure MagicPDF per-run config is written under a temp HOME (no pollution).
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MINERU_TOOLS_CONFIG_JSON", raising=False)
    monkeypatch.setattr(settings, "MINERU_TOOLS_CONFIG_JSON", "", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_FORMULA_ENABLED", True, raising=False)

    parser = MagicPDFParser()
    artifact_root = tmp_path / "magic"
    artifact_root.mkdir(parents=True, exist_ok=True)
    cfg_path = parser._ensure_tools_config(artifact_root)

    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert (data.get("formula-config") or {}).get("enable") is True

