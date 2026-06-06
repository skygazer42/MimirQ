from __future__ import annotations


def test_build_retrieval_config_fingerprint_strips_sensitive_fields_and_hashes_stably() -> None:
    from app.rag.core.retrieval_config_fingerprint import build_retrieval_config_fingerprint

    fp1 = build_retrieval_config_fingerprint(
        config={
            "requested_retrieval_mode": "vector",
            "retrieval_mode": "vector",
            "top_k": 5,
            "score_threshold": 0.0,
            "question": "should-not-be-in-config",
            "query": "should-not-be-in-config",
            "document_ids": ["doc-1"],
            "dataset_id": "ds-1",
            "tenant_id": "t-1",
            "account_id": "u",
            "metadata_filter": {"page": {"$gte": 10}},
        }
    )

    assert fp1.get("schema") == "mimirq.retrieval_config.v1"
    assert isinstance(fp1.get("hash"), str) and len(fp1.get("hash") or "") >= 16
    cfg1 = fp1.get("config") or {}
    assert isinstance(cfg1, dict)

    for k in ("question", "query", "document_ids", "dataset_id", "tenant_id", "account_id", "metadata_filter"):
        assert k not in cfg1
    assert isinstance(cfg1.get("metadata_filter_hash"), str) and cfg1.get("metadata_filter_hash")
    assert cfg1.get("metadata_filter_summary") == {
        "keys_count": 1,
        "keys_sample": ["page"],
        "ops": {"$gte": 1},
    }
    assert "10" not in str(cfg1)

    # Changing only question-like text should not affect the fingerprint.
    fp2 = build_retrieval_config_fingerprint(
        config={
            "requested_retrieval_mode": "vector",
            "retrieval_mode": "vector",
            "top_k": 5,
            "score_threshold": 0.0,
            "question": "different",
            "metadata_filter": {"page": {"$gte": 10}},
        }
    )
    assert fp2.get("hash") == fp1.get("hash")

    # Changing retrieval config or filter values must affect the fingerprint.
    fp3 = build_retrieval_config_fingerprint(
        config={
            "requested_retrieval_mode": "vector",
            "retrieval_mode": "vector",
            "top_k": 6,
            "score_threshold": 0.0,
        }
    )
    assert fp3.get("hash") != fp1.get("hash")

    fp4 = build_retrieval_config_fingerprint(
        config={
            "requested_retrieval_mode": "vector",
            "retrieval_mode": "vector",
            "top_k": 5,
            "score_threshold": 0.0,
            "metadata_filter": {"page": {"$gte": 11}},
        }
    )
    assert fp4.get("hash") != fp1.get("hash")


def test_build_retrieval_config_fingerprint_keeps_hierarchy_recall_knobs() -> None:
    from app.rag.core.retrieval_config_fingerprint import build_retrieval_config_fingerprint

    fp = build_retrieval_config_fingerprint(
        config={
            "retrieval_mode": "hybrid",
            "top_k": 20,
            "enable_hierarchy_recall": True,
            "hierarchy_family_collapse": True,
            "hierarchy_family_aggregation": "combined",
            "hierarchy_tree_dedup": True,
            "hierarchy_parent_depth": 1,
            "hierarchy_sibling_window": 2,
            "hierarchy_overfetch_factor": 4,
        }
    )

    cfg = fp.get("config") or {}
    assert cfg.get("enable_hierarchy_recall") is True
    assert cfg.get("hierarchy_family_collapse") is True
    assert cfg.get("hierarchy_family_aggregation") == "combined"
    assert cfg.get("hierarchy_tree_dedup") is True
    assert cfg.get("hierarchy_parent_depth") == 1
    assert cfg.get("hierarchy_sibling_window") == 2
    assert cfg.get("hierarchy_overfetch_factor") == 4
