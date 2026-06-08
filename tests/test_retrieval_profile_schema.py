import pytest


def test_chat_rag_config_recall20_overrides_top_k_and_threshold() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(retrieval_profile="recall20", top_k=5, score_threshold=0.7)

    assert cfg.top_k >= 20
    assert cfg.score_threshold == pytest.approx(0.0)


def test_chat_rag_config_recall50_overrides_top_k_and_threshold() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(retrieval_profile="recall50", top_k=5, score_threshold=0.7)

    assert cfg.top_k >= 50
    assert cfg.score_threshold == pytest.approx(0.0)


def test_chat_rag_config_coverage80_overrides_top_k_and_threshold() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(retrieval_profile="coverage80", top_k=5, score_threshold=0.7)

    assert cfg.top_k >= 80
    assert cfg.score_threshold == pytest.approx(0.0)


def test_chat_rag_config_basic_mode_maps_to_production_profile() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(mode="basic", top_k=5, score_threshold=0.7)

    assert cfg.mode == "basic"
    assert cfg.retrieval_profile == "hybrid_ce"
    assert cfg.retrieval_mode == "hybrid"
    assert cfg.top_k >= 20


def test_chat_rag_config_contextual_mode_maps_to_long_context_profile() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(mode="contextual", top_k=20, score_threshold=0.7)

    assert cfg.mode == "contextual"
    assert cfg.retrieval_profile == "long_context"
    assert cfg.retrieval_mode == "hybrid"
    assert cfg.top_k == 8
    assert cfg.reranker_top_n == 4


def test_chat_rag_config_expanded_mode_maps_to_expanded_profile() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(mode="expanded", top_k=5, score_threshold=0.7)

    assert cfg.mode == "expanded"
    assert cfg.retrieval_profile == "expanded"
    assert cfg.enable_hierarchy_recall is True
    assert cfg.hierarchy_parent_depth == 1
    assert cfg.hierarchy_sibling_window == 1


def test_chat_rag_config_explicit_profile_wins_over_mode() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(mode="basic", retrieval_profile="expanded", top_k=5, score_threshold=0.7)

    assert cfg.mode == "basic"
    assert cfg.retrieval_profile == "expanded"
    assert cfg.enable_hierarchy_recall is True


def test_chat_rag_config_hybrid_ce_degrades_to_hybrid_without_reranker() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(
        retrieval_profile="hybrid_ce",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="keyword",
        enable_reranker=False,
        reranker_provider="llm",
        reranker_top_n=3,
        enable_weight_rerank=True,
    )

    assert cfg.retrieval_profile == "hybrid_ce"
    assert cfg.retrieval_mode == "hybrid"
    assert cfg.top_k >= 20
    assert cfg.score_threshold == pytest.approx(0.0)
    assert cfg.enable_reranker is False
    assert cfg.reranker_provider == "none"
    assert cfg.enable_weight_rerank is False


def test_chat_rag_config_hybrid_ce_keeps_cross_encoder_when_enabled() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(
        retrieval_profile="hybrid_ce",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="keyword",
        enable_reranker=True,
        reranker_provider="llm",
        reranker_top_n=3,
        enable_weight_rerank=True,
    )

    assert cfg.retrieval_profile == "hybrid_ce"
    assert cfg.enable_reranker is True
    assert cfg.reranker_provider == "cross_encoder"
    assert cfg.reranker_top_n >= 20


def test_grounded_strict_profile_contract_enforces_strict_evidence_defaults() -> None:
    from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides

    applied = apply_retrieval_profile_overrides(
        profile="grounded_strict",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="keyword",
        enable_reranker=False,
        reranker_provider="llm",
        reranker_top_n=3,
        enable_weight_rerank=True,
        retrieval_contract_mode="",
        visible_evidence_only=False,
    )

    assert applied["retrieval_profile"] == "grounded_strict"
    assert applied["retrieval_mode"] == "hybrid"
    assert applied["top_k"] >= 20
    assert applied["score_threshold"] == pytest.approx(0.0)
    assert applied["enable_reranker"] is True
    assert applied["reranker_provider"] == "cross_encoder"
    assert applied["reranker_top_n"] >= 20
    assert applied["enable_weight_rerank"] is False
    assert applied["retrieval_contract_mode"] == "evidence_strict"
    assert applied["visible_evidence_only"] is True


def test_hierarchy_recall20_profile_enables_hierarchy_overlay_contract() -> None:
    from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides, is_recall_first_profile

    applied = apply_retrieval_profile_overrides(
        profile="hierarchy_recall20",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="keyword",
        enable_reranker=False,
        reranker_provider="llm",
        reranker_top_n=3,
        enable_weight_rerank=True,
        retrieval_contract_mode="",
        visible_evidence_only=False,
    )

    assert applied["retrieval_profile"] == "hierarchy_recall20"
    assert applied["top_k"] >= 20
    assert applied["score_threshold"] == pytest.approx(0.0)
    assert applied["enable_hierarchy_recall"] is True
    assert applied["hierarchy_family_collapse"] is True
    assert applied["hierarchy_family_aggregation"] == "combined"
    assert applied["hierarchy_tree_dedup"] is True
    assert applied["hierarchy_parent_depth"] == 0
    assert applied["hierarchy_sibling_window"] == 0
    assert applied["hierarchy_overfetch_factor"] == 4
    assert is_recall_first_profile("hierarchy_recall20") is True


def test_hierarchy_recall20_expand_profile_enables_default_context_expansion() -> None:
    from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides, is_recall_first_profile

    applied = apply_retrieval_profile_overrides(
        profile="hierarchy_recall20_expand",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="keyword",
        enable_reranker=False,
        reranker_provider="llm",
        reranker_top_n=3,
        enable_weight_rerank=True,
        retrieval_contract_mode="",
        visible_evidence_only=False,
    )

    assert applied["retrieval_profile"] == "hierarchy_recall20_expand"
    assert applied["top_k"] >= 20
    assert applied["score_threshold"] == pytest.approx(0.0)
    assert applied["enable_hierarchy_recall"] is True
    assert applied["hierarchy_family_collapse"] is True
    assert applied["hierarchy_family_aggregation"] == "combined"
    assert applied["hierarchy_tree_dedup"] is True
    assert applied["hierarchy_parent_depth"] == 1
    assert applied["hierarchy_sibling_window"] == 1
    assert applied["hierarchy_overfetch_factor"] == 4
    assert is_recall_first_profile("hierarchy_recall20_expand") is True


def test_expanded_profile_maps_to_default_expansion_preset() -> None:
    from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides, is_recall_first_profile

    applied = apply_retrieval_profile_overrides(
        profile="expanded",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="keyword",
        enable_reranker=False,
        reranker_provider="llm",
        reranker_top_n=3,
        enable_weight_rerank=True,
        retrieval_contract_mode="",
        visible_evidence_only=False,
    )

    assert applied["retrieval_profile"] == "expanded"
    assert applied["top_k"] >= 20
    assert applied["score_threshold"] == pytest.approx(0.0)
    assert applied["enable_hierarchy_recall"] is True
    assert applied["hierarchy_family_collapse"] is True
    assert applied["hierarchy_tree_dedup"] is True
    assert applied["hierarchy_parent_depth"] == 1
    assert applied["hierarchy_sibling_window"] == 1
    assert applied["hierarchy_overfetch_factor"] == 4
    assert applied["context_neighbor_window"] == 2
    assert applied["context_neighbor_max_added"] == 24
    assert applied["context_neighbor_score_driven"] is True
    assert applied["context_neighbor_high_span"] == 2
    assert applied["context_neighbor_mid_span"] == 1
    assert is_recall_first_profile("expanded") is True


def test_chat_rag_config_accepts_request_level_kg_boost_controls() -> None:
    from app.api.schemas.chat import ChatRAGConfig
    from app.rag.pipelines.langgraph import build_rag_state

    cfg = ChatRAGConfig(
        enable_kg_chunk_injection=True,
        kg_chunk_injection_max_chunks=7,
        enable_kg_chunk_boost=True,
        kg_chunk_boost_weight=0.35,
        kg_chunk_boost_max_promoted=2,
        enable_kg_query_expansion=True,
    )

    state = build_rag_state(
        question="q",
        document_ids=[],
        top_k=5,
        score_threshold=0.0,
        retrieval_mode="hybrid",
        enable_kg_chunk_injection=cfg.enable_kg_chunk_injection,
        kg_chunk_injection_max_chunks=cfg.kg_chunk_injection_max_chunks,
        enable_kg_chunk_boost=cfg.enable_kg_chunk_boost,
        kg_chunk_boost_weight=cfg.kg_chunk_boost_weight,
        kg_chunk_boost_max_promoted=cfg.kg_chunk_boost_max_promoted,
        enable_kg_query_expansion=cfg.enable_kg_query_expansion,
    )

    assert state["enable_kg_chunk_injection"] is True
    assert state["kg_chunk_injection_max_chunks"] == 7
    assert state["enable_kg_chunk_boost"] is True
    assert state["kg_chunk_boost_weight"] == 0.35
    assert state["kg_chunk_boost_max_promoted"] == 2
    assert state["enable_kg_query_expansion"] is True


def test_rag_state_preserves_multi_dataset_scope_for_kg() -> None:
    from uuid import uuid4

    from app.rag.pipelines.langgraph import build_rag_state

    dataset_a = uuid4()
    dataset_b = uuid4()

    state = build_rag_state(
        question="q",
        dataset_ids=[dataset_a, dataset_b],
        top_k=5,
        score_threshold=0.0,
        retrieval_mode="hybrid",
        enable_kg_chunk_injection=True,
        enable_kg_query_expansion=True,
    )

    assert state["dataset_id"] is None
    assert state["dataset_ids"] == [dataset_a, dataset_b]


def test_hierarchy_hybrid_ce_profile_keeps_hierarchy_overlay_without_reranker() -> None:
    from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides

    applied = apply_retrieval_profile_overrides(
        profile="hierarchy_hybrid_ce",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="keyword",
        enable_reranker=False,
        reranker_provider="llm",
        reranker_top_n=3,
        enable_weight_rerank=True,
        retrieval_contract_mode="",
        visible_evidence_only=False,
    )

    assert applied["retrieval_profile"] == "hierarchy_hybrid_ce"
    assert applied["retrieval_mode"] == "hybrid"
    assert applied["top_k"] >= 20
    assert applied["score_threshold"] == pytest.approx(0.0)
    assert applied["enable_reranker"] is False
    assert applied["reranker_provider"] == "none"
    assert applied["enable_weight_rerank"] is False
    assert applied["enable_hierarchy_recall"] is True
    assert applied["hierarchy_family_collapse"] is True
    assert applied["hierarchy_family_aggregation"] == "combined"
    assert applied["hierarchy_tree_dedup"] is True


def test_hierarchy_hybrid_ce_profile_keeps_cross_encoder_when_enabled() -> None:
    from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides

    applied = apply_retrieval_profile_overrides(
        profile="hierarchy_hybrid_ce",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="keyword",
        enable_reranker=True,
        reranker_provider="llm",
        reranker_top_n=3,
        enable_weight_rerank=True,
        retrieval_contract_mode="",
        visible_evidence_only=False,
    )

    assert applied["retrieval_profile"] == "hierarchy_hybrid_ce"
    assert applied["enable_reranker"] is True
    assert applied["reranker_provider"] == "cross_encoder"
    assert applied["reranker_top_n"] >= 20


def test_hierarchy_grounded_strict_profile_combines_strict_grounding_with_hierarchy_overlay() -> None:
    from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides

    applied = apply_retrieval_profile_overrides(
        profile="hierarchy_grounded_strict",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="keyword",
        enable_reranker=False,
        reranker_provider="llm",
        reranker_top_n=3,
        enable_weight_rerank=True,
        retrieval_contract_mode="",
        visible_evidence_only=False,
    )

    assert applied["retrieval_profile"] == "hierarchy_grounded_strict"
    assert applied["retrieval_mode"] == "hybrid"
    assert applied["top_k"] >= 20
    assert applied["score_threshold"] == pytest.approx(0.0)
    assert applied["enable_reranker"] is True
    assert applied["reranker_provider"] == "cross_encoder"
    assert applied["reranker_top_n"] >= 20
    assert applied["enable_weight_rerank"] is False
    assert applied["retrieval_contract_mode"] == "evidence_strict"
    assert applied["visible_evidence_only"] is True
    assert applied["enable_hierarchy_recall"] is True
    assert applied["hierarchy_family_collapse"] is True
    assert applied["hierarchy_family_aggregation"] == "combined"
    assert applied["hierarchy_tree_dedup"] is True


def test_dataset_rag_defaults_persists_retrieval_profile() -> None:
    from app.api.schemas.dataset import DatasetRAGDefaults

    d = DatasetRAGDefaults(retrieval_profile="recall20")
    dumped = d.model_dump(exclude_none=True)

    assert dumped.get("retrieval_profile") == "recall20"


def test_long_context_profile_prefers_small_top_k_and_rerank_budget() -> None:
    from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides

    applied = apply_retrieval_profile_overrides(
        profile="long_context",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="keyword",
        enable_reranker=True,
        reranker_provider="llm",
        reranker_top_n=20,
        enable_weight_rerank=True,
        retrieval_contract_mode="",
        visible_evidence_only=False,
    )

    assert applied["retrieval_profile"] == "long_context"
    assert applied["top_k"] == 8
    assert applied["reranker_top_n"] == 4
    assert applied["retrieval_mode"] == "hybrid"
    assert applied["score_threshold"] == pytest.approx(0.0)
    assert applied["enable_reranker"] is True
    assert applied["reranker_provider"] == "long_context"
    assert applied["enable_weight_rerank"] is False
