from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document


def test_compute_faithfulness_score_claim_support_ratio() -> None:
    from app.rag.core.faithfulness import compute_faithfulness_score

    out = compute_faithfulness_score(
        answer="Sky is blue. Bananas are red.",
        evidence_text="The sky is blue due to Rayleigh scattering.",
        max_claims=24,
    )
    assert out.get("score") == pytest.approx(0.5)
    assert int(out.get("supported_claims") or 0) == 1
    assert int(out.get("total_claims") or 0) == 2
    unsupported = out.get("unsupported_claims") or []
    assert any("Bananas are red" in str(x) for x in unsupported)


def test_render_sentence_citations_markdown_outputs_rows() -> None:
    from app.rag.core.sentence_citations import render_sentence_citations_markdown

    md, count = render_sentence_citations_markdown(
        [
            {
                "claim": "Sky is blue.",
                "evidence": [{"document_id": "d1", "chunk_id": "c1", "page_number": 3}],
            }
        ],
        max_items=8,
        max_evidence_per_claim=2,
    )
    assert count == 1
    assert "### Sentence Citations" in md
    assert "Sky is blue." in md
    assert "doc:d1" in md and "chunk:c1" in md


def test_render_sentence_citations_inline_uses_numbered_markers() -> None:
    from app.rag.core.sentence_citations import render_sentence_citations_inline

    text, count = render_sentence_citations_inline(
        [{"claim": "Sky is blue.", "evidence": [{"document_id": "d1", "chunk_id": "c1"}]}]
    )

    assert count == 1
    assert "[1]" in text
    assert "doc:d1" not in text


@pytest.mark.asyncio
async def test_engine_metrics_include_faithfulness_and_sentence_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_CLAIM_CHECK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SHOW_IMAGE_IN_ANSWER", False, raising=False)

    monkeypatch.setattr(settings, "FAITHFULNESS_SCORE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "FAITHFULNESS_SCORE_MAX_CLAIMS", 24, raising=False)
    monkeypatch.setattr(settings, "FAITHFULNESS_SCORE_MAX_EVIDENCE_CHARS", 24000, raising=False)
    monkeypatch.setattr(settings, "SENTENCE_CITATIONS_INLINE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SENTENCE_CITATIONS_INLINE_MAX_ITEMS", 8, raising=False)
    monkeypatch.setattr(settings, "SENTENCE_CITATIONS_INLINE_MAX_EVIDENCE_PER_CLAIM", 2, raising=False)

    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "Sky is blue. Bananas are red.", raising=False)

    class _Retriever:
        _last_debug_metrics = {}

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, _q):  # noqa: ANN001
            return [
                Document(
                    page_content="The sky is blue due to Rayleigh scattering.",
                    metadata={"source": "doc.txt", "page": 1, "score": 0.9},
                    id=str(uuid.uuid4()),
                )
            ]

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _Retriever(), raising=True)

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question="Why is sky blue?",
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
    parts: list[str] = []
    async for item in agen:
        if item.get("type") == "token":
            parts.append(str((item.get("data") or {}).get("content") or ""))
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    full_response = "".join(parts)
    metrics = done_metrics or {}
    assert metrics.get("faithfulness_score_enabled") is True
    assert metrics.get("faithfulness_score") == pytest.approx(0.5)
    assert metrics.get("confidence_score") == pytest.approx(0.6)
    assert int(metrics.get("faithfulness_supported_claims") or 0) == 1
    assert int(metrics.get("faithfulness_total_claims") or 0) == 2
    assert int(metrics.get("sentence_citations_count") or 0) >= 2
    assert metrics.get("sentence_citations_inline_enabled") is True
    assert metrics.get("sentence_citations_inline_used") is True
    assert int(metrics.get("sentence_citations_inline_count") or 0) >= 1
    assert "### Sentence Citations" in full_response

    sentence_citations = metrics.get("sentence_citations") or []
    assert isinstance(sentence_citations, list) and sentence_citations
    assert any("Bananas are red" in str(x.get("claim") or "") for x in sentence_citations if isinstance(x, dict))


def test_langgraph_build_context_preserves_extract_evidence_text_after_denoise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.pipelines.langgraph as lg_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, 'RAG_CONTEXT_EVIDENCE_ENABLED', True, raising=False)
    monkeypatch.setattr(lg_mod, 'extract_evidence_text', lambda *_args, **_kwargs: 'EVIDENCE ONLY')

    out = lg_mod._build_context(
        [
            Document(
                page_content='The sky is blue due to Rayleigh scattering. Additional filler.',
                metadata={'source': 'doc.txt', 'page': 1},
                id=str(uuid.uuid4()),
            )
        ],
        query='Why is the sky blue?',
    )

    assert 'EVIDENCE ONLY' in out


def test_langgraph_generate_node_includes_faithfulness_and_sentence_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    import app.rag.pipelines.langgraph as lg_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    monkeypatch.setattr(settings, "RAG_CLAIM_CHECK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SHOW_IMAGE_IN_ANSWER", False, raising=False)
    monkeypatch.setattr(settings, "FAITHFULNESS_SCORE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SENTENCE_CITATIONS_INLINE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "Sky is blue. Bananas are red.", raising=False)

    out = lg_mod._generate_node(
        {
            "question": "Why is sky blue?",
            "history": [],
            "docs": [
                Document(
                    page_content="The sky is blue due to Rayleigh scattering.",
                    metadata={"source": "doc.txt", "page": 1},
                    id=str(uuid.uuid4()),
                )
            ],
            "citations": [],
            "metrics": {"iterative_pass_gap": {"has_gap": False, "severity": "none"}},
            "structured_output": False,
            "visible_evidence_only": False,
        }
    )
    metrics = out.get("metrics") or {}
    assert metrics.get("faithfulness_score_enabled") is True
    assert metrics.get("faithfulness_score") == pytest.approx(0.5)
    assert metrics.get("confidence_score") == pytest.approx(0.6)
    assert int(metrics.get("faithfulness_supported_claims") or 0) == 1
    assert int(metrics.get("faithfulness_total_claims") or 0) == 2
    assert int(metrics.get("sentence_citations_count") or 0) >= 2
    assert metrics.get("sentence_citations_inline_enabled") is True
    assert metrics.get("sentence_citations_inline_used") is True
    assert int(metrics.get("sentence_citations_inline_count") or 0) >= 1
    assert "### Sentence Citations" in str(out.get("answer") or "")


def test_langgraph_appended_markdown_is_pii_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Regression test: LangGraph pipeline appends Markdown blocks (images + sentence citations).
    These must go through the same PII redaction gate as the base answer text.
    """
    import app.rag.engine as engine_mod
    import app.rag.pipelines.langgraph as lg_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    monkeypatch.setattr(settings, "PII_REDACTION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PII_REDACTION_MASK", "[REDACTED]", raising=False)

    monkeypatch.setattr(settings, "RAG_CLAIM_CHECK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "FAITHFULNESS_SCORE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SENTENCE_CITATIONS_INLINE_ENABLED", True, raising=False)

    monkeypatch.setattr(settings, "SHOW_IMAGE_IN_ANSWER", True, raising=False)
    monkeypatch.setattr(settings, "IMAGE_APPEND_MAX", 5, raising=False)

    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "Sky is blue.", raising=False)

    out = lg_mod._generate_node(
        {
            "question": "Why is sky blue?",
            "history": [],
            "docs": [
                Document(
                    page_content="Sky is blue due to Rayleigh scattering.",
                    metadata={"document_id": "alice@example.com", "source": "doc.txt", "page": 1},
                    id=str(uuid.uuid4()),
                )
            ],
            "citations": [{"has_image": True, "img_url": "https://example.com/?u=alice@example.com"}],
            "metrics": {},
            "structured_output": False,
            "visible_evidence_only": False,
        }
    )

    answer = str(out.get("answer") or "")
    assert "alice@example.com" not in answer
    assert "[REDACTED]" in answer
