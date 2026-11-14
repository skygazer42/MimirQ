import pytest

from app.services import dataset_embedding_config


def test_invalid_stored_embedding_model_does_not_silently_inherit_the_global_model(monkeypatch):
    monkeypatch.setattr(dataset_embedding_config.settings, "VECTOR_BACKEND", "milvus")
    with pytest.raises(AttributeError):
        dataset_embedding_config.resolve_dataset_embedding_runtime({"embedding_defaults": {"model": 0}})


def test_nullable_embedding_override_inherits_but_literal_zero_model_is_retained(monkeypatch):
    monkeypatch.setattr(dataset_embedding_config.settings, "VECTOR_BACKEND", "milvus")
    implicit = dataset_embedding_config.resolve_dataset_embedding_runtime(None)
    inherited = dataset_embedding_config.resolve_dataset_embedding_runtime({"embedding_defaults": {"model": None}})
    explicit = dataset_embedding_config.resolve_dataset_embedding_runtime({"embedding_defaults": {"model": "0"}})
    assert inherited.model == implicit.model
    assert inherited.dataset_scoped is False
    assert explicit.model == "0"
    assert explicit.dataset_scoped is True
