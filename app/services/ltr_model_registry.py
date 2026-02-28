"""
LTR model registry service (file-based, versioned artifacts + rollback).

Design goals:
- Deterministic: model ids are content-addressed (sha256).
- Safe defaults: activation requires a validated manifest.
- Reproducible: active selection is persisted in a small active.json record.
- Fail-closed for activation/validation; fail-open for reads/listing.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Tuple

from app.core.config import settings
from app.rag.reranker.ltr import LTRFeatureSpec

_ACTIVE_SCHEMA_V1 = "mimirq.ltr_model_registry_active.v1"
_MODEL_META_SCHEMA_V1 = "mimirq.ltr_model_registry_meta.v1"
_MANIFEST_SCHEMA_V1 = "mimirq.ltr_model_manifest.v1"

# Re-entrant because rollback calls activate_model() which also needs the registry lock.
_LOCK = threading.RLock()


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _registry_root() -> Path:
    root = Path(getattr(settings, "UPLOAD_DIR", "./uploads") or "./uploads")
    return (root / ".ltr_registry").resolve(strict=False)


def _models_root() -> Path:
    return _registry_root() / "models"


def _active_path() -> Path:
    return _registry_root() / "active.json"


def _model_dir(model_id: str) -> Path:
    safe = "".join([c for c in str(model_id or "").strip().lower() if c.isalnum()])
    return _models_root() / safe


def _model_path(model_id: str) -> Path:
    return _model_dir(model_id) / "model.xgb.json"


def _manifest_path(model_id: str) -> Path:
    return _model_dir(model_id) / "manifest.json"


def _meta_path(model_id: str) -> Path:
    return _model_dir(model_id) / "meta.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _validate_manifest_obj(*, manifest: dict[str, Any], model_sha256: str) -> Tuple[int, dict[str, Any]]:
    schema = str(manifest.get("schema") or "").strip()
    if schema != _MANIFEST_SCHEMA_V1:
        raise ValueError(f"manifest schema mismatch: {schema or '<missing>'}")

    feature_schema = str(manifest.get("feature_schema") or "").strip()
    if feature_schema not in {"mimirq.ltr_features.v1", "mimirq.ltr_features.v2"}:
        raise ValueError("manifest feature_schema must be mimirq.ltr_features.v1 or mimirq.ltr_features.v2")

    version = 2 if feature_schema.endswith(".v2") else 1
    spec = LTRFeatureSpec.from_version(version)

    names = manifest.get("feature_names")
    if not isinstance(names, list):
        raise ValueError("manifest feature_names must be a list")
    names_norm = [str(x) for x in names if x is not None]
    if names_norm != list(spec.feature_names):
        raise ValueError("manifest feature_names mismatch (feature order/count must match spec)")

    sha = str(manifest.get("model_sha256") or "").strip()
    if sha and sha != model_sha256:
        raise ValueError("manifest model_sha256 mismatch")

    cleaned = {
        "schema": schema,
        "feature_schema": feature_schema,
        "feature_names": list(names_norm),
        "model_sha256": (sha or model_sha256),
    }
    return version, cleaned


@dataclass(frozen=True)
class LTRRegisteredModel:
    model_id: str
    model_sha256: str
    size_bytes: int
    created_at: str
    created_by: str | None
    feature_spec_version: int
    feature_schema: str
    feature_names: list[str]
    has_manifest: bool


def register_model(
    *,
    model_bytes: bytes,
    manifest_bytes: bytes,
    actor_id: str | None,
) -> LTRRegisteredModel:
    """
    Register an LTR model artifact into the file-based registry.

    Notes:
    - Registration is content-addressed: model_id == sha256(model_bytes)
    - A manifest is required for safety/reproducibility.
    """
    if not isinstance(model_bytes, (bytes, bytearray)) or not model_bytes:
        raise ValueError("model_bytes is required")
    if not isinstance(manifest_bytes, (bytes, bytearray)) or not manifest_bytes:
        raise ValueError("manifest_bytes is required")

    with _LOCK:
        model_sha = _sha256(bytes(model_bytes))
        model_id = model_sha

        try:
            manifest_obj = json.loads(manifest_bytes.decode("utf-8"))
        except Exception as exc:
            raise ValueError("invalid manifest JSON") from exc
        if not isinstance(manifest_obj, dict):
            raise ValueError("manifest must be a JSON object")

        spec_version, manifest_clean = _validate_manifest_obj(manifest=manifest_obj, model_sha256=model_sha)

        out_dir = _model_dir(model_id)
        out_dir.mkdir(parents=True, exist_ok=True)

        mp = _model_path(model_id)
        mp.write_bytes(bytes(model_bytes))

        man_p = _manifest_path(model_id)
        _write_json(man_p, manifest_clean)

        meta = {
            "schema": _MODEL_META_SCHEMA_V1,
            "model_id": model_id,
            "model_sha256": model_sha,
            "size_bytes": int(len(model_bytes)),
            "created_at": _now_utc_iso(),
            "created_by": (str(actor_id) if actor_id else None),
            "feature_spec_version": int(spec_version),
            "feature_schema": str(manifest_clean.get("feature_schema") or ""),
            "feature_names": list(manifest_clean.get("feature_names") or []),
            "paths": {
                "model": str(mp),
                "manifest": str(man_p),
            },
        }
        _write_json(_meta_path(model_id), meta)

        return LTRRegisteredModel(
            model_id=model_id,
            model_sha256=model_sha,
            size_bytes=int(len(model_bytes)),
            created_at=str(meta.get("created_at") or ""),
            created_by=(str(actor_id) if actor_id else None),
            feature_spec_version=int(spec_version),
            feature_schema=str(manifest_clean.get("feature_schema") or ""),
            feature_names=list(manifest_clean.get("feature_names") or []),
            has_manifest=True,
        )


def list_models() -> List[LTRRegisteredModel]:
    """List registered LTR models (best-effort)."""
    root = _models_root()
    if not root.exists():
        return []
    out: list[LTRRegisteredModel] = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        meta = _read_json(p / "meta.json") or {}
        if str(meta.get("schema") or "") != _MODEL_META_SCHEMA_V1:
            continue
        try:
            out.append(
                LTRRegisteredModel(
                    model_id=str(meta.get("model_id") or p.name),
                    model_sha256=str(meta.get("model_sha256") or ""),
                    size_bytes=int(meta.get("size_bytes") or 0),
                    created_at=str(meta.get("created_at") or ""),
                    created_by=(str(meta.get("created_by")) if meta.get("created_by") is not None else None),
                    feature_spec_version=int(meta.get("feature_spec_version") or 1),
                    feature_schema=str(meta.get("feature_schema") or ""),
                    feature_names=list(meta.get("feature_names") or []),
                    has_manifest=bool(_manifest_path(str(meta.get("model_id") or p.name)).exists()),
                )
            )
        except Exception:
            continue
    out.sort(key=lambda m: (m.created_at or "", m.model_id))
    return out


def _load_active() -> dict[str, Any]:
    return _read_json(_active_path()) or {}


def _save_active(obj: dict[str, Any]) -> None:
    _write_json(_active_path(), obj)


def activate_model(*, model_id: str, actor_id: str | None) -> dict[str, Any]:
    """
    Activate a registered model (writes active.json, updates runtime settings).

    Activation requires a validated manifest so feature schema mismatches fail-closed.
    """
    mid = str(model_id or "").strip().lower()
    if not mid:
        raise ValueError("model_id is required")

    with _LOCK:
        mp = _model_path(mid)
        man_p = _manifest_path(mid)
        meta_p = _meta_path(mid)
        if not mp.exists() or not meta_p.exists():
            raise FileNotFoundError(f"model not found: {mid}")
        if not man_p.exists():
            raise ValueError("manifest is required for activation")

        meta = _read_json(meta_p) or {}
        if str(meta.get("schema") or "") != _MODEL_META_SCHEMA_V1:
            raise ValueError("invalid model meta")

        prev = _load_active()
        prev_id = str(prev.get("current_model_id") or "").strip() or None

        spec_version = int(meta.get("feature_spec_version") or 1)
        settings.LTR_MODEL_PATH = str(mp)
        settings.LTR_MODEL_MANIFEST_PATH = str(man_p)
        settings.LTR_FEATURE_SPEC_VERSION = int(spec_version)

        active = {
            "schema": _ACTIVE_SCHEMA_V1,
            "current_model_id": mid,
            "previous_model_id": prev_id,
            "activated_at": _now_utc_iso(),
            "activated_by": (str(actor_id) if actor_id else None),
        }
        _save_active(active)

        return active


def rollback_active_model(*, actor_id: str | None) -> dict[str, Any]:
    """Rollback to the previous activated model (best-effort, fail-closed)."""
    with _LOCK:
        active = _load_active()
        if str(active.get("schema") or "") != _ACTIVE_SCHEMA_V1:
            raise ValueError("no active model")
        cur = str(active.get("current_model_id") or "").strip()
        prev = str(active.get("previous_model_id") or "").strip()
        if not cur or not prev:
            raise ValueError("no previous model to rollback to")

        # Swap: previous becomes current; keep one-step history only.
        next_active = activate_model(model_id=prev, actor_id=actor_id)
        # Preserve "previous" as the model we rolled back from.
        next_active["previous_model_id"] = cur
        _save_active(next_active)
        return next_active


def resolve_active_model_paths() -> Tuple[str | None, str | None, int | None, str | None]:
    """
    Resolve (model_path, manifest_path, feature_spec_version, model_id) from active.json.

    This enables persistence across restarts without requiring .env mutation.
    """
    active = _load_active()
    if str(active.get("schema") or "") != _ACTIVE_SCHEMA_V1:
        return None, None, None, None
    mid = str(active.get("current_model_id") or "").strip().lower()
    if not mid:
        return None, None, None, None

    mp = _model_path(mid)
    man_p = _manifest_path(mid)
    meta = _read_json(_meta_path(mid)) or {}
    if not mp.exists() or not man_p.exists():
        return None, None, None, None
    try:
        spec_version = int(meta.get("feature_spec_version") or 1)
    except Exception:
        spec_version = 1
    return str(mp), str(man_p), int(spec_version), mid


__all__ = [
    "LTRRegisteredModel",
    "activate_model",
    "list_models",
    "register_model",
    "resolve_active_model_paths",
    "rollback_active_model",
]
