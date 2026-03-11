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
