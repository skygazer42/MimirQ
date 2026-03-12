def test_chat_rag_config_recall20_overrides_top_k_and_threshold() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(retrieval_profile="recall20", top_k=5, score_threshold=0.7)

    assert cfg.top_k >= 20
    assert cfg.score_threshold == 0.0


def test_chat_rag_config_recall50_overrides_top_k_and_threshold() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(retrieval_profile="recall50", top_k=5, score_threshold=0.7)

    assert cfg.top_k >= 50
    assert cfg.score_threshold == 0.0


def test_chat_rag_config_coverage80_overrides_top_k_and_threshold() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(retrieval_profile="coverage80", top_k=5, score_threshold=0.7)

    assert cfg.top_k >= 80
    assert cfg.score_threshold == 0.0


def test_chat_rag_config_hybrid_ce_enables_cross_encoder_baseline() -> None:
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
    assert cfg.score_threshold == 0.0
    assert cfg.enable_reranker is True
    assert cfg.reranker_provider == "cross_encoder"
    assert cfg.reranker_top_n >= 20
    assert cfg.enable_weight_rerank is False


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
    assert applied["score_threshold"] == 0.0
    assert applied["enable_reranker"] is True
    assert applied["reranker_provider"] == "cross_encoder"
    assert applied["reranker_top_n"] >= 20
    assert applied["enable_weight_rerank"] is False
    assert applied["retrieval_contract_mode"] == "evidence_strict"
    assert applied["visible_evidence_only"] is True


def test_dataset_rag_defaults_persists_retrieval_profile() -> None:
    from app.api.schemas.dataset import DatasetRAGDefaults

    d = DatasetRAGDefaults(retrieval_profile="recall20")
    dumped = d.model_dump(exclude_none=True)

    assert dumped.get("retrieval_profile") == "recall20"
