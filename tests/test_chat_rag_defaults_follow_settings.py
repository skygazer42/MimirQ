from __future__ import annotations


def test_chat_rag_config_defaults_follow_system_settings(monkeypatch):  # noqa: ANN001
    from app.api.schemas.chat import ChatRAGConfig
    from app.core.config import settings

    monkeypatch.setattr(settings, "RETRIEVAL_TOP_K", 11, raising=False)
    monkeypatch.setattr(settings, "SIMILARITY_THRESHOLD", 0.33, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_MMR_LAMBDA", 0.25, raising=False)
    monkeypatch.setattr(settings, "ENABLE_RERANKER", True, raising=False)
    monkeypatch.setattr(settings, "RERANKER_PROVIDER", "llm", raising=False)
    monkeypatch.setattr(settings, "RERANKER_TOP_N", 17, raising=False)

    cfg = ChatRAGConfig()
    assert cfg.top_k == 11
    assert abs(cfg.score_threshold - 0.33) < 1e-6
    assert abs(cfg.mmr_lambda - 0.25) < 1e-6
    assert cfg.enable_reranker is True
    assert cfg.reranker_provider == "llm"
    assert cfg.reranker_top_n == 17

