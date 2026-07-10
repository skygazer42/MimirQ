
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
