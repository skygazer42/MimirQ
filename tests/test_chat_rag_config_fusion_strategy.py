from __future__ import annotations

import pytest

from app.api.schemas.chat import ChatRAGConfig


def test_chat_rag_config_normalizes_fusion_strategy_aliases() -> None:
    c1 = ChatRAGConfig(fusion_strategy="reciprocal_rank_fusion")
    assert c1.fusion_strategy == "rrf"

    c2 = ChatRAGConfig(fusion_strategy="budget_rrf")
    assert c2.fusion_strategy == "budgeted_rrf"


def test_chat_rag_config_rejects_invalid_fusion_budget_keys() -> None:
    with pytest.raises(ValueError):
        ChatRAGConfig(
            fusion_strategy="budgeted_rrf",
            fusion_budgets={"vector": 10, "unknown": 1},
        )


def test_chat_rag_config_rejects_invalid_fusion_min_scores() -> None:
    with pytest.raises(ValueError):
        ChatRAGConfig(
            fusion_strategy="budgeted_rrf",
            fusion_min_scores={"lexical": 1.5},
        )


def test_chat_rag_config_accepts_weighted_fusion_strategy_and_weights() -> None:
    c = ChatRAGConfig(
        fusion_strategy="weighted",
        fusion_weights={"vector": 0.7, "bm25": 0.3},
    )
    assert c.fusion_strategy == "weighted"
    assert c.fusion_weights == {"vector": 0.7, "bm25": 0.3}


def test_chat_rag_config_rejects_invalid_fusion_weight_keys() -> None:
    with pytest.raises(ValueError):
        ChatRAGConfig(
            fusion_strategy="weighted",
            fusion_weights={"unknown": 0.1},
        )


def test_chat_rag_config_rejects_invalid_fusion_weight_values() -> None:
    with pytest.raises(ValueError):
        ChatRAGConfig(
            fusion_strategy="weighted",
            fusion_weights={"vector": -0.1},
        )
    with pytest.raises(ValueError):
        ChatRAGConfig(
            fusion_strategy="weighted",
            fusion_weights={"bm25": 1.5},
        )
