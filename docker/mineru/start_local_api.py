from __future__ import annotations

import json
import os
from pathlib import Path


def _config_path() -> Path:
    name = (os.environ.get("MINERU_TOOLS_CONFIG_JSON") or "mineru.json").strip() or "mineru.json"
    path = Path(name)
    if path.is_absolute():
        return path
    return Path.home() / path


def _existing_snapshot_root(path: Path) -> str | None:
    if not path.exists():
        return None
    snapshots = [p for p in path.iterdir() if p.is_dir()]
    if not snapshots:
        return None
    snapshots.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(snapshots[0])


def _discover_local_model_dirs() -> dict[str, str]:
    roots: dict[str, str] = {}

    hf_hub = Path.home() / ".cache" / "huggingface" / "hub"
    pipeline = _existing_snapshot_root(hf_hub / "models--opendatalab--PDF-Extract-Kit-1.0" / "snapshots")
    vlm = _existing_snapshot_root(hf_hub / "models--opendatalab--MinerU2.5-2509-1.2B" / "snapshots")

    if pipeline:
        roots["pipeline"] = pipeline
    if vlm:
        roots["vlm"] = vlm
    return roots


def ensure_local_model_config() -> Path | None:
    if (os.environ.get("MINERU_MODEL_SOURCE") or "").strip().lower() != "local":
        return None

    cfg_path = _config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {}
    if cfg_path.exists():
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}

    discovered = _discover_local_model_dirs()
    if not discovered:
        return cfg_path

    models_dir = data.get("models-dir")
    if not isinstance(models_dir, dict):
        models_dir = {}
        data["models-dir"] = models_dir

    for key, value in discovered.items():
        models_dir.setdefault(key, value)

    cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cfg_path


def main() -> None:
    ensure_local_model_config()
    os.execvp("mineru-api", ["mineru-api", "--host", "0.0.0.0", "--port", "8000"])


if __name__ == "__main__":
    main()
