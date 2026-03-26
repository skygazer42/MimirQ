from __future__ import annotations

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.core.context_denoise import compress_context_docs_with_llm, denoise_context_docs


def test_denoise_context_docs_reorders_for_lost_in_middle_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RAG_CONTEXT_LOST_IN_MIDDLE_REORDER_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_TOKEN_BUDGET_TRIM_ENABLED", False, raising=False)

    docs = [
        Document(page_content="chunk one", metadata={"source": "s1"}),
        Document(page_content="chunk two", metadata={"source": "s2"}),
        Document(page_content="chunk three", metadata={"source": "s3"}),
        Document(page_content="chunk four", metadata={"source": "s4"}),
        Document(page_content="chunk five", metadata={"source": "s5"}),
    ]

    out = denoise_context_docs(docs)
    assert [str((d.metadata or {}).get("source") or "") for d in out] == ["s1", "s3", "s5", "s4", "s2"]


def test_denoise_context_docs_trims_to_token_budget_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RAG_CONTEXT_LOST_IN_MIDDLE_REORDER_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_TOKEN_BUDGET_TRIM_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_DENOISE_MAX_TOTAL_TOKENS", 8, raising=False)

    monkeypatch.setattr(
        "app.rag.core.context_denoise.num_tokens_from_string",
        lambda text: len([t for t in str(text).split(" ") if t]),
    )

    docs = [
        Document(page_content="a b c d", metadata={"source": "s1"}),
        Document(page_content="e f g", metadata={"source": "s2"}),
        Document(page_content="h i j k", metadata={"source": "s3"}),
    ]

    out = denoise_context_docs(docs)
    assert [str((d.metadata or {}).get("source") or "") for d in out] == ["s1", "s2"]


def test_compress_context_docs_with_llm_uses_query_aware_helper(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RAG_CONTEXT_LLM_COMPRESSION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_LLM_COMPRESSION_TARGET_RATIO", 0.4, raising=False)

    captured: list[tuple[str, str, float]] = []

    def _fake_compress(*, text: str, query: str, target_ratio: float) -> str:
        captured.append((text, query, target_ratio))
        return f"compressed::{query}"

    monkeypatch.setattr("app.rag.core.context_denoise._compress_text_with_llm", _fake_compress)

    docs = [Document(page_content="original context", metadata={"source": "s1"})]
    out = compress_context_docs_with_llm(docs, query="focus this")

    assert captured == [("original context", "focus this", 0.4)]
    assert [doc.page_content for doc in out] == ["compressed::focus this"]
