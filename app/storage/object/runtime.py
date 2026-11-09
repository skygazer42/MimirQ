from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.config import parse_object_storage_region_profiles, settings
from app.storage.object.factory import (
    get_object_store,
    normalize_object_store_provider,
)
from app.storage.object.minio import MinIOService, minio_service

_OBJECT_STORAGE_SCHEMES = {"minio", "s3", "s3_compatible", "s3compat", "oss", "cos"}
SOURCE_STORAGE_BACKEND_KEY = "source_storage_backend"
SOURCE_STORAGE_PROVIDER_KEY = "source_storage_provider"
SOURCE_STORAGE_REGION_KEY = "source_storage_region"
SOURCE_STORAGE_BACKEND_OBJECT_STORAGE = "object_storage"
SOURCE_STORAGE_BACKEND_LEGACY_MINIO = "legacy_minio"


@dataclass(frozen=True)
class ObjectStorageRef:
    provider: str
    bucket: str
    object_name: str


def is_object_storage_uri(value: str | None) -> bool:
    if value is None:
        return False
    raw = value.strip()
    if not raw:
        return False
    scheme, separator, _remainder = raw.partition("://")
    return bool(separator) and scheme.strip().lower() in _OBJECT_STORAGE_SCHEMES


def parse_object_storage_uri(uri: str) -> ObjectStorageRef:
    raw = uri.strip()
    provider, separator, remainder = raw.partition("://")
    provider = provider.strip().lower()
    if provider not in _OBJECT_STORAGE_SCHEMES:
        raise ValueError("invalid_object_storage_uri_scheme")
    if provider == "s3compat":
        provider = "s3_compatible"
    if not separator:
        raise ValueError("invalid_object_storage_uri")
    bucket, slash, object_name = remainder.partition("/")
    bucket = bucket.strip()
    object_name = object_name.lstrip("/").strip() if slash else ""
    if not bucket or not object_name:
        raise ValueError("invalid_object_storage_uri")
    return ObjectStorageRef(provider=provider, bucket=bucket, object_name=object_name)


def _build_generic_object_store(provider: str, *, region: str | None = None) -> MinIOService:
    return get_object_store(provider=provider, region=region, prefer_legacy_minio=False)


def get_document_object_store(*, region: str | None = None) -> MinIOService | None:
    provider = normalize_object_store_provider(settings.OBJECT_STORAGE_PROVIDER or "minio")
    generic_store = _build_generic_object_store(provider, region=region)
    generic_backend = object_store_backend_config(generic_store)
    if bool(generic_backend.get("enabled", False)) and bool(generic_backend.get("documents_enabled", False)):
        return generic_store
    if settings.MINIO_ENABLED and settings.MINIO_DOCUMENTS_ENABLED:
        return minio_service
    return None


def document_object_storage_enabled(*, region: str | None = None) -> bool:
    return get_document_object_store(region=region) is not None


def _resolve_stored_object_region(
    ref: ObjectStorageRef,
    *,
    region: str | None,
    document_metadata: dict[str, object] | None,
) -> str | None:
    metadata = document_metadata if isinstance(document_metadata, dict) else {}
    stored_region = metadata.get(SOURCE_STORAGE_REGION_KEY)
    if stored_region is not None:
        stored_region = stored_region.strip().lower()
    if stored_region:
        return stored_region
    explicit_region = region.strip().lower() if region is not None else None
    if explicit_region:
        return explicit_region
    stored_backend = metadata.get(SOURCE_STORAGE_BACKEND_KEY)
    if stored_backend is not None:
        stored_backend = stored_backend.strip().lower()
    if stored_backend != SOURCE_STORAGE_BACKEND_OBJECT_STORAGE:
        return region

    profiles = parse_object_storage_region_profiles(settings.OBJECT_STORAGE_REGION_PROFILES)
    matching_regions: list[str] = []
    for profile_region, profile in profiles.items():
        provider = normalize_object_store_provider(
            str(profile.get("provider") or settings.OBJECT_STORAGE_PROVIDER or "minio")
        )
        bucket = str(profile.get("bucket_name") or settings.OBJECT_STORAGE_BUCKET_NAME).strip()
        if provider == ref.provider and bucket == ref.bucket:
            matching_regions.append(profile_region)
    if len(matching_regions) == 1:
        return matching_regions[0]
    if len(matching_regions) > 1:
        raise ValueError("object_region_ambiguous")
    if settings.DATA_REGION.strip():
        raise ValueError("object_region_missing")
    return region


def get_object_store_for_uri(
    uri: str, *, region: str | None = None, document_metadata: dict[str, object] | None = None
) -> MinIOService:
    ref = parse_object_storage_uri(uri)
    metadata = document_metadata if isinstance(document_metadata, dict) else {}
    resolved_region = _resolve_stored_object_region(ref, region=region, document_metadata=metadata)
    stored_provider = metadata.get(SOURCE_STORAGE_PROVIDER_KEY)
    if stored_provider is not None:
        stored_provider = stored_provider.strip().lower()
    if stored_provider and normalize_object_store_provider(stored_provider) != ref.provider:
        raise ValueError("object_provider_denied")
    if ref.provider == "minio":
        stored_backend = metadata.get(SOURCE_STORAGE_BACKEND_KEY)
        if stored_backend is not None:
            stored_backend = stored_backend.strip().lower()
        if stored_backend == SOURCE_STORAGE_BACKEND_OBJECT_STORAGE:
            return _build_generic_object_store("minio", region=resolved_region)
        return minio_service
    return get_object_store(provider=ref.provider, region=resolved_region)


def object_store_backend_config(store: MinIOService) -> dict[str, Any]:
    return store.describe_backend()


def document_object_store_metadata(store: object) -> dict[str, str]:
    backend = SOURCE_STORAGE_BACKEND_LEGACY_MINIO if store is minio_service else SOURCE_STORAGE_BACKEND_OBJECT_STORAGE
    backend_config = object_store_backend_config(store)
    provider = str(backend_config.get("provider") or "minio").strip().lower() or "minio"
    metadata = {
        SOURCE_STORAGE_BACKEND_KEY: backend,
        SOURCE_STORAGE_PROVIDER_KEY: provider,
    }
    region = backend_config.get("region")
    if region is not None:
        region = region.strip().lower()
    if backend == SOURCE_STORAGE_BACKEND_OBJECT_STORAGE and region:
        metadata[SOURCE_STORAGE_REGION_KEY] = region
    return metadata


def resolve_document_object_reference(
    raw_path: str,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    document_id: UUID,
    file_type: str,
    document_metadata: dict[str, object] | None = None,
    region: str | None = None,
) -> tuple[MinIOService, ObjectStorageRef]:
    ref = parse_object_storage_uri(raw_path)
    store = get_object_store_for_uri(raw_path, region=region, document_metadata=document_metadata)
    backend = object_store_backend_config(store)
    if not bool(backend.get("enabled", False)):
        raise RuntimeError("object_storage_disabled")
    expected_bucket = backend["bucket"].strip()
    if ref.bucket != expected_bucket:
        raise ValueError("object_bucket_denied")
    expected_object = store.build_document_object_name(
        tenant_id=str(tenant_id),
        dataset_id=str(dataset_id or tenant_id),
        document_id=str(document_id),
        extension=f".{file_type.lower()}",
    )
    if ref.object_name != expected_object:
        raise ValueError("object_key_denied")
    return store, ref


__all__ = [
    "ObjectStorageRef",
    "document_object_storage_enabled",
    "document_object_store_metadata",
    "get_document_object_store",
    "get_object_store_for_uri",
    "is_object_storage_uri",
    "object_store_backend_config",
    "parse_object_storage_uri",
    "resolve_document_object_reference",
    "SOURCE_STORAGE_BACKEND_KEY",
    "SOURCE_STORAGE_BACKEND_LEGACY_MINIO",
    "SOURCE_STORAGE_BACKEND_OBJECT_STORAGE",
    "SOURCE_STORAGE_PROVIDER_KEY",
    "SOURCE_STORAGE_REGION_KEY",
]
