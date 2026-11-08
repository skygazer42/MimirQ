import threading
from collections.abc import Mapping
from typing import TypedDict

from app.core.config import (
    normalize_object_storage_provider_name,
    parse_object_storage_region_profiles,
    settings,
)
from app.storage.object.minio import MinIOService, minio_service
from app.storage.object.s3_compatible import S3CompatibleObjectStore

_DEFAULT_OBJECT_STORE_METRICS_LOG_PATH = "./logs/object_store_metrics.jsonl"
_OBJECT_STORE_CACHE: dict[tuple[object, ...], S3CompatibleObjectStore] = {}
_OBJECT_STORE_CACHE_LOCK = threading.RLock()


class _ObjectStoreConfig(TypedDict):
    region: str | None
    provider: str
    enabled: bool
    endpoint: str
    access_key: str
    secret_key: str
    bucket_name: str
    use_ssl: bool
    metrics_log_path: str
    documents_enabled: bool


def _normalize_region(region: str | None = None) -> str:
    return str(region or settings.DATA_REGION or "").strip().lower()


def _load_region_profiles() -> dict[str, dict[str, object]]:
    return parse_object_storage_region_profiles(settings.OBJECT_STORAGE_REGION_PROFILES)


def normalize_object_store_provider(provider: str | None = None) -> str:
    return normalize_object_storage_provider_name(provider or settings.OBJECT_STORAGE_PROVIDER or "minio")


def _resolve_object_store_config(provider: str | None = None, *, region: str | None = None) -> _ObjectStoreConfig:
    region_key = _normalize_region(region)
    region_profile = _load_region_profiles().get(region_key, {}) if region_key else {}

    return {
        "region": region_key or None,
        "provider": normalize_object_store_provider(
            str(region_profile.get("provider") or provider or settings.OBJECT_STORAGE_PROVIDER or "minio")
        ),
        "enabled": bool(region_profile.get("enabled", settings.OBJECT_STORAGE_ENABLED)),
        "endpoint": str(region_profile.get("endpoint") or settings.OBJECT_STORAGE_ENDPOINT).strip(),
        "access_key": str(region_profile.get("access_key") or settings.OBJECT_STORAGE_ACCESS_KEY).strip(),
        "secret_key": str(region_profile.get("secret_key") or settings.OBJECT_STORAGE_SECRET_KEY).strip(),
        "bucket_name": str(region_profile.get("bucket_name") or settings.OBJECT_STORAGE_BUCKET_NAME).strip(),
        "use_ssl": bool(region_profile.get("use_ssl", settings.OBJECT_STORAGE_USE_SSL)),
        "metrics_log_path": str(
            region_profile.get("metrics_log_path")
            or settings.OBJECT_STORAGE_METRICS_LOG_PATH
            or _DEFAULT_OBJECT_STORE_METRICS_LOG_PATH
        ),
        "documents_enabled": bool(region_profile.get("documents_enabled", settings.OBJECT_STORAGE_DOCUMENTS_ENABLED)),
    }


def _build_s3_compatible_store(provider: str, *, config: _ObjectStoreConfig) -> S3CompatibleObjectStore:
    return S3CompatibleObjectStore(
        provider_name=provider,
        enabled=config["enabled"],
        endpoint=config["endpoint"],
        access_key=config["access_key"],
        secret_key=config["secret_key"],
        bucket_name=config["bucket_name"],
        use_ssl=config["use_ssl"],
        metrics_log_path=config["metrics_log_path"],
        documents_enabled=config["documents_enabled"],
        region=config["region"],
    )


def _object_store_cache_key(config: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(
        config.get(key)
        for key in (
            "provider",
            "region",
            "enabled",
            "endpoint",
            "access_key",
            "secret_key",
            "bucket_name",
            "use_ssl",
            "metrics_log_path",
            "documents_enabled",
        )
    )


def reset_object_store_cache() -> None:
    with _OBJECT_STORE_CACHE_LOCK:
        _OBJECT_STORE_CACHE.clear()


def get_object_store(
    provider: str | None = None,
    *,
    region: str | None = None,
    prefer_legacy_minio: bool = True,
) -> MinIOService:
    cfg = _resolve_object_store_config(provider, region=region)
    normalized = cfg["provider"]
    if prefer_legacy_minio and normalized == "minio" and not cfg["region"]:
        return minio_service
    cache_key = _object_store_cache_key(cfg)
    with _OBJECT_STORE_CACHE_LOCK:
        cached = _OBJECT_STORE_CACHE.get(cache_key)
        if cached is not None:
            return cached
        store = _build_s3_compatible_store(normalized, config=cfg)
        _OBJECT_STORE_CACHE[cache_key] = store
        return store


__all__ = ["get_object_store", "normalize_object_store_provider", "reset_object_store_cache"]
