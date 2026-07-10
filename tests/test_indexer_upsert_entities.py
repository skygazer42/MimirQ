
import uuid
from uuid import UUID

import pytest


def test_indexer_upsert_entities_sets_extra_data_and_indexes_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.indexer as indexer_mod

    class _StubMilvus:  # noqa: D401
        """No-op vector adapter."""

        def add_vectors(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
            return []

    monkeypatch.setattr(indexer_mod, "get_milvus_adapter", lambda **_k: _StubMilvus(), raising=True)

    class _FakeSession:
        def commit(self) -> None:  # noqa: D401
            """No-op."""

        def flush(self) -> None:  # noqa: D401
            """No-op."""

    class _FakeEntity:
        def __init__(self) -> None:
            self.id = uuid.uuid4()
            self.vector = None
            self.extra_data = None
            self.description = None

    db = _FakeSession()
    indexer = indexer_mod.Indexer(db)  # type: ignore[arg-type]

    ent = _FakeEntity()

    def _fake_get_or_create_entity(self, **_kwargs):  # noqa: ANN001, ANN003
        return ent

    monkeypatch.setattr(indexer_mod.Indexer, "_get_or_create_entity", _fake_get_or_create_entity, raising=True)

    called = {"indexed": False}

    def _fake_index_entity_vectors(self, entities):  # noqa: ANN001
        called["indexed"] = True
        assert entities and entities[0] is ent
        return []

    monkeypatch.setattr(indexer_mod.Indexer, "_index_entity_vectors", _fake_index_entity_vectors, raising=True)

    out = indexer.upsert_entities(
        tenant_id=UUID(int=1),
        entities=[
            {
                "name": "Setup Python venv",
                "normalized_name": "setup python venv",
                "type": "Skill",
                "description": "Create and activate a venv.",
                "vector": [0.1],
                "extra_data": {"steps": ["python -m venv .venv"]},
            }
        ],
        commit=True,
        options=None,
    )

    assert out == [ent]
    assert ent.vector == [0.1]
    assert ent.extra_data == {"steps": ["python -m venv .venv"]}
    assert called["indexed"] is True

