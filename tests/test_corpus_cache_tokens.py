from __future__ import annotations

from datetime import datetime, timezone


def test_document_scope_corpus_token_changes_when_pipeline_changes() -> None:
    from app.services.corpus_cache_tokens import build_document_scope_corpus_cache_token

    rows = [
        {
            "id": "doc-1",
            "updated_at": datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc),
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
        "updated_at": datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc),
        "active_pipeline_hash": "pipe-a",
    }
    token_a = build_document_scope_corpus_cache_token([row])
    token_b = build_document_scope_corpus_cache_token(
        [{**row, "updated_at": datetime(2026, 3, 7, 12, 5, tzinfo=timezone.utc)}]
    )

    assert token_a != token_b


def test_dataset_scope_corpus_token_changes_when_dataset_updates() -> None:
    from app.services.corpus_cache_tokens import build_dataset_scope_corpus_cache_token

    token_a = build_dataset_scope_corpus_cache_token(
        dataset_id="ds-1",
        updated_at=datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc),
    )
    token_b = build_dataset_scope_corpus_cache_token(
        dataset_id="ds-1",
        updated_at=datetime(2026, 3, 7, 12, 5, tzinfo=timezone.utc),
    )

    assert isinstance(token_a, str) and token_a
    assert token_a != token_b
