
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MANIFEST_PATH = _REPO_ROOT / "config" / "parsing_small_models.yaml"

SmallModelKind = Literal["onnx", "hf_transformers"]


@dataclass(frozen=True, slots=True)
class SmallModelSpec:
    task: str
    model_id: str
    kind: SmallModelKind
    optional: bool = False
    path: str | None = None
    repo_id: str | None = None
    revision: str | None = None
    pipeline_task: str | None = None
    providers: tuple[str, ...] = ()
    max_size_mb: float | None = None
    cpu_feasible: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)
    _base_dir: Path = field(default=_REPO_ROOT, repr=False, compare=False)

    def resolved_path(self) -> Path:
        if not self.path:
            return self._base_dir
        raw = Path(self.path)
        if raw.is_absolute():
            return raw
        return (self._base_dir / raw).resolve()

    def to_metadata(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "task": self.task,
            "model_id": self.model_id,
            "kind": self.kind,
            "optional": bool(self.optional),
        }
        if self.path:
            out["path"] = str(self.resolved_path())
        if self.repo_id:
            out["repo_id"] = self.repo_id
        if self.revision:
            out["revision"] = self.revision
        if self.pipeline_task:
            out["pipeline_task"] = self.pipeline_task
        if self.providers:
            out["providers"] = list(self.providers)
        if self.max_size_mb is not None:
            out["max_size_mb"] = float(self.max_size_mb)
        out["cpu_feasible"] = bool(self.cpu_feasible)
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out


@dataclass(frozen=True, slots=True)
class SmallModelManifest:
    path: Path
    tasks: Mapping[str, Mapping[str, SmallModelSpec]]
    defaults: Mapping[str, str]

    def get_default(self, task: str) -> SmallModelSpec:
        task_key = str(task or "").strip()
        model_id = self.defaults.get(task_key)
        if not model_id:
            raise KeyError(f"missing default model for task '{task_key}'")
        return self.get(task_key, model_id=model_id)

    def get(self, task: str, *, model_id: str) -> SmallModelSpec:
        task_key = str(task or "").strip()
        model_key = str(model_id or "").strip()
        models = self.tasks.get(task_key)
        if not models:
            raise KeyError(f"unknown small-model task '{task_key}'")
        spec = models.get(model_key)
        if spec is None:
            raise KeyError(f"unknown small model '{model_key}' for task '{task_key}'")
        return spec

    def list_task_models(self, task: str) -> list[SmallModelSpec]:
        return list((self.tasks.get(str(task or "").strip()) or {}).values())


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _coerce_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, list | tuple):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_spec(*, task: str, model_id: str, raw: Mapping[str, Any], base_dir: Path) -> SmallModelSpec:
    kind = str(raw.get("kind") or "").strip()
    if kind not in {"onnx", "hf_transformers"}:
        raise ValueError(f"invalid small-model kind for {task}.{model_id}: {kind!r}")

    metadata = raw.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    cpu_feasible_raw = raw.get("cpu_feasible", metadata.get("cpu_feasible"))

    return SmallModelSpec(
        task=task,
        model_id=model_id,
        kind=kind,  # type: ignore[arg-type]
        optional=_coerce_bool(raw.get("optional"), default=False),
        path=str(raw.get("path")).strip() if raw.get("path") is not None else None,
        repo_id=str(raw.get("repo_id")).strip() if raw.get("repo_id") is not None else None,
        revision=str(raw.get("revision")).strip() if raw.get("revision") is not None else None,
        pipeline_task=str(raw.get("task")).strip() if raw.get("task") is not None else None,
        providers=_coerce_str_tuple(raw.get("providers")),
        max_size_mb=_coerce_float(raw.get("max_size_mb", metadata.get("max_size_mb"))),
        cpu_feasible=_coerce_bool(cpu_feasible_raw, default=True),
        metadata=dict(metadata),
        _base_dir=base_dir,
    )


def load_small_model_manifest(path: str | Path, *, base_dir: str | Path | None = None) -> SmallModelManifest:
    manifest_path = Path(path).resolve()
    root = Path(base_dir).resolve() if base_dir is not None else manifest_path.parent
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"small-model manifest must be a mapping: {manifest_path}")

    tasks: dict[str, dict[str, SmallModelSpec]] = {}
    defaults: dict[str, str] = {}
    for task, section in raw.items():
        task_key = str(task).strip()
        if not task_key:
            continue
        if not isinstance(section, Mapping):
            raise ValueError(f"small-model task section must be a mapping: {task_key}")
        default_id = str(section.get("default") or "").strip()
        models_raw = section.get("models")
        if not default_id or not isinstance(models_raw, Mapping):
            raise ValueError(f"small-model task '{task_key}' requires default and models")

        models: dict[str, SmallModelSpec] = {}
        for model_id, model_raw in models_raw.items():
            model_key = str(model_id).strip()
            if not model_key or not isinstance(model_raw, Mapping):
                continue
            models[model_key] = _parse_spec(task=task_key, model_id=model_key, raw=model_raw, base_dir=root)
        if default_id not in models:
            raise ValueError(f"small-model default '{default_id}' not found for task '{task_key}'")
        tasks[task_key] = models
        defaults[task_key] = default_id

    return SmallModelManifest(path=manifest_path, tasks=tasks, defaults=defaults)


def load_default_small_model_manifest() -> SmallModelManifest:
    return load_small_model_manifest(_DEFAULT_MANIFEST_PATH, base_dir=_REPO_ROOT)


__all__ = [
    "SmallModelKind",
    "SmallModelManifest",
    "SmallModelSpec",
    "load_default_small_model_manifest",
    "load_small_model_manifest",
]
