
from app.rag.core.retrieval_config_fingerprint import build_retrieval_config_fingerprint


def test_retrieval_config_fingerprint_removes_sensitive_values_recursively() -> None:
    result = build_retrieval_config_fingerprint(
        config={
            "retrieval_mode": "hybrid",
            "query": "secret query",
            "nested": {
                "tenant_id": "tenant-secret",
                "weights": [0.7, None, 0.3],
                "empty": {"question": "secret"},
            },
        }
    )

    assert result["schema"] == "mimirq.retrieval_config.v1"
    assert len(result["hash"]) == 32
    assert result["config"] == {
        "retrieval_mode": "hybrid",
        "nested": {"weights": [0.7, 0.3]},
    }


def test_retrieval_config_fingerprint_is_stable_for_equivalent_key_order() -> None:
    first = build_retrieval_config_fingerprint(config={"top_k": 5, "weights": {"vector": 0.7, "bm25": 0.3}})
    second = build_retrieval_config_fingerprint(config={"weights": {"bm25": 0.3, "vector": 0.7}, "top_k": 5})

    assert first == second
