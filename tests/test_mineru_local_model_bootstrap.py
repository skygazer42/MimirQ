from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path("docker/mineru/start_local_api.py")
    spec = importlib.util.spec_from_file_location("mineru_start_local_api", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ensure_local_model_config_writes_models_dir(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    home = tmp_path / "home"
    hf = home / ".cache" / "huggingface" / "hub"
    (hf / "models--opendatalab--PDF-Extract-Kit-1.0" / "snapshots" / "pipe123").mkdir(parents=True)
    (hf / "models--opendatalab--MinerU2.5-2509-1.2B" / "snapshots" / "vlm123").mkdir(parents=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MINERU_MODEL_SOURCE", "local")

    cfg_path = module.ensure_local_model_config()

    assert cfg_path is not None and cfg_path.exists()
    data = __import__("json").loads(cfg_path.read_text(encoding="utf-8"))
    assert data["models-dir"]["pipeline"].endswith("pipe123")
    assert data["models-dir"]["vlm"].endswith("vlm123")
