from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REMOTE_MODEL_SOURCES = {"huggingface", "modelscope"}
DOWNLOAD_MODEL_TYPES = {"pipeline", "vlm", "all"}
PIPELINE_REQUIRED_FILES = (
    "models/OCR/paddleocr_torch/ch_PP-OCRv4_rec_server_doc_infer.pth",
)
VLM_REQUIRED_FILES = ("config.json",)


def _config_path() -> Path:
    name = (os.environ.get("MINERU_TOOLS_CONFIG_JSON") or "mineru.json").strip() or "mineru.json"
    home = Path.home().resolve(strict=False)
    path = Path(name).expanduser()
    candidate = path.resolve(strict=False) if path.is_absolute() else (home / path).resolve(strict=False)
    try:
        candidate.relative_to(home)
    except ValueError:
        return home / "mineru.json"
    return candidate


def _existing_snapshot_root(path: Path) -> str | None:
    if not path.exists():
        return None
    snapshots = [p for p in path.iterdir() if p.is_dir()]
    if not snapshots:
        return None
    snapshots.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(snapshots[0])


def _load_config() -> dict:
    cfg_path = _config_path()
    if not cfg_path.exists():
        return {}
    try:
        loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


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


def _configured_model_dirs() -> dict[str, str]:
    models_dir = _load_config().get("models-dir")
    if not isinstance(models_dir, dict):
        return {}
    return {str(key): str(value) for key, value in models_dir.items() if isinstance(value, str) and value.strip()}


def _candidate_model_roots(model_type: str) -> list[Path]:
    roots: list[Path] = []
    configured = _configured_model_dirs().get(model_type)
    if configured:
        roots.append(Path(configured).expanduser())
    discovered = _discover_local_model_dirs().get(model_type)
    if discovered:
        roots.append(Path(discovered))

    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve(strict=False))
        if key not in seen:
            seen.add(key)
            deduped.append(root)
    return deduped


def _required_files_ready(model_type: str) -> bool:
    required = PIPELINE_REQUIRED_FILES if model_type == "pipeline" else VLM_REQUIRED_FILES
    return any(root.exists() and all((root / rel).exists() for rel in required) for root in _candidate_model_roots(model_type))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _download_source() -> str:
    source = (os.environ.get("MINERU_MODEL_DOWNLOAD_SOURCE") or "huggingface").strip().lower()
    return source if source in REMOTE_MODEL_SOURCES else "huggingface"


def _download_type_for(required_types: list[str]) -> str | None:
    configured = (os.environ.get("MINERU_MODEL_DOWNLOAD_TYPE") or "auto").strip().lower()
    if configured in DOWNLOAD_MODEL_TYPES:
        return configured
    missing = [model_type for model_type in required_types if not _required_files_ready(model_type)]
    if not missing:
        return None
    if set(missing) == {"pipeline", "vlm"}:
        return "all"
    return missing[0]


def ensure_models(required_types: list[str]) -> None:
    """Populate the mounted model cache when required local models are missing."""
    if not _env_bool("MINERU_AUTO_DOWNLOAD_MODELS", True):
        return

    requested = sorted({model_type for model_type in required_types if model_type in {"pipeline", "vlm"}})
    download_type = _download_type_for(requested)
    if not download_type:
        return

    cmd = ["mineru-models-download", "-s", _download_source(), "-m", download_type]
    print(f"Ensuring MinerU {download_type} models in mounted cache: {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True)


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
    if "--download-models-only" in sys.argv:
        ensure_models(["pipeline", "vlm"])
        ensure_local_model_config()
        return

    backend = (os.environ.get("MINERU_BACKEND") or "pipeline").strip().lower().replace("_", "-")
    ensure_models(["pipeline"] if backend == "pipeline" else [])
    ensure_local_model_config()
    args = ["mineru-api", "--host", "0.0.0.0", "--port", "8000"]
    allow_http_client = (os.environ.get("MINERU_API_ALLOW_PUBLIC_HTTP_CLIENT") or "1").strip().lower()
    if allow_http_client in {"1", "true", "yes", "on"}:
        args.append("--allow-public-http-client")
    os.execvp("mineru-api", args)


if __name__ == "__main__":
    main()
