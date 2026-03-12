from __future__ import annotations

import pytest


def test_chat_rag_config_normalizes_retrieval_contract_mode_alias() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(retrieval_contract_mode=" deterministic ")
    assert cfg.retrieval_contract_mode == "deterministic_recall"


def test_chat_rag_config_rejects_unknown_retrieval_contract_mode() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    with pytest.raises(ValueError):
        ChatRAGConfig(retrieval_contract_mode="bad_mode")

