from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_retrieval_config_hash_endpoint_is_stable_for_same_effective_config() -> None:
    import app.api.v1.retrieval_config_hash as api_mod

    tenant_id = uuid.uuid4()

    req = api_mod.RetrievalConfigHashRequest(
        rag_config={"retrieval_profile": "recall50", "top_k": 7, "retrieval_mode": "hybrid"},
    )

    out1 = await api_mod.get_retrieval_config_hash(
        body=req,
        tenant_id=tenant_id,
        account_id="u",
    )
    out2 = await api_mod.get_retrieval_config_hash(
        body=req,
        tenant_id=tenant_id,
        account_id="u",
    )

    assert out1.schema == "mimirq.retrieval_config_hash.v1"
    assert out1.hash == out2.hash
    assert out1.fingerprint.get("schema") == "mimirq.retrieval_config.v1"


@pytest.mark.asyncio
async def test_retrieval_config_hash_endpoint_changes_when_knobs_change() -> None:
    import app.api.v1.retrieval_config_hash as api_mod

    tenant_id = uuid.uuid4()

    a = await api_mod.get_retrieval_config_hash(
        body=api_mod.RetrievalConfigHashRequest(
            rag_config={"top_k": 7, "retrieval_mode": "hybrid"},
        ),
        tenant_id=tenant_id,
        account_id="u",
    )
    b = await api_mod.get_retrieval_config_hash(
        body=api_mod.RetrievalConfigHashRequest(
            rag_config={"top_k": 9, "retrieval_mode": "hybrid"},
        ),
        tenant_id=tenant_id,
        account_id="u",
    )

    assert a.hash != b.hash


@pytest.mark.asyncio
async def test_retrieval_config_hash_endpoint_includes_hierarchy_recall_knobs() -> None:
    import app.api.v1.retrieval_config_hash as api_mod

    tenant_id = uuid.uuid4()

    out = await api_mod.get_retrieval_config_hash(
        body=api_mod.RetrievalConfigHashRequest(
            rag_config={
                "enable_hierarchy_recall": True,
                "hierarchy_family_collapse": True,
                "hierarchy_family_aggregation": "combined",
                "hierarchy_tree_dedup": True,
                "hierarchy_parent_depth": 1,
                "hierarchy_sibling_window": 2,
                "hierarchy_overfetch_factor": 4,
            },
        ),
        tenant_id=tenant_id,
        account_id="u",
    )

    effective = out.effective_config
    assert effective.get("enable_hierarchy_recall") is True
    assert effective.get("hierarchy_family_collapse") is True
    assert effective.get("hierarchy_family_aggregation") == "combined"
    assert effective.get("hierarchy_tree_dedup") is True
    assert effective.get("hierarchy_parent_depth") == 1
    assert effective.get("hierarchy_sibling_window") == 2
    assert effective.get("hierarchy_overfetch_factor") == 4

    fp_cfg = out.fingerprint.get("config") or {}
    assert fp_cfg.get("enable_hierarchy_recall") is True
    assert fp_cfg.get("hierarchy_family_collapse") is True
    assert fp_cfg.get("hierarchy_family_aggregation") == "combined"
    assert fp_cfg.get("hierarchy_tree_dedup") is True
