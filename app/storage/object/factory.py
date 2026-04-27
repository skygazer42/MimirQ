from __future__ import annotations

import json
from collections.abc import Mapping

from app.core.config import settings
from app.storage.object.minio import minio_service
from app.storage.object.s3_compatible import S3CompatibleObjectStore

_PROVIDER_ALIASES = {
    "": "minio",
    "minio": "minio",
    "s3": "s3",
    "aws_s3": "s3",
    "s3_compatible": "s3_compatible",
    "oss": "oss",
    "aliyun_oss": "oss",
    "cos": "cos",
    "tencent_cos": "cos",
}
_S3_COMPATIBLE_PROVIDERS = {"minio", "s3", "s3_compatible", "oss", "cos"}


def _normalize_region(region: str | None = None) -> str:
    return str(region or getattr(settings, "DATA_REGION", "") or "").strip().lower()


def _load_region_profiles() -> dict[str, dict[str, object]]:
    raw = getattr(settings, "OBJECT_STORAGE_REGION_PROFILES", "") or ""
    if isinstance(raw, Mapping):
        source = dict(raw)
    else:
        text = str(raw).strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        source = dict(parsed) if isinstance(parsed, dict) else {}

    out: dict[str, dict[str, object]] = {}
    for key, value in source.items():
        region = str(key or "").strip().lower()
        if not region or not isinstance(value, Mapping):
            continue
        out[region] = dict(value)
    return out


def normalize_object_store_provider(provider: str | None = None) -> str:
    requested = str(provider or getattr(settings, "OBJECT_STORAGE_PROVIDER", "") or "minio").strip().lower()
    normalized = _PROVIDER_ALIASES.get(requested, requested)
    if normalized not in _S3_COMPATIBLE_PROVIDERS:
        raise ValueError(f"unsupported object storage provider: {requested or normalized}")
    return normalized


def _resolve_object_store_config(provider: str | None = None, *, region: str | None = None) -> dict[str, object]:
    region_key = _normalize_region(region)
    region_profile = _load_region_profiles().get(region_key, {}) if region_key else {}

    return {
        "region": region_key or None,
        "provider": normalize_object_store_provider(
            str(region_profile.get("provider") or provider or getattr(settings, "OBJECT_STORAGE_PROVIDER", "") or "minio")
        ),
        "enabled": bool(region_profile.get("enabled", getattr(settings, "OBJECT_STORAGE_ENABLED", False))),
        "endpoint": str(region_profile.get("endpoint") or getattr(settings, "OBJECT_STORAGE_ENDPOINT", "") or "").strip(),
        "access_key": str(region_profile.get("access_key") or getattr(settings, "OBJECT_STORAGE_ACCESS_KEY", "") or "").strip(),
        "secret_key": str(region_profile.get("secret_key") or getattr(settings, "OBJECT_STORAGE_SECRET_KEY", "") or "").strip(),
        "bucket_name": str(region_profile.get("bucket_name") or getattr(settings, "OBJECT_STORAGE_BUCKET_NAME", "") or "").strip(),
        "use_ssl": bool(region_profile.get("use_ssl", getattr(settings, "OBJECT_STORAGE_USE_SSL", True))),
        "metrics_log_path": str(
            region_profile.get("metrics_log_path")
            or getattr(settings, "OBJECT_STORAGE_METRICS_LOG_PATH", "./logs/object_store_metrics.jsonl")
            or "./logs/object_store_metrics.jsonl"
        ),
        "documents_enabled": bool(
            region_profile.get("documents_enabled", getattr(settings, "OBJECT_STORAGE_DOCUMENTS_ENABLED", False))
        ),
    }


def _build_s3_compatible_store(provider: str, *, config: Mapping[str, object] | None = None) -> S3CompatibleObjectStore:
    cfg = dict(config or {})
    return S3CompatibleObjectStore(
        provider_name=provider,
        enabled=bool(cfg.get("enabled", False)),
        endpoint=str(cfg.get("endpoint") or "").strip(),
        access_key=str(cfg.get("access_key") or "").strip(),
        secret_key=str(cfg.get("secret_key") or "").strip(),
        bucket_name=str(cfg.get("bucket_name") or "").strip(),
        use_ssl=bool(cfg.get("use_ssl", True)),
        metrics_log_path=str(cfg.get("metrics_log_path") or "./logs/object_store_metrics.jsonl"),
        documents_enabled=bool(cfg.get("documents_enabled", False)),
    )


def get_object_store(provider: str | None = None, *, region: str | None = None):
    cfg = _resolve_object_store_config(provider, region=region)
    normalized = str(cfg.get("provider") or "minio")
    if normalized == "minio" and not cfg.get("region"):
        return minio_service
    return _build_s3_compatible_store(normalized, config=cfg)


__all__ = ["get_object_store", "normalize_object_store_provider"]
