from datetime import UTC, datetime

from app.services.corpus_cache_tokens import (
    build_dataset_scope_corpus_cache_token,
    build_document_scope_corpus_cache_token,
)


def test_corpus_token_keeps_an_explicit_empty_revision_distinct_from_absence() -> None:
    empty = build_dataset_scope_corpus_cache_token(dataset_id="dataset-1", updated_at="")
    missing = build_dataset_scope_corpus_cache_token(dataset_id="dataset-1", updated_at=None)

    assert empty != missing


def test_corpus_revision_codec_keeps_datetime_and_iso_text_equivalent() -> None:
    revision = datetime(2026, 11, 8, tzinfo=UTC)

    assert build_dataset_scope_corpus_cache_token(
        dataset_id="dataset-1", updated_at=revision
    ) == build_dataset_scope_corpus_cache_token(dataset_id="dataset-1", updated_at=revision.isoformat())


def test_document_corpus_token_keeps_the_actual_optional_dataset_value() -> None:
    empty = build_document_scope_corpus_cache_token([{"id": "document-1", "dataset_id": "", "updated_at": None}])
    missing = build_document_scope_corpus_cache_token([{"id": "document-1", "dataset_id": None, "updated_at": None}])

    assert empty != missing


def test_missing_document_identity_does_not_create_an_admitted_corpus_token() -> None:
    assert build_document_scope_corpus_cache_token([]) is None
    assert build_document_scope_corpus_cache_token([{"dataset_id": "dataset-1"}]) is None
