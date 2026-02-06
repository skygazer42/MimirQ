from __future__ import annotations

import uuid

import pytest


def test_split_into_claims_splits_sentences() -> None:
    from app.rag.core.text import split_into_claims

    text = "Alpha is here. Beta is there!\nGamma?"
    assert split_into_claims(text) == ["Alpha is here.", "Beta is there!", "Gamma?"]


def test_split_into_claims_splits_markdown_lists() -> None:
    from app.rag.core.text import split_into_claims

    text = "- First item\n- Second item\n\nAfter."
    assert split_into_claims(text) == ["First item", "Second item", "After."]


def test_split_into_claims_is_bounded_by_max_claims() -> None:
    from app.rag.core.text import split_into_claims

    text = "- one\n- two\n- three"
    assert split_into_claims(text, max_claims=2) == ["one", "two"]


def test_is_claim_supported_accepts_overlap() -> None:
    from app.rag.core.text import is_claim_supported

    evidence = "The sky is blue due to Rayleigh scattering."
    assert is_claim_supported("Sky is blue.", evidence) is True


def test_is_claim_supported_rejects_no_overlap() -> None:
    from app.rag.core.text import is_claim_supported

    evidence = "The sky is blue due to Rayleigh scattering."
    assert is_claim_supported("Bananas are red.", evidence) is False


def test_is_claim_supported_always_keeps_uncertainty_phrasing() -> None:
    from app.rag.core.text import is_claim_supported

    assert is_claim_supported("Unable to answer this question based on the available materials.", "") is True
    assert is_claim_supported("证据不足，无法根据现有材料确定。", "") is True


@pytest.mark.asyncio
async def test_rag_engine_claim_check_removes_unsupported_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    # Keep the test deterministic / single-query.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    # Use a deterministic fake LLM.
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "Sky is blue. Bananas are red.", raising=False)

    monkeypatch.setattr(settings, "RAG_CLAIM_CHECK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_CLAIM_CHECK_MAX_CLAIMS", 24, raising=False)

    from langchain_core.documents import Document

    class _CapturingRetriever:
        _last_debug_metrics = {}

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, _q):  # noqa: ANN001
            return [
                Document(
                    page_content="The sky is blue due to Rayleigh scattering.",
                    metadata={"source": "doc.txt", "page": 1},
                    id=str(uuid.uuid4()),
                )
            ]

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _CapturingRetriever(), raising=True)

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question="Why is the sky blue?",
        history=None,
        conversation_id=None,
        tenant_id=uuid.uuid4(),
        document_ids=None,
        account_id="u",
        top_k=1,
        score_threshold=0.0,
        retrieval_mode="vector",
        db=None,
    )

    parts: list[str] = []
    done_metrics = None
    async for item in agen:
        if item.get("type") == "token":
            data = item.get("data") or {}
            parts.append(str(data.get("content") or ""))
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    full_response = "".join(parts)
    assert "Sky is blue" in full_response
    assert "Bananas" not in full_response
    assert (done_metrics or {}).get("claim_check_removed") == 1
