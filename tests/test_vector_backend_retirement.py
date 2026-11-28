import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize("backend", ["qdrant", "pgvector"])
def test_retired_vector_backend_is_rejected_at_startup(backend):
    from app.infrastructure.config import Settings

    with pytest.raises(ValidationError, match="VECTOR_BACKEND"):
        Settings.model_validate({"VECTOR_BACKEND": backend, "SECRET_KEY": "retirement-test-key-is-not-a-real-secret"})


@pytest.mark.parametrize("backend", ["qdrant", "pgvector"])
@pytest.mark.parametrize("selection", ["explicit", "region", "default", "cached"])
def test_retired_vector_backend_cannot_resolve_or_reuse_a_cached_store(backend, selection, monkeypatch):
    from app.storage.vector import factory

    monkeypatch.setattr(factory.settings, "VECTOR_BACKEND", backend if selection == "default" else "memory")
    monkeypatch.setattr(factory.settings, "VECTOR_REGION_BACKENDS", json.dumps({"test-region": backend}))
    monkeypatch.setattr(factory, "_VECTOR_STORE_SINGLETONS", {})
    if selection == "cached":
        monkeypatch.setattr(factory, "_vector_store_cache_key", lambda **_kwargs: "old-store")
        factory._VECTOR_STORE_SINGLETONS["old-store"] = object()

    with pytest.raises(ValueError, match=backend):
        factory.get_vector_store(
            backend=backend if selection in {"explicit", "cached"} else None,
            region="test-region" if selection == "region" else "",
        )


def test_unknown_vector_backend_is_rejected_before_returning_a_placeholder(monkeypatch):
    from app.storage.vector import factory

    monkeypatch.setattr(factory.settings, "VECTOR_REGION_BACKENDS", "")
    with pytest.raises(ValueError, match="unsupported-test-backend"):
        factory.get_vector_store(backend="unsupported-test-backend", region="")


@pytest.mark.parametrize("backend", ["qdrant", "pgvector", "unsupported-test-backend"])
@pytest.mark.parametrize("mode", ["ready", "health"])
def test_unsupported_vector_backend_is_never_reported_as_ready(backend, mode):
    from app.infrastructure.observability.health import check_vector

    vector, _milvus, ready = check_vector(SimpleNamespace(VECTOR_BACKEND=backend), mode=mode)
    assert ready is False
    assert vector["status"] == "unsupported"
    assert backend in vector["error"]
