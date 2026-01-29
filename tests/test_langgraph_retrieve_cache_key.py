from __future__ import annotations

from uuid import UUID

from app.rag.pipelines.langgraph import _retrieve_cache_key


def test_retrieve_cache_key_varies_by_account_and_dataset_scope() -> None:
    base = {
        "question": "q",
        "history": [],
        "tenant_id": UUID(int=1),
        "document_ids": [],
        "top_k": 5,
        "score_threshold": 0.7,
        "retrieval_mode": "hybrid",
    }

    k_a = _retrieve_cache_key({**base, "account_id": "a", "dataset_id": None})
    k_b = _retrieve_cache_key({**base, "account_id": "b", "dataset_id": None})
    assert k_a != k_b

    k_ds = _retrieve_cache_key({**base, "account_id": "a", "dataset_id": UUID(int=2)})
    assert k_a != k_ds

