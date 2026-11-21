from types import SimpleNamespace

import pytest
from pydantic import ValidationError


def test_retired_faiss_backend_is_rejected_at_startup():
    from app.infrastructure.config import Settings

    with pytest.raises(ValidationError, match="VECTOR_BACKEND"):
        Settings.model_validate({"VECTOR_BACKEND": "faiss", "SECRET_KEY": "retirement-test-key-is-not-a-real-secret"})


@pytest.mark.parametrize("selection", ["explicit", "region", "default", "cached"])
def test_retired_faiss_cannot_be_selected_or_silently_substituted(selection, monkeypatch):
    from app.storage.vector import factory

    monkeypatch.setattr(factory.settings, "VECTOR_BACKEND", "faiss" if selection == "default" else "memory")
    monkeypatch.setattr(factory.settings, "VECTOR_REGION_BACKENDS", '{"test-region":"faiss"}')
    monkeypatch.setattr(factory, "_VECTOR_STORE_SINGLETONS", {})
    if selection == "cached":
        monkeypatch.setattr(factory, "_vector_store_cache_key", lambda **_kwargs: "old-faiss")
        factory._VECTOR_STORE_SINGLETONS["old-faiss"] = object()
    with pytest.raises(ValueError, match="(?i)FAISS.*retired"):
        factory.get_vector_store(
            backend="faiss" if selection in {"explicit", "cached"} else None,
            region="test-region" if selection == "region" else None,
        )


@pytest.mark.parametrize("mode", ["ready", "health"])
def test_retired_backend_is_never_reported_as_ready(mode):
    from app.infrastructure.observability.health import check_vector

    vector, _milvus, ready = check_vector(SimpleNamespace(VECTOR_BACKEND="faiss"), mode=mode)
    assert ready is False
    assert vector["status"] == "retired"
