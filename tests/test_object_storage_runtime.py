from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.storage.object import runtime
from app.storage.object.factory import reset_object_store_cache
from app.storage.object.s3_compatible import S3CompatibleObjectStore


def test_parse_object_storage_uri_supports_s3_compatible_scheme() -> None:
    ref = runtime.parse_object_storage_uri("s3_compatible://bucket/path/to/object.txt")

    assert ref.provider == "s3_compatible"
    assert ref.bucket == "bucket"
    assert ref.object_name == "path/to/object.txt"


def test_parse_object_storage_uri_supports_canonical_s3compat_scheme() -> None:
    ref = runtime.parse_object_storage_uri("s3compat://bucket/path/to/object.txt")

    assert ref.provider == "s3_compatible"
    assert ref.bucket == "bucket"
    assert ref.object_name == "path/to/object.txt"


def test_s3_compatible_store_emits_canonical_s3compat_uri() -> None:
    store = S3CompatibleObjectStore(
        provider_name="s3_compatible",
        enabled=True,
        endpoint="s3.example.com",
        access_key="key",
        secret_key="secret",
        bucket_name="bucket",
        use_ssl=True,
        metrics_log_path="./logs/object_store_metrics.jsonl",
        documents_enabled=True,
    )

    assert store.build_object_uri("bucket", "path/to/object.txt") == "s3compat://bucket/path/to/object.txt"


def test_s3_compatible_health_check_uses_its_own_enablement(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _Client:
        def bucket_exists(self, bucket: str) -> bool:
            calls.append(bucket)
            return True

    store = S3CompatibleObjectStore(
        provider_name="s3",
        enabled=True,
        endpoint="s3.example.test:443",
        access_key="access",
        secret_key="secret",
        bucket_name="documents",
        use_ssl=True,
        metrics_log_path="",
        documents_enabled=True,
    )
    monkeypatch.setattr(runtime.settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(store, "_get_client", lambda: _Client(), raising=True)

    result = store.health_check()

    assert calls == ["documents"]
    assert result["enabled"] is True
    assert result["status"] == "connected"
    assert result["provider"] == "s3"


def test_s3_compatible_health_check_rejects_missing_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Client:
        def bucket_exists(self, _bucket: str) -> bool:
            return False

    store = S3CompatibleObjectStore(
        provider_name="s3",
        enabled=True,
        endpoint="s3.example.test:443",
        access_key="access",
        secret_key="secret",
        bucket_name="documents",
        use_ssl=True,
        metrics_log_path="",
        documents_enabled=True,
    )
    monkeypatch.setattr(store, "_get_client", lambda: _Client(), raising=True)

    result = store.health_check()

    assert result["enabled"] is True
    assert result["status"] == "disconnected"
    assert result["error"] == "configured object-storage bucket is unavailable"


def test_get_document_object_store_uses_generic_minio_profile_when_enabled(monkeypatch) -> None:  # noqa: ANN001
    sentinel = object()

    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_ENABLED", True, raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_DOCUMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_PROVIDER", "minio", raising=False)
    monkeypatch.setattr(runtime.settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(runtime, "_build_generic_object_store", lambda provider, *, region=None: sentinel, raising=True)

    assert runtime.get_document_object_store() is sentinel


def test_get_document_object_store_reuses_client_for_stable_config(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_object_store_cache()
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_ENABLED", True, raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_DOCUMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_PROVIDER", "s3", raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_ENDPOINT", "s3.example.test:443", raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_ACCESS_KEY", "access", raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_SECRET_KEY", "secret", raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_BUCKET_NAME", "documents", raising=False)

    first = runtime.get_document_object_store()
    second = runtime.get_document_object_store()

    assert first is second
    reset_object_store_cache()


def test_get_document_object_store_refreshes_client_when_config_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_object_store_cache()
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_ENABLED", True, raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_DOCUMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_PROVIDER", "s3", raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_ENDPOINT", "s3-a.example.test:443", raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_BUCKET_NAME", "documents", raising=False)

    first = runtime.get_document_object_store()
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_ENDPOINT", "s3-b.example.test:443", raising=False)
    second = runtime.get_document_object_store()

    assert first is not second
    reset_object_store_cache()


def test_get_document_object_store_uses_enabled_region_profile_when_global_store_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_object_store_cache()
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_ENABLED", False, raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_DOCUMENTS_ENABLED", False, raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_PROVIDER", "minio", raising=False)
    monkeypatch.setattr(runtime.settings, "DATA_REGION", "cn-shanghai", raising=False)
    monkeypatch.setattr(
        runtime.settings,
        "OBJECT_STORAGE_REGION_PROFILES",
        (
            '{"cn-shanghai":{"provider":"oss","enabled":true,'
            '"endpoint":"oss.example.test:443","access_key":"access",'
            '"secret_key":"secret","bucket_name":"documents","documents_enabled":true}}'
        ),
        raising=False,
    )
    monkeypatch.setattr(runtime.settings, "MINIO_ENABLED", False, raising=False)

    store = runtime.get_document_object_store()

    assert store is not None
    assert store.describe_backend()["provider"] == "oss"
    assert store.describe_backend()["bucket"] == "documents"
    reset_object_store_cache()


def test_document_object_metadata_binds_reads_to_upload_region(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_object_store_cache()
    profiles = (
        '{"cn-shanghai":{"provider":"oss","enabled":true,'
        '"endpoint":"oss-sh.example.test:443","access_key":"access",'
        '"secret_key":"secret","bucket_name":"documents-sh","documents_enabled":true},'
        '"us-east":{"provider":"oss","enabled":true,'
        '"endpoint":"oss-us.example.test:443","access_key":"access",'
        '"secret_key":"secret","bucket_name":"documents-us","documents_enabled":true}}'
    )
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_ENABLED", False, raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_DOCUMENTS_ENABLED", False, raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_PROVIDER", "minio", raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_REGION_PROFILES", profiles, raising=False)
    monkeypatch.setattr(runtime.settings, "DATA_REGION", "cn-shanghai", raising=False)
    monkeypatch.setattr(runtime.settings, "MINIO_ENABLED", False, raising=False)

    uploaded_store = runtime.get_document_object_store()
    assert uploaded_store is not None
    metadata = runtime.document_object_store_metadata(uploaded_store)
    uri = uploaded_store.build_object_uri("documents-sh", "documents/tenant/dataset/document.pdf")

    monkeypatch.setattr(runtime.settings, "DATA_REGION", "us-east", raising=False)
    resolved_store = runtime.get_object_store_for_uri(uri, document_metadata=metadata)

    assert metadata[runtime.SOURCE_STORAGE_REGION_KEY] == "cn-shanghai"
    assert resolved_store.describe_backend()["endpoint"] == "oss-sh.example.test:443"
    reset_object_store_cache()


def test_legacy_regionless_metadata_fails_closed_when_bucket_mapping_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_PROVIDER", "s3", raising=False)
    monkeypatch.setattr(
        runtime.settings,
        "OBJECT_STORAGE_REGION_PROFILES",
        (
            '{"region-a":{"provider":"s3","bucket_name":"shared"},'
            '"region-b":{"provider":"s3","bucket_name":"shared"}}'
        ),
        raising=False,
    )

    with pytest.raises(ValueError, match="object_region_ambiguous"):
        runtime.get_object_store_for_uri(
            "s3://shared/documents/tenant/dataset/document.pdf",
            document_metadata={
                runtime.SOURCE_STORAGE_BACKEND_KEY: runtime.SOURCE_STORAGE_BACKEND_OBJECT_STORAGE,
                runtime.SOURCE_STORAGE_PROVIDER_KEY: "s3",
            },
        )


def test_legacy_regionless_metadata_fails_closed_when_region_profile_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime.settings, "DATA_REGION", "us-east", raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_REGION_PROFILES", "", raising=False)

    with pytest.raises(ValueError, match="object_region_missing"):
        runtime.get_object_store_for_uri(
            "s3://shared/documents/tenant/dataset/document.pdf",
            document_metadata={
                runtime.SOURCE_STORAGE_BACKEND_KEY: runtime.SOURCE_STORAGE_BACKEND_OBJECT_STORAGE,
                runtime.SOURCE_STORAGE_PROVIDER_KEY: "s3",
            },
        )


def test_runtime_settings_refresh_object_store_and_readiness_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import health as health_api
    from app.api.v1 import settings as settings_api

    reset_object_store_cache()
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_ENABLED", True, raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_DOCUMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_PROVIDER", "s3", raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_ENDPOINT", "s3-a.example.test:443", raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_ACCESS_KEY", "access", raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_SECRET_KEY", "secret-a", raising=False)
    monkeypatch.setattr(runtime.settings, "OBJECT_STORAGE_BUCKET_NAME", "documents", raising=False)
    first = runtime.get_document_object_store()
    health_api._ready_cache.update({"ts": 1.0, "payload": {"ok": True}, "status": 200, "key": ("old",)})

    settings_api._apply_runtime_settings(
        {
            "OBJECT_STORAGE_ENDPOINT": "s3-b.example.test:443",
            "OBJECT_STORAGE_SECRET_KEY": "secret-b",
        },
        ["OBJECT_STORAGE_ENDPOINT", "OBJECT_STORAGE_SECRET_KEY"],
    )
    second = runtime.get_document_object_store()

    assert runtime.settings.OBJECT_STORAGE_ENDPOINT == "s3-b.example.test:443"
    assert runtime.settings.OBJECT_STORAGE_SECRET_KEY == "secret-b"
    assert second is not first
    assert health_api._ready_cache["payload"] is None
    reset_object_store_cache()


def test_get_object_store_for_uri_prefers_generic_minio_when_document_metadata_marks_object_storage(monkeypatch) -> None:  # noqa: ANN001
    sentinel = object()

    monkeypatch.setattr(
        runtime,
        "_build_generic_object_store",
        lambda provider, *, region=None: sentinel if provider == "minio" else None,
        raising=True,
    )

    store = runtime.get_object_store_for_uri(
        "minio://bucket/documents/a/b/c.pdf",
        document_metadata={runtime.SOURCE_STORAGE_BACKEND_KEY: runtime.SOURCE_STORAGE_BACKEND_OBJECT_STORAGE},
    )

    assert store is sentinel


def test_resolve_document_object_reference_validates_expected_bucket_and_key(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    store = SimpleNamespace(
        build_document_object_name=lambda **_kwargs: f"documents/{tenant_id}/{dataset_id}/{document_id}.pdf",
        describe_backend=lambda: {
            "provider": "s3",
            "enabled": True,
            "documents_enabled": True,
            "bucket": "bucket",
        },
    )

    monkeypatch.setattr(runtime, "get_object_store_for_uri", lambda *_args, **_kwargs: store, raising=True)

    resolved_store, ref = runtime.resolve_document_object_reference(
        f"s3://bucket/documents/{tenant_id}/{dataset_id}/{document_id}.pdf",
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        file_type="pdf",
    )

    assert resolved_store is store
    assert ref.bucket == "bucket"
