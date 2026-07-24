
from uuid import uuid4

import pytest


def test_resolve_chat_response_cache_key_changes_with_dataset_corpus_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_response_cache as cache_mod

    base = {
        "db": object(),
        "tenant_id": uuid4(),
        "account_id": "acct-1",
        "dataset_id": uuid4(),
        "document_ids": [],
        "question": "What changed?",
        "rag_config": {"top_k": 5, "retrieval_mode": "hybrid"},
        "prompt_config": {"prompt_template_id": None},
        "structured_output": False,
        "structured_preset": None,
        "use_graph": False,
    }

    monkeypatch.setattr(cache_mod, "resolve_corpus_cache_token", lambda *_a, **_k: "corp-a", raising=False)
    key_a, skip_a = cache_mod.resolve_chat_response_cache_key(**base)

    monkeypatch.setattr(cache_mod, "resolve_corpus_cache_token", lambda *_a, **_k: "corp-b", raising=False)
    key_b, skip_b = cache_mod.resolve_chat_response_cache_key(**base)

    assert skip_a is None
    assert skip_b is None
    assert isinstance(key_a, str) and key_a
    assert isinstance(key_b, str) and key_b
    assert key_a != key_b


def test_resolve_chat_response_cache_key_fails_closed_when_corpus_token_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_response_cache as cache_mod

    monkeypatch.setattr(cache_mod, "resolve_corpus_cache_token", lambda *_a, **_k: None, raising=False)

    key, skip_reason = cache_mod.resolve_chat_response_cache_key(
        db=object(),
        tenant_id=uuid4(),
        account_id="acct-1",
        dataset_id=uuid4(),
        document_ids=[],
        question="What changed?",
        rag_config={"top_k": 5, "retrieval_mode": "hybrid"},
        prompt_config={"prompt_template_id": None},
        structured_output=False,
        structured_preset=None,
        use_graph=False,
    )

    assert key is None
    assert skip_reason == "missing_corpus_cache_token"


class _Query:
    def __init__(self, *, rows=None, first_row=None) -> None:  # noqa: ANN001
        self._rows = list(rows or [])
        self._first_row = first_row

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return self

    def all(self):  # noqa: ANN202
        return list(self._rows)

    def first(self):  # noqa: ANN202
        return self._first_row


class _CorpusTokenDB:
    def __init__(self, *, document_rows, dataset_rows) -> None:  # noqa: ANN001
        self._document_rows = list(document_rows)
        self._dataset_rows = list(dataset_rows)

    def query(self, *entities):  # noqa: ANN002, ANN202
        if len(entities) >= 3:
            return _Query(rows=self._document_rows)
        return _Query(rows=self._dataset_rows)


def test_build_dataset_scope_corpus_cache_token_changes_with_dataset_embedding_binding() -> None:
    import app.services.corpus_cache_tokens as token_mod

    dataset_id = uuid4()
    token_a = token_mod.build_dataset_scope_corpus_cache_token(
        dataset_id=dataset_id,
        updated_at=None,
        dataset_embedding_binding={"embedding_space_hash": "emb-a", "dataset_scoped": True},
    )
    token_b = token_mod.build_dataset_scope_corpus_cache_token(
        dataset_id=dataset_id,
        updated_at=None,
        dataset_embedding_binding={"embedding_space_hash": "emb-b", "dataset_scoped": True},
    )

    assert isinstance(token_a, str) and token_a
    assert isinstance(token_b, str) and token_b
    assert token_a != token_b


def test_resolve_corpus_cache_token_fails_closed_when_document_scope_row_missing() -> None:
    import app.services.corpus_cache_tokens as token_mod

    token = token_mod.resolve_corpus_cache_token(
        _CorpusTokenDB(document_rows=[], dataset_rows=[]),
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        document_ids=[uuid4()],
    )

    assert token is None


def test_resolve_corpus_cache_token_changes_when_document_scope_dataset_embedding_defaults_change() -> None:
    import app.services.corpus_cache_tokens as token_mod

    tenant_id = uuid4()
    document_id = uuid4()
    dataset_id = uuid4()
    db_a = _CorpusTokenDB(
        document_rows=[(document_id, dataset_id, None, {})],
        dataset_rows=[(dataset_id, {"embedding_defaults": {"provider": "local", "model": "embed-a"}})],
    )
    db_b = _CorpusTokenDB(
        document_rows=[(document_id, dataset_id, None, {})],
        dataset_rows=[(dataset_id, {"embedding_defaults": {"provider": "local", "model": "embed-b"}})],
    )

    token_a = token_mod.resolve_corpus_cache_token(
        db_a,
        tenant_id=tenant_id,
        document_ids=[document_id],
    )
    token_b = token_mod.resolve_corpus_cache_token(
        db_b,
        tenant_id=tenant_id,
        document_ids=[document_id],
    )

    assert isinstance(token_a, str) and token_a
    assert isinstance(token_b, str) and token_b
    assert token_a != token_b


class _DatasetScopeTokenDB:
    def __init__(self, rows) -> None:  # noqa: ANN001
        self._rows = list(rows)

    def query(self, *_entities):  # noqa: ANN002, ANN202
        return _Query(rows=self._rows)


def test_resolve_corpus_cache_token_for_multi_dataset_scope_is_order_stable_and_binding_sensitive() -> None:
    import app.services.corpus_cache_tokens as token_mod

    tenant_id = uuid4()
    dataset_a = uuid4()
    dataset_b = uuid4()
    rows_a = [
        (dataset_a, "2026-01-01T00:00:00+00:00", {"embedding_defaults": {"provider": "local", "model": "embed-a"}}),
        (dataset_b, "2026-01-02T00:00:00+00:00", {"embedding_defaults": {"provider": "local", "model": "embed-b"}}),
    ]
    rows_b = [
        (dataset_a, "2026-01-01T00:00:00+00:00", {"embedding_defaults": {"provider": "local", "model": "embed-a"}}),
        (dataset_b, "2026-01-03T00:00:00+00:00", {"embedding_defaults": {"provider": "local", "model": "embed-c"}}),
    ]

    token_a = token_mod.resolve_corpus_cache_token(
        _DatasetScopeTokenDB(rows_a),
        tenant_id=tenant_id,
        dataset_ids=[dataset_b, dataset_a],
    )
    token_a_reordered = token_mod.resolve_corpus_cache_token(
        _DatasetScopeTokenDB(list(reversed(rows_a))),
        tenant_id=tenant_id,
        dataset_ids=[dataset_a, dataset_b],
    )
    token_b = token_mod.resolve_corpus_cache_token(
        _DatasetScopeTokenDB(rows_b),
        tenant_id=tenant_id,
        dataset_ids=[dataset_b, dataset_a],
    )

    assert isinstance(token_a, str) and token_a
    assert token_a == token_a_reordered
    assert isinstance(token_b, str) and token_b
    assert token_a != token_b
