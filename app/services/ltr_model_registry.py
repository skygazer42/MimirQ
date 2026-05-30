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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.rag.core.retrieval_config_fingerprint import build_retrieval_config_fingerprint
from app.rag.reranker.ltr import LTRFeatureSpec, build_ltr_feature_spec_fingerprint

_ACTIVE_SCHEMA_V1 = "mimirq.ltr_model_registry_active.v1"
_MODEL_META_SCHEMA_V1 = "mimirq.ltr_model_registry_meta.v1"
_MANIFEST_SCHEMA_V1 = "mimirq.ltr_model_manifest.v1"

# Re-entrant because rollback calls activate_model() which also needs the registry lock.
_LOCK = threading.RLock()
_SHA256_HEX_LEN = 64


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    safe_path = _safe_registry_path(path)
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = safe_path.with_name(f".{safe_path.name}.{os.getpid()}.tmp")
    # Path is constrained to the LTR registry root before the atomic write.
    tmp.write_text(text, encoding="utf-8")  # NOSONAR
    tmp.replace(safe_path)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    safe_path = _safe_registry_path(path)
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = safe_path.with_name(f".{safe_path.name}.{os.getpid()}.tmp")
    # Path is constrained to the LTR registry root before the atomic write.
    tmp.write_bytes(data)  # NOSONAR
    tmp.replace(safe_path)


def _registry_root() -> Path:
    root = Path(getattr(settings, "UPLOAD_DIR", "./uploads") or "./uploads")
    return (root / ".ltr_registry").resolve(strict=False)


def _safe_registry_path(path: Path) -> Path:
    root = _registry_root()
    resolved = Path(path).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("registry path outside LTR registry") from exc
    return resolved


def _models_root() -> Path:
    return _registry_root() / "models"


def _active_path() -> Path:
    return _registry_root() / "active.json"


def _model_dir(model_id: str) -> Path:
    safe = str(model_id or "").strip().lower()
    if len(safe) != _SHA256_HEX_LEN or any(c not in "0123456789abcdef" for c in safe):
        raise ValueError("model_id must be a sha256 hex digest")
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


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _extract_metric_value(window: dict[str, Any], metric_key: str) -> float | None:
    key = str(metric_key or "").strip()
    if not key:
        return None
    if key in window:
        return _as_float(window.get(key))

    cur: Any = window
    for part in [p for p in key.split(".") if p]:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return _as_float(cur)


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _validate_manifest_obj(*, manifest: dict[str, Any], model_sha256: str) -> tuple[int, dict[str, Any]]:
    schema = str(manifest.get("schema") or "").strip()
    if schema != _MANIFEST_SCHEMA_V1:
        raise ValueError(f"manifest schema mismatch: {schema or '<missing>'}")

    feature_schema = str(manifest.get("feature_schema") or "").strip()
    if feature_schema not in {"mimirq.ltr_features.v1", "mimirq.ltr_features.v2", "mimirq.ltr_features.v3"}:
        raise ValueError("manifest feature_schema must be mimirq.ltr_features.v1, .v2, or .v3")

    if feature_schema.endswith(".v3"):
        version = 3
    elif feature_schema.endswith(".v2"):
        version = 2
    else:
        version = 1
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

    def _safe_str(value: Any, *, max_len: int = 200) -> str | None:
        s = str(value or "").strip()
        if not s:
            return None
        lim = max(0, int(max_len or 0))
        if lim <= 0:
            return s
        return s[:lim]

    def _safe_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except Exception:
            return None

    def _safe_list_str(value: Any, *, max_items: int = 20, max_len: int = 80) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for raw in value:
            s = _safe_str(raw, max_len=max_len)
            if not s:
                continue
            out.append(s)
            if len(out) >= max(0, int(max_items or 0)):
                break
        return out

    # Base validated fields (required for safe activation).
    cleaned: dict[str, Any] = {
        "schema": schema,
        "feature_schema": feature_schema,
        "feature_names": list(names_norm),
        "model_sha256": (sha or model_sha256),
    }

    # Optional, PII-safe training metadata (best-effort).
    created_at = _safe_str(manifest.get("created_at"), max_len=40)
    if created_at:
        cleaned["created_at"] = created_at

    model_file = _safe_str(manifest.get("model_file"), max_len=200)
    if model_file:
        cleaned["model_file"] = model_file

    objective = _safe_str(manifest.get("objective"), max_len=80)
    if objective:
        cleaned["objective"] = objective

    num_boost_round = _safe_int(manifest.get("num_boost_round"))
    if num_boost_round is not None:
        cleaned["num_boost_round"] = max(0, int(num_boost_round))

    seed = _safe_int(manifest.get("seed"))
    if seed is not None:
        cleaned["seed"] = int(seed)

    # Explicit feature spec fingerprint (stable + versioned).
    cleaned["feature_spec_version"] = int(version)
    cleaned["feature_spec"] = build_ltr_feature_spec_fingerprint(spec=spec, version=version)

    training_raw = manifest.get("training")
    if isinstance(training_raw, dict):
        allow = {
            "cases_total",
            "cases_used",
            "cases_missed",
            "rows_total",
            "rows_pos",
            "rows_neg",
            "rows_hard_neg",
            "group_count",
            "data_hash",
        }
        training_out: dict[str, Any] = {}
        for k in allow:
            if k not in training_raw:
                continue
            if k == "data_hash":
                v = _safe_str(training_raw.get(k), max_len=64)
                if v:
                    training_out[k] = v
                continue
            iv = _safe_int(training_raw.get(k))
            if iv is None:
                continue
            training_out[k] = max(0, int(iv))
        if training_out:
            cleaned["training"] = training_out

    # Optional run lineage (PII-safe by construction: hashes + low-cardinality config).
    lineage_raw = manifest.get("lineage")
    if isinstance(lineage_raw, dict) and _safe_str(lineage_raw.get("schema"), max_len=80) == "mimirq.ltr_run_lineage.v1":
        lineage_out: dict[str, Any] = {"schema": "mimirq.ltr_run_lineage.v1"}
        kind = _safe_str(lineage_raw.get("kind"), max_len=16)
        if kind:
            lineage_out["kind"] = kind

        dataset_id = _safe_str(lineage_raw.get("dataset_id"), max_len=64)
        if dataset_id:
            lineage_out["dataset_id"] = dataset_id

        cases_sha256 = _safe_str(lineage_raw.get("cases_sha256"), max_len=64)
        if cases_sha256:
            lineage_out["cases_sha256"] = cases_sha256

        cases_schema = _safe_str(lineage_raw.get("cases_schema"), max_len=80)
        if cases_schema:
            lineage_out["cases_schema"] = cases_schema

        pipeline_hashes = _safe_list_str(lineage_raw.get("pipeline_hashes"), max_items=20, max_len=64)
        if pipeline_hashes:
            lineage_out["pipeline_hashes"] = pipeline_hashes

        hard_neg_sha = _safe_str(lineage_raw.get("hard_negatives_sha256"), max_len=64)
        if hard_neg_sha:
            lineage_out["hard_negatives_sha256"] = hard_neg_sha

        retrieval_cfg_raw = lineage_raw.get("retrieval_config")
        retrieval_cfg_out: dict[str, Any] | None = None
        if isinstance(retrieval_cfg_raw, dict):
            # Accept either a full fingerprint or a bare config; normalize via the canonical helper.
            cfg_obj = retrieval_cfg_raw.get("config") if isinstance(retrieval_cfg_raw.get("config"), dict) else retrieval_cfg_raw
            if isinstance(cfg_obj, dict):
                retrieval_cfg_out = build_retrieval_config_fingerprint(config=cfg_obj)
        if retrieval_cfg_out:
            lineage_out["retrieval_config"] = retrieval_cfg_out
            if isinstance(retrieval_cfg_out.get("hash"), str) and retrieval_cfg_out.get("hash"):
                lineage_out["retrieval_config_hash"] = retrieval_cfg_out.get("hash")

        if len(lineage_out.keys()) > 1:
            cleaned["lineage"] = lineage_out

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
    manifest_bytes: bytes | None = None,
    _manifest_bytes: bytes | None = None,
    actor_id: str | None = None,
    _actor_id: str | None = None,
) -> LTRRegisteredModel:
    """
    Register an LTR model artifact into the file-based registry.

    Notes:
    - Registration is content-addressed: model_id == sha256(model_bytes)
    - A manifest is required for safety/reproducibility.
    """
    manifest_bytes0 = manifest_bytes if manifest_bytes is not None else _manifest_bytes
    actor_id0 = actor_id if actor_id is not None else _actor_id

    if not isinstance(model_bytes, (bytes, bytearray)) or not model_bytes:
        raise ValueError("model_bytes is required")
    if not isinstance(manifest_bytes0, (bytes, bytearray)) or not manifest_bytes0:
        raise ValueError("manifest_bytes is required")

    with _LOCK:
        model_sha = _sha256(bytes(model_bytes))
        model_id = model_sha

        try:
            manifest_obj = json.loads(bytes(manifest_bytes0).decode("utf-8"))
        except Exception as exc:
            raise ValueError("invalid manifest JSON") from exc
        if not isinstance(manifest_obj, dict):
            raise ValueError("manifest must be a JSON object")

        spec_version, manifest_clean = _validate_manifest_obj(manifest=manifest_obj, model_sha256=model_sha)

        out_dir = _model_dir(model_id)
        out_dir.mkdir(parents=True, exist_ok=True)

        mp = _model_path(model_id)
        _atomic_write_bytes(mp, bytes(model_bytes))

        man_p = _manifest_path(model_id)
        _write_json(man_p, manifest_clean)

        meta = {
            "schema": _MODEL_META_SCHEMA_V1,
            "model_id": model_id,
            "model_sha256": model_sha,
            "size_bytes": int(len(model_bytes)),
            "created_at": _now_utc_iso(),
            "created_by": (str(actor_id0) if actor_id0 else None),
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
            created_by=(str(actor_id0) if actor_id0 else None),
            feature_spec_version=int(spec_version),
            feature_schema=str(manifest_clean.get("feature_schema") or ""),
            feature_names=list(manifest_clean.get("feature_names") or []),
            has_manifest=True,
        )


def list_models() -> list[LTRRegisteredModel]:
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


def apply_canary_activation(
    *,
    model_id: str,
    actor_id: str | None,
    canary_ratio: float,
    min_ratio: float = 0.01,
    max_ratio: float = 0.5,
) -> dict[str, Any]:
    """
    Activate a model with bounded canary metadata.

    Notes:
    - Activation semantics remain the same as `activate_model`.
    - This helper only adds deterministic canary metadata into active.json.
    - Runtime traffic splitting is executed by callers/routers using this metadata.
    """
    ratio = float(canary_ratio)
    low = max(0.0, float(min_ratio))
    high = min(1.0, max(float(max_ratio), low))
    if ratio < low or ratio > high:
        raise ValueError(f"canary_ratio_out_of_bounds:{ratio} not in [{low}, {high}]")

    with _LOCK:
        active = activate_model(model_id=model_id, actor_id=actor_id)
        canary = {
            "enabled": True,
            "ratio": round(float(ratio), 6),
            "min_ratio": round(float(low), 6),
            "max_ratio": round(float(high), 6),
            "applied_at": _now_utc_iso(),
            "applied_by": (str(actor_id) if actor_id else None),
        }
        active["canary"] = canary
        _save_active(active)
        return active


def resolve_active_model_paths() -> tuple[str | None, str | None, int | None, str | None]:
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


def evaluate_online_rollback_trigger(
    *,
    windows: list[dict[str, Any]] | None,
    metric_key: str = "delta.mrr",
    max_allowed_delta: float = -0.02,
    min_consecutive_windows: int = 3,
) -> dict[str, Any]:
    """
    Evaluate whether online degradation windows should trigger rollback.

    Rules:
    - Use the trailing consecutive degraded windows (latest-first from list tail).
    - A window is degraded when metric_value <= max_allowed_delta.
    - Trigger when trailing degraded windows >= min_consecutive_windows.
    """
    rows = [w for w in (windows or []) if isinstance(w, dict)]
    required = max(1, int(min_consecutive_windows or 1))
    threshold = float(max_allowed_delta)
    key = str(metric_key or "").strip() or "delta.mrr"
    reasons: list[str] = []

    degraded_total = 0
    trailing_consecutive = 0
    for row in rows:
        value = _extract_metric_value(row, key)
        if value is not None and value <= threshold:
            degraded_total += 1

    for row in reversed(rows):
        value = _extract_metric_value(row, key)
        if value is None:
            break
        if value <= threshold:
            trailing_consecutive += 1
            continue
        break

    if len(rows) < required:
        reasons.append(f"insufficient windows: have={len(rows)} need={required}")
    if trailing_consecutive < required:
        reasons.append(
            "consecutive degradation below threshold not met: "
            f"have={trailing_consecutive} need={required}"
        )

    triggered = len(rows) >= required and trailing_consecutive >= required
    return {
        "schema": "mimirq.ltr_online_rollback_trigger.v1",
        "metric_key": key,
        "max_allowed_delta": round(float(threshold), 4),
        "min_consecutive_windows": int(required),
        "windows_evaluated": int(len(rows)),
        "degraded_windows_total": int(degraded_total),
        "degraded_consecutive": int(trailing_consecutive),
        "triggered": bool(triggered),
        "reasons": reasons,
    }


__all__ = [
    "LTRRegisteredModel",
    "activate_model",
    "apply_canary_activation",
    "evaluate_online_rollback_trigger",
    "list_models",
    "register_model",
    "resolve_active_model_paths",
    "rollback_active_model",
]
