from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script(rel: str):
    path = _repo_root() / rel
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_generate_retrieval_debt_audit_writes_markdown(tmp_path: Path) -> None:
    mod = _load_script("scripts/generate_retrieval_debt_audit.py")
    out = tmp_path / "retrieval_debt_audit.md"

    rc = mod.main(["--out", str(out)])
    assert rc == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Retrieval Debt Audit" in text
    assert "Threshold Staleness" in text
    assert "TODO Hotspots" in text
