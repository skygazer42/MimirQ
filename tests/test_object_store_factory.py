from __future__ import annotations

import json

import pytest


def test_get_object_store_defaults_to_minio(monkeypatch):  # noqa: ANN001
    import app.storage.object.factory as factory

    sentinel = object()
    monkeypatch.setattr(factory, "minio_service", sentinel, raising=True)

    store = factory.get_object_store(provider="minio")

    assert store is sentinel


def test_get_object_store_accepts_s3_compatible_aliases(monkeypatch):  # noqa: ANN001
    import app.storage.object.factory as factory

    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_ENABLED", True, raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_ENDPOINT", "compat.example.com", raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_ACCESS_KEY", "ak", raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_SECRET_KEY", "sk", raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_BUCKET_NAME", "assets", raising=False)

    assert factory.get_object_store(provider="s3").describe_backend()["provider"] == "s3"
    assert factory.get_object_store(provider="oss").describe_backend()["provider"] == "oss"
    assert factory.get_object_store(provider="cos").describe_backend()["provider"] == "cos"


def test_get_object_store_builds_configured_s3_store(monkeypatch):  # noqa: ANN001
    import app.storage.object.factory as factory

    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_ENABLED", True, raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_ENDPOINT", "s3.us-east-1.amazonaws.com", raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_ACCESS_KEY", "ak", raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_SECRET_KEY", "sk", raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_BUCKET_NAME", "rag-assets", raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_USE_SSL", True, raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_DOCUMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_METRICS_LOG_PATH", "./logs/object_store_metrics.jsonl", raising=False)

    store = factory.get_object_store(provider="s3")

    assert store is not factory.minio_service
    desc = store.describe_backend()
    assert desc == {
        "provider": "s3",
        "enabled": True,
        "endpoint": "s3.us-east-1.amazonaws.com",
        "bucket": "rag-assets",
        "secure": True,
        "documents_enabled": True,
    }


def test_get_object_store_uses_default_provider_from_settings(monkeypatch):  # noqa: ANN001
    import app.storage.object.factory as factory

    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_PROVIDER", "oss", raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_ENABLED", True, raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_ENDPOINT", "oss-cn-shanghai.aliyuncs.com", raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_ACCESS_KEY", "ak", raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_SECRET_KEY", "sk", raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_BUCKET_NAME", "oss-bucket", raising=False)
    monkeypatch.setattr(factory.settings, "OBJECT_STORAGE_USE_SSL", True, raising=False)

    store = factory.get_object_store()

    assert store is not factory.minio_service
    assert store.describe_backend()["provider"] == "oss"
    assert store.describe_backend()["bucket"] == "oss-bucket"


def test_get_object_store_rejects_unknown_provider() -> None:
    from app.storage.object.factory import get_object_store

    with pytest.raises(ValueError):
        get_object_store(provider="unknown")


def test_get_object_store_routes_region_profile(monkeypatch):  # noqa: ANN001
    import app.storage.object.factory as factory

    monkeypatch.setattr(factory.settings, "DATA_REGION", "cn-shanghai", raising=False)
    monkeypatch.setattr(
        factory.settings,
        "OBJECT_STORAGE_REGION_PROFILES",
        json.dumps(
            {
                "cn-shanghai": {
                    "provider": "oss",
                    "endpoint": "oss-cn-shanghai.aliyuncs.com",
                    "access_key": "ak-cn",
                    "secret_key": "sk-cn",
                    "bucket_name": "cn-bucket",
                    "use_ssl": True,
                    "documents_enabled": True,
                }
            }
        ),
        raising=False,
    )

    store = factory.get_object_store()
    desc = store.describe_backend()

    assert desc["provider"] == "oss"
    assert desc["endpoint"] == "oss-cn-shanghai.aliyuncs.com"
    assert desc["bucket"] == "cn-bucket"
    assert desc["documents_enabled"] is True
