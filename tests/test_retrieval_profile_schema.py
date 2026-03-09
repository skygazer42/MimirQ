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


def test_dataset_rag_defaults_persists_retrieval_profile() -> None:
    from app.api.schemas.dataset import DatasetRAGDefaults

    d = DatasetRAGDefaults(retrieval_profile="recall20")
    dumped = d.model_dump(exclude_none=True)

    assert dumped.get("retrieval_profile") == "recall20"
