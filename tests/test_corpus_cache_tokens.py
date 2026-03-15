from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


def test_document_scope_corpus_token_changes_when_pipeline_changes() -> None:
    from app.services.corpus_cache_tokens import build_document_scope_corpus_cache_token

    rows = [
        {
            "id": "doc-1",
            "updated_at": datetime(2026, 3, 7, 12, 0, tzinfo=UTC),
            "active_pipeline_hash": "pipe-a",
        }
    ]
    token_a = build_document_scope_corpus_cache_token(rows)
    token_b = build_document_scope_corpus_cache_token(
        [{**rows[0], "active_pipeline_hash": "pipe-b"}]
    )

    assert isinstance(token_a, str) and token_a
    assert token_a != token_b


def test_document_scope_corpus_token_changes_when_document_updates() -> None:
    from app.services.corpus_cache_tokens import build_document_scope_corpus_cache_token

    row = {
        "id": "doc-1",
        "updated_at": datetime(2026, 3, 7, 12, 0, tzinfo=UTC),
        "active_pipeline_hash": "pipe-a",
    }
    token_a = build_document_scope_corpus_cache_token([row])
    token_b = build_document_scope_corpus_cache_token(
        [{**row, "updated_at": datetime(2026, 3, 7, 12, 5, tzinfo=UTC)}]
    )

    assert token_a != token_b


def test_dataset_scope_corpus_token_changes_when_dataset_updates() -> None:
    from app.services.corpus_cache_tokens import build_dataset_scope_corpus_cache_token

    token_a = build_dataset_scope_corpus_cache_token(
        dataset_id="ds-1",
        updated_at=datetime(2026, 3, 7, 12, 0, tzinfo=UTC),
    )
    token_b = build_dataset_scope_corpus_cache_token(
        dataset_id="ds-1",
        updated_at=datetime(2026, 3, 7, 12, 5, tzinfo=UTC),
    )

    assert isinstance(token_a, str) and token_a
    assert token_a != token_b


def test_invalidate_dataset_cache_namespace_rotates_dataset_token(monkeypatch) -> None:  # noqa: ANN001
    from app.services import corpus_cache_tokens as token_mod

    tenant_id = uuid4()
    dataset_id = uuid4()
    initial_updated_at = datetime(2026, 3, 10, 11, 0, tzinfo=UTC)

    class _FakeDataset:
        def __init__(self) -> None:
            self.tenant_id = tenant_id
            self.id = dataset_id
            self.updated_at = initial_updated_at

    dataset = _FakeDataset()

    class _FakeUpdatedAtQuery:
        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN001
            return (dataset.updated_at,)

    class _FakeDatasetQuery:
        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN001
            return dataset

    class _FakeDB:
        def __init__(self) -> None:
            self.calls = 0

        def query(self, model, *_a, **_k):  # noqa: ANN001
            self.calls += 1
            if model is token_mod.Dataset.updated_at:
                return _FakeUpdatedAtQuery()
            return _FakeDatasetQuery()

    cleared = {"count": 0}
    monkeypatch.setattr(
        token_mod,
        "clear_evidence_post_rerank_cache",
        lambda: cleared.__setitem__("count", cleared["count"] + 1) or True,
        raising=True,
    )

    out = token_mod.invalidate_dataset_cache_namespace(
        _FakeDB(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
    )

    assert out["dataset_id"] == str(dataset_id)
    assert out["previous_corpus_cache_token"] != out["current_corpus_cache_token"]
    assert out["evidence_post_rerank_memory_cleared"] is True
    assert dataset.updated_at > initial_updated_at
    assert cleared["count"] == 1
