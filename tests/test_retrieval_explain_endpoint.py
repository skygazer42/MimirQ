from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_retrieval_explain_endpoint_returns_deterministic_schema_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)

    import app.api.v1.retrieval_explain as api_mod

    monkeypatch.setattr(api_mod.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    captured: dict = {}

    def _build_rag_state(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return {"question": kwargs.get("question")}

    def _run_retrieval(_state):  # noqa: ANN001
        return {
            "query_for_retrieval": "q_norm",
            "citations": [
                {"chunk_id": "c1", "document_id": "d1", "relevance_score": 0.91, "source": "a.md"},
                {"chunk_id": "c2", "document_id": "d2", "relevance_score": 0.65, "source": "b.md"},
            ],
            "query_debug": {"channels": {"vector": {"count": 5}, "keyword": {"count": 2}}},
            "metrics": {
                "retrieval_elapsed_sec": 0.123,
                "rewrite_elapsed_sec": 0.011,
                "multi_query_elapsed_sec": 0.02,
                "decompose_elapsed_sec": 0.0,
                "evidence_post_rerank_elapsed_sec": 0.014,
                "retrieval_query_count": 2,
                "evidence_post_rerank_provider": "ltr",
                "evidence_post_rerank_used": True,
                "evidence_post_rerank_candidates_n": 20,
                "evidence_post_rerank_pipeline_stages": ["ltr", "colbert"],
            },
        }

    monkeypatch.setattr(api_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(api_mod, "run_retrieval", _run_retrieval, raising=True)

    res = await api_mod.explain_retrieval(
        body=api_mod.RetrievalExplainRequest(query="What is recall?"),
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert res.schema == "mimirq.retrieval_explain.v1"
    assert res.retrieval_only is True
    assert res.query_for_retrieval == "q_norm"
    assert res.channels == {"vector": {"count": 5}, "keyword": {"count": 2}}
    assert res.candidate_counts == {"query_count": 2, "citations": 2}
    assert res.rerank.get("provider") == "ltr"
    assert res.rerank.get("used") is True
    assert res.rerank.get("candidates_n") == 20
    assert res.rerank.get("pipeline_stages") == ["ltr", "colbert"]
    assert res.stage_timings.get("retrieval_elapsed_sec") == 0.123
    assert res.stage_timings.get("post_rerank_elapsed_sec") == 0.014
    assert len(res.top_citations) == 2
    assert res.top_citations[0].get("chunk_id") == "c1"
    assert str(captured.get("retrieval_profile") or "").strip().lower() == "recall50"

