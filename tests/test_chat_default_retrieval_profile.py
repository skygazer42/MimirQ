from __future__ import annotations


def test_chat_rag_config_applies_default_profile_when_omitted(monkeypatch) -> None:  # noqa: ANN001
    from app.api.schemas.chat import ChatRAGConfig
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_DEFAULT_RETRIEVAL_PROFILE", "hybrid_ce", raising=False)

    cfg = ChatRAGConfig()
    assert cfg.retrieval_profile == "hybrid_ce"
    assert cfg.retrieval_mode == "hybrid"
    assert cfg.enable_reranker is True


def test_chat_rag_config_keeps_explicit_knobs_without_forced_default_profile(monkeypatch) -> None:  # noqa: ANN001
    from app.api.schemas.chat import ChatRAGConfig
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_DEFAULT_RETRIEVAL_PROFILE", "hybrid_ce", raising=False)

    cfg = ChatRAGConfig(top_k=7, retrieval_mode="vector", enable_reranker=False, reranker_provider="llm")
    assert cfg.retrieval_profile is None
    assert cfg.top_k == 7
    assert cfg.retrieval_mode == "vector"
    assert cfg.enable_reranker is False
    assert cfg.reranker_provider == "llm"


def test_chat_rag_default_profile_can_enable_strict_visible_evidence(monkeypatch) -> None:  # noqa: ANN001
    from app.api.schemas.chat import ChatRAGConfig
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_DEFAULT_RETRIEVAL_PROFILE", "hybrid_ce", raising=False)
    monkeypatch.setattr(settings, "CHAT_DEFAULT_VISIBLE_EVIDENCE_ONLY", True, raising=False)

    cfg = ChatRAGConfig()
    assert cfg.retrieval_profile == "hybrid_ce"
    assert cfg.visible_evidence_only is True


def test_chat_rag_config_grounded_strict_projects_contract_fields() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(
        retrieval_profile="grounded_strict",
        retrieval_contract_mode="",
        visible_evidence_only=False,
    )

    assert cfg.retrieval_profile == "grounded_strict"
    assert cfg.retrieval_contract_mode == "evidence_strict"
    assert cfg.visible_evidence_only is True


def test_chat_rag_config_default_grounded_strict_projects_contract_fields(monkeypatch) -> None:  # noqa: ANN001
    from app.api.schemas.chat import ChatRAGConfig
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_DEFAULT_RETRIEVAL_PROFILE", "grounded_strict", raising=False)
    monkeypatch.setattr(settings, "CHAT_DEFAULT_VISIBLE_EVIDENCE_ONLY", False, raising=False)

    cfg = ChatRAGConfig()
    assert cfg.retrieval_profile == "grounded_strict"
    assert cfg.retrieval_contract_mode == "evidence_strict"
    assert cfg.visible_evidence_only is True
