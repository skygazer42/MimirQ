from __future__ import annotations

import uuid

import pytest


def test_extract_evidence_text_keeps_matching_sentences() -> None:
    from app.rag.core.text import extract_evidence_text

    raw = "Alpha is here. Beta is unrelated. Zebra appears here."
    out = extract_evidence_text(raw, "zebra", max_sentences=1, min_sentence_chars=0)

    assert "Zebra" in out
    assert "Beta" not in out


def test_extract_evidence_text_falls_back_when_no_match() -> None:
    from app.rag.core.text import extract_evidence_text

    raw = "Alpha is here. Beta is unrelated."
    out = extract_evidence_text(raw, "notpresent", max_sentences=1, min_sentence_chars=0)

    assert "Alpha" in out


def test_extract_evidence_text_is_bounded_by_max_chars() -> None:
    from app.rag.core.text import extract_evidence_text

    raw = "Alpha is here. Beta is unrelated. Zebra appears here."
    out = extract_evidence_text(raw, "zebra", max_sentences=3, min_sentence_chars=0, max_chars=10)

    assert len(out) <= 13
    assert out.endswith("...")


@pytest.mark.asyncio
async def test_rag_engine_context_evidence_extraction_is_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    log_records = []

    def _log_metrics(payload):  # noqa: ANN001
        log_records.append(payload)

    monkeypatch.setattr(engine_mod, "log_metrics", _log_metrics, raising=True)

    # Keep the test deterministic / single-query.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    # Use a deterministic fake LLM.
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "OK", raising=False)

    monkeypatch.setattr(settings, "RAG_CONTEXT_EVIDENCE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK", 2, raising=False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS", 0, raising=False)

    def _boom(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError("boom")

    monkeypatch.setattr(engine_mod, "extract_evidence_text", _boom, raising=True)

    from langchain_core.documents import Document

    class _CapturingRetriever:
        _last_debug_metrics = {}

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, _q):  # noqa: ANN001
            return [
                Document(
                    page_content="Alpha is here. Zebra appears here.",
                    metadata={"source": "doc.txt", "page": 1},
                    id=str(uuid.uuid4()),
                )
            ]

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _CapturingRetriever(), raising=True)

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question="zebra?",
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

    done_metrics = None
    async for item in agen:
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    assert done_metrics.get("context_evidence_enabled") is True
    rag_trace = next(r for r in log_records if r.get("event") == "rag_trace")
    assert bool((rag_trace.get("context_evidence") or {}).get("enabled"))
