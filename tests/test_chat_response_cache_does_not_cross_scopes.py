import inspect

import pytest

from app.services.chat_response_cache import build_chat_cache_key


def _supports_dataset_id_param() -> bool:
    return "dataset_id" in inspect.signature(build_chat_cache_key).parameters


def test_build_chat_cache_key_accepts_dataset_id() -> None:
    # O31 safety: dataset-scoped chats should never share cached responses.
    assert _supports_dataset_id_param()


def test_chat_cache_key_differs_across_dataset_scopes(monkeypatch) -> None:
    if not _supports_dataset_id_param():
        # The assertion in the test above already fails in this case.
        pytest.skip("build_chat_cache_key missing dataset_id parameter")

    # Keep pipeline stable for this test; scope changes should still affect key.
    monkeypatch.setattr("app.services.chat_response_cache.current_embedding_space_hash", lambda: "embspace-a", raising=False)

    base = {
        "tenant_id": "t1",
        "account_id": "acct-1",
        "document_ids": ["doc-a", "doc-b"],
        "question": "What is the policy?",
        "rag_config": {"top_k": 5, "retrieval_mode": "hybrid"},
        "prompt_config": {"prompt_template_id": None},
        "structured_output": False,
        "structured_preset": None,
        "use_graph": False,
    }

    key_a = build_chat_cache_key(**base, dataset_id="ds-a")
    key_b = build_chat_cache_key(**base, dataset_id="ds-b")
    assert key_a != key_b


def test_chat_cache_key_differs_across_embedding_space(monkeypatch) -> None:
    if not _supports_dataset_id_param():
        pytest.skip("build_chat_cache_key missing dataset_id parameter")

    base = {
        "tenant_id": "t1",
        "account_id": "acct-1",
        "dataset_id": "ds-a",
        "document_ids": ["doc-a", "doc-b"],
        "question": "What is the policy?",
        "rag_config": {"top_k": 5, "retrieval_mode": "hybrid"},
        "prompt_config": {"prompt_template_id": None},
        "structured_output": False,
        "structured_preset": None,
        "use_graph": False,
    }

    monkeypatch.setattr("app.services.chat_response_cache.current_embedding_space_hash", lambda: "embspace-a", raising=False)
    key_a = build_chat_cache_key(**base)

    monkeypatch.setattr("app.services.chat_response_cache.current_embedding_space_hash", lambda: "embspace-b", raising=False)
    key_b = build_chat_cache_key(**base)

    assert key_a != key_b


def test_chat_cache_key_differs_across_corpus_cache_token(monkeypatch) -> None:
    if not _supports_dataset_id_param():
        pytest.skip("build_chat_cache_key missing dataset_id parameter")

    monkeypatch.setattr("app.services.chat_response_cache.current_embedding_space_hash", lambda: "embspace-a", raising=False)

    base = {
        "tenant_id": "t1",
        "account_id": "acct-1",
        "dataset_id": "ds-a",
        "document_ids": ["doc-a", "doc-b"],
        "question": "What is the policy?",
        "rag_config": {"top_k": 5, "retrieval_mode": "hybrid"},
        "prompt_config": {"prompt_template_id": None},
        "structured_output": False,
        "structured_preset": None,
        "use_graph": False,
        "corpus_cache_token": "corp-a",
    }

    key_a = build_chat_cache_key(**base)
    key_b = build_chat_cache_key(**{**base, "corpus_cache_token": "corp-b"})
    assert key_a != key_b
