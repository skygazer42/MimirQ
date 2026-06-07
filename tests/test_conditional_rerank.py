from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.callbacks import CallbackManagerForRetrieverRun

from app.core.config import settings
from app.rag.reranker.base import BaseReranker
from app.rag.reranker.types import RerankCandidate, RerankResult
from app.rag.retriever import HybridRetriever


class _StubVectorStore:
    def __init__(self, *, results):  # noqa: ANN001
        self._results = list(results)

    def search(self, **_kwargs):  # noqa: ANN003
        return list(self._results)


@dataclass
class _CountingReranker(BaseReranker):
    calls: list[int]

    def rerank(self, query: str, candidates: Sequence[RerankCandidate], **kwargs: Any) -> RerankResult:  # noqa: ARG002
        top_n = int(kwargs.get("top_n") or 0)
        self.calls.append(top_n)
        ordered = [str(c.id) for c in candidates]
        score_map = {cid: float(len(ordered) - i) for i, cid in enumerate(ordered)}
        return RerankResult(ordered_ids=ordered, score_map=score_map, provider="stub", model_used="stub")


@dataclass
class _FixedScoreReranker(BaseReranker):
    scores_by_service_name: dict[str, float]

    def rerank(self, query: str, candidates: Sequence[RerankCandidate], **kwargs: Any) -> RerankResult:  # noqa: ARG002
        scores: dict[str, float] = {}
        for c in candidates:
            meta = c.metadata if isinstance(c.metadata, dict) else {}
            service_name = str(meta.get("service_name") or "").strip()
            scores[str(c.id)] = float(self.scores_by_service_name.get(service_name, 0.0))
        ordered = sorted(scores, key=lambda cid: (-float(scores[cid]), cid))
        return RerankResult(ordered_ids=ordered, score_map=scores, provider="stub", model_used="stub")


def _mk_candidate(*, dataset_id: str, score: float, index: int) -> dict[str, Any]:
    return {
        "chunk_id": str(uuid4()),
        "content": f"vector hit {index}",
        "metadata": {"document_id": str(uuid4()), "dataset_id": dataset_id, "chunk_index": index},
        "score": float(score),
    }


def _build_vector_retriever() -> HybridRetriever:
    retriever = HybridRetriever()
    retriever.k = 3
    retriever.tenant_id = uuid4()
    retriever.dataset_id = uuid4()
    retriever.account_id = "u"
    retriever.retrieval_mode = "vector"
    retriever.enable_weight_rerank = False
    retriever.enable_reranker = True
    retriever.reranker_provider = "stub"
    retriever.reranker_top_n = 3
    return retriever


def test_retriever_skips_reranker_when_top_hit_is_high_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    retriever = _build_vector_retriever()
    ds_id = str(retriever.dataset_id)

    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 1, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 0, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RERANK_CONDITIONAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RERANK_SKIP_THRESHOLD", 0.9, raising=False)
    monkeypatch.setattr(settings, "RERANK_SKIP_GAP", 0.15, raising=False)

    vector_candidates = [
        _mk_candidate(dataset_id=ds_id, score=0.96, index=0),
        _mk_candidate(dataset_id=ds_id, score=0.70, index=1),
        _mk_candidate(dataset_id=ds_id, score=0.61, index=2),
    ]
    stub_store = _StubVectorStore(results=vector_candidates)
    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: stub_store, raising=True)
    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: stub_store, raising=False)

    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda _self, r, **_k: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda _self, r: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda _self, r: r, raising=True)

    reranker_calls: list[int] = []
    monkeypatch.setattr(
        "app.rag.retriever.get_reranker",
        lambda _provider: _CountingReranker(calls=reranker_calls),
        raising=True,
    )

    retriever._get_relevant_documents(
        "q",
        run_manager=CallbackManagerForRetrieverRun.get_noop_manager(),
    )

    assert reranker_calls == []
    channels = (retriever._last_debug_metrics or {}).get("channels") or {}
    rerank = channels.get("rerank") or {}
    assert rerank.get("used") is False
    assert rerank.get("skip_reason") == "high_confidence"
    assert rerank.get("skip_top_score") == pytest.approx(1.0)
    assert float(rerank.get("skip_score_gap") or 0.0) > 0.15


def test_retriever_keeps_reranker_when_confidence_gate_is_not_met(monkeypatch: pytest.MonkeyPatch) -> None:
    retriever = _build_vector_retriever()
    ds_id = str(retriever.dataset_id)

    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 1, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 0, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RERANK_CONDITIONAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RERANK_SKIP_THRESHOLD", 0.9, raising=False)
    monkeypatch.setattr(settings, "RERANK_SKIP_GAP", 0.15, raising=False)

    vector_candidates = [
        _mk_candidate(dataset_id=ds_id, score=0.84, index=0),
        _mk_candidate(dataset_id=ds_id, score=0.83, index=1),
        _mk_candidate(dataset_id=ds_id, score=0.10, index=2),
    ]
    stub_store = _StubVectorStore(results=vector_candidates)
    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: stub_store, raising=True)
    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: stub_store, raising=False)

    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda _self, r, **_k: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda _self, r: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda _self, r: r, raising=True)

    reranker_calls: list[int] = []
    monkeypatch.setattr(
        "app.rag.retriever.get_reranker",
        lambda _provider: _CountingReranker(calls=reranker_calls),
        raising=True,
    )

    retriever._get_relevant_documents(
        "q",
        run_manager=CallbackManagerForRetrieverRun.get_noop_manager(),
    )

    assert reranker_calls == [3]
    channels = (retriever._last_debug_metrics or {}).get("channels") or {}
    rerank = channels.get("rerank") or {}
    assert rerank.get("used") is True
    assert rerank.get("skip_reason") is None


def test_retriever_promotes_exact_metadata_anchor_after_api_rerank(monkeypatch: pytest.MonkeyPatch) -> None:
    retriever = _build_vector_retriever()
    ds_id = str(retriever.dataset_id)
    query = "文艺表演团体变更地址咨询电话是多少？"

    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 1, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 0, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RERANK_CONDITIONAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35, raising=False)

    wrong = _mk_candidate(dataset_id=ds_id, score=0.90, index=0)
    wrong["content"] = "事项名称：演出场所经营单位变更法人或主要负责人\n咨询方式：12345"
    wrong["metadata"]["service_name"] = "演出场所经营单位变更法人或主要负责人"
    wrong["metadata"]["_evaluable_metadata"] = {"service_name": "演出场所经营单位变更法人或主要负责人"}

    correct = _mk_candidate(dataset_id=ds_id, score=0.89, index=1)
    correct["content"] = "事项名称：文艺表演团体变更地址\n咨询方式：0519-12345"
    correct["metadata"]["service_name"] = "文艺表演团体变更地址"
    correct["metadata"]["_evaluable_metadata"] = {"service_name": "文艺表演团体变更地址"}

    stub_store = _StubVectorStore(results=[wrong, correct])
    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: stub_store, raising=True)
    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: stub_store, raising=False)

    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda _self, r, **_k: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda _self, r: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda _self, r: r, raising=True)

    monkeypatch.setattr(
        "app.rag.retriever.get_reranker",
        lambda _provider: _FixedScoreReranker(
            scores_by_service_name={
                "演出场所经营单位变更法人或主要负责人": 0.728,
                "文艺表演团体变更地址": 0.727,
            }
        ),
        raising=True,
    )

    docs = retriever._get_relevant_documents(
        query,
        run_manager=CallbackManagerForRetrieverRun.get_noop_manager(),
    )

    assert docs[0].metadata["service_name"] == "文艺表演团体变更地址"
    assert docs[0].metadata["rerank_score"] == pytest.approx(0.727)
    assert docs[0].metadata["metadata_exact_match_field"] == "service_name"
    assert float(docs[0].metadata["metadata_exact_match_boost"]) > 0.0


def test_retriever_combines_title_and_intent_metadata_anchors_after_api_rerank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retriever = _build_vector_retriever()
    ds_id = str(retriever.dataset_id)
    query = "开办餐饮店一件事办理注意事项有哪些？"

    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 1, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 0, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RERANK_CONDITIONAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35, raising=False)

    guide = _mk_candidate(dataset_id=ds_id, score=0.90, index=0)
    guide["content"] = "一件事：开办餐饮店“一件事”\n章节：涉及事项"
    guide["metadata"]["case_title"] = "开办餐饮店“一件事”"
    guide["metadata"]["section_type"] = "related_services"
    guide["metadata"]["_evaluable_metadata"] = {
        "case_title": "开办餐饮店“一件事”",
        "retrieval_intents": ["涉及事项", "联办事项"],
    }

    notes = _mk_candidate(dataset_id=ds_id, score=0.89, index=1)
    notes["content"] = "一件事：开办餐饮店“一件事”\n章节：备注\n按页面提示提交。"
    notes["metadata"]["case_title"] = "开办餐饮店“一件事”"
    notes["metadata"]["section_type"] = "operation_notes"
    notes["metadata"]["_evaluable_metadata"] = {
        "case_title": "开办餐饮店“一件事”",
        "retrieval_intents": ["备注", "注意事项", "办理注意事项"],
    }

    stub_store = _StubVectorStore(results=[guide, notes])
    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: stub_store, raising=True)
    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: stub_store, raising=False)

    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda _self, r, **_k: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda _self, r: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda _self, r: r, raising=True)

    # Use section_type-aware fixed scores without adding a second fake reranker class.
    class _SectionScoreReranker(BaseReranker):
        def rerank(self, query: str, candidates: Sequence[RerankCandidate], **kwargs: Any) -> RerankResult:  # noqa: ARG002
            scores = {}
            for c in candidates:
                meta = c.metadata if isinstance(c.metadata, dict) else {}
                scores[str(c.id)] = 0.729 if meta.get("section_type") == "related_services" else 0.724
            ordered = sorted(scores, key=lambda cid: (-float(scores[cid]), cid))
            return RerankResult(ordered_ids=ordered, score_map=scores, provider="stub", model_used="stub")

    monkeypatch.setattr("app.rag.retriever.get_reranker", lambda _provider: _SectionScoreReranker(), raising=True)

    docs = retriever._get_relevant_documents(
        query,
        run_manager=CallbackManagerForRetrieverRun.get_noop_manager(),
    )

    assert docs[0].metadata["section_type"] == "operation_notes"
    assert "case_title" in docs[0].metadata["metadata_exact_match_fields"]
    assert "retrieval_intents" in docs[0].metadata["metadata_exact_match_fields"]
    assert float(docs[0].metadata["metadata_exact_match_boost"]) > float(docs[1].metadata["metadata_exact_match_boost"])


def test_retriever_promotes_post_expansion_intent_anchor_over_title_only_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retriever = _build_vector_retriever()
    ds_id = str(retriever.dataset_id)
    query = "开办餐饮店“一件事”办理注意事项有哪些？"

    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 1, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 0, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RERANK_CONDITIONAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35, raising=False)

    guide = _mk_candidate(dataset_id=ds_id, score=0.90, index=0)
    guide["content"] = "一件事：开办餐饮店“一件事”\n章节：涉及事项"
    guide["metadata"]["case_key"] = "开办餐饮店一件事"
    guide["metadata"]["case_title"] = "开办餐饮店“一件事”"
    guide["metadata"]["case_title_raw"] = "开办餐饮店“一件事”"
    guide["metadata"]["section_type"] = "related_services"
    guide["metadata"]["_evaluable_metadata"] = {
        "case_key": "开办餐饮店一件事",
        "case_title": "开办餐饮店“一件事”",
        "case_title_raw": "开办餐饮店“一件事”",
        "retrieval_intents": ["涉及事项", "联办事项"],
    }

    notes = _mk_candidate(dataset_id=ds_id, score=0.0, index=1)
    notes.pop("score", None)
    notes["content"] = "一件事：开办餐饮店“一件事”\n章节：备注\n按页面提示提交。"
    notes["metadata"]["case_key"] = "开办餐饮店一件事"
    notes["metadata"]["case_title"] = "开办餐饮店“一件事”"
    notes["metadata"]["case_title_raw"] = "开办餐饮店“一件事”"
    notes["metadata"]["section_type"] = "operation_notes"
    notes["metadata"]["retrieval_role"] = "neighbor"
    notes["metadata"]["_evaluable_metadata"] = {
        "case_key": "开办餐饮店一件事",
        "case_title": "开办餐饮店“一件事”",
        "case_title_raw": "开办餐饮店“一件事”",
        "retrieval_intents": ["备注", "注意事项", "办理注意事项"],
    }

    stub_store = _StubVectorStore(results=[guide])
    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: stub_store, raising=True)
    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: stub_store, raising=False)

    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda _self, r, **_k: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda _self, r: list(r) + [notes], raising=True)
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda _self, r: r, raising=True)

    class _GuideOnlyReranker(BaseReranker):
        def rerank(self, query: str, candidates: Sequence[RerankCandidate], **kwargs: Any) -> RerankResult:  # noqa: ARG002
            ordered = [str(c.id) for c in candidates]
            return RerankResult(
                ordered_ids=ordered,
                score_map={cid: 0.729 for cid in ordered},
                provider="stub",
                model_used="stub",
            )

    monkeypatch.setattr("app.rag.retriever.get_reranker", lambda _provider: _GuideOnlyReranker(), raising=True)

    docs = retriever._get_relevant_documents(
        query,
        run_manager=CallbackManagerForRetrieverRun.get_noop_manager(),
    )

    assert docs[0].metadata["section_type"] == "operation_notes"
    assert docs[0].metadata["metadata_exact_match_promoted_score"] == pytest.approx(0.675)
    assert "retrieval_intents" in docs[0].metadata["metadata_exact_match_fields"]
    assert float(docs[0].metadata["metadata_exact_match_score"]) > float(docs[1].metadata["metadata_exact_match_score"])
    post_stats = (retriever._last_debug_metrics or {}).get("metadata_exact_anchor_post") or {}
    assert post_stats["top_changed"] is True
