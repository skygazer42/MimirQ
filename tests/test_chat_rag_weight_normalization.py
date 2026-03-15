from __future__ import annotations

import pytest


def test_chat_rag_config_normalizes_weights_when_enabled() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(enable_weight_rerank=True, vector_weight=0.7, keyword_weight=0.7)
    assert round(cfg.vector_weight, 4) == pytest.approx(0.5)
    assert round(cfg.keyword_weight, 4) == pytest.approx(0.5)


def test_chat_rag_config_rejects_zero_sum_weights() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    with pytest.raises(ValueError):
        ChatRAGConfig(enable_weight_rerank=True, vector_weight=0.0, keyword_weight=0.0)


def test_chat_rag_config_does_not_normalize_when_disabled() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(enable_weight_rerank=False, vector_weight=0.7, keyword_weight=0.7)
    assert cfg.vector_weight == pytest.approx(0.7)
    assert cfg.keyword_weight == pytest.approx(0.7)
