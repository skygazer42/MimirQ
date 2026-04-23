from __future__ import annotations

import uuid

import pytest


def test_settings_has_visible_evidence_only_toggle() -> None:
    from app.core.config import settings

    assert hasattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED")


@pytest.mark.asyncio
async def test_strict_mode_abstains_when_no_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    # Keep the test deterministic / single-query.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    # Use a deterministic fake LLM (should not be called in strict abstain path).
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "SHOULD_NOT_APPEAR", raising=False)

    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_CITATIONS", 1, raising=False)

    class _EmptyRetriever:
        _last_debug_metrics = {}

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, _q):  # noqa: ANN001
            return []

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _EmptyRetriever(), raising=True)

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question="What is X?",
        history=None,
        conversation_id=None,
        tenant_id=uuid.uuid4(),
        document_ids=None,
        account_id="u",
        top_k=3,
        score_threshold=0.0,
        retrieval_mode="vector",
        db=None,
    )

    parts: list[str] = []
    done_metrics = None
    async for item in agen:
        if item.get("type") == "token":
            parts.append(str((item.get("data") or {}).get("content") or ""))
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    full_response = "".join(parts).strip()
    assert full_response == "Unable to answer this question based on the available materials."
    assert (done_metrics or {}).get("generation_elapsed_sec") == pytest.approx(0.0)
    followup = (done_metrics or {}).get("abstain_followup")
    assert isinstance(followup, dict)
    assert followup.get("type") == "refine_query"
    assert isinstance(followup.get("question"), str) and followup.get("question")
    assert followup.get("options") == []


@pytest.mark.asyncio
async def test_strict_mode_forces_claim_check(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    # Keep the test deterministic / single-query.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    # Use a deterministic fake LLM that includes one supported and one unsupported claim.
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "Sky is blue. Bananas are red.", raising=False)

    monkeypatch.setattr(settings, "RAG_CLAIM_CHECK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", True, raising=False)

    from langchain_core.documents import Document

    class _OneDocRetriever:
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

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _OneDocRetriever(), raising=True)

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
            parts.append(str((item.get("data") or {}).get("content") or ""))
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    full_response = "".join(parts)
    assert "Sky is blue" in full_response
    assert "Bananas" not in full_response
    assert (done_metrics or {}).get("claim_check_removed") == 1
    claim_evidence = (done_metrics or {}).get("claim_evidence")
    assert isinstance(claim_evidence, list) and claim_evidence
    sky = [x for x in claim_evidence if "Sky is blue" in str(x.get("claim") or "")]
    assert sky and isinstance(sky[0].get("evidence"), list) and sky[0].get("evidence")


@pytest.mark.asyncio
async def test_request_visible_evidence_only_abstains_when_no_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    # Keep the test deterministic / single-query.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    # Use a deterministic fake LLM (should not be called in strict abstain path).
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "SHOULD_NOT_APPEAR", raising=False)

    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_CITATIONS", 1, raising=False)

    class _EmptyRetriever:
        _last_debug_metrics = {}

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, _q):  # noqa: ANN001
            return []

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _EmptyRetriever(), raising=True)

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question="What is X?",
        history=None,
        conversation_id=None,
        tenant_id=uuid.uuid4(),
        document_ids=None,
        account_id="u",
        top_k=3,
        score_threshold=0.0,
        retrieval_mode="vector",
        visible_evidence_only=True,
        db=None,
    )

    parts: list[str] = []
    done_metrics = None
    async for item in agen:
        if item.get("type") == "token":
            parts.append(str((item.get("data") or {}).get("content") or ""))
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    full_response = "".join(parts).strip()
    assert full_response == "Unable to answer this question based on the available materials."
    assert (done_metrics or {}).get("abstain_triggered") is True
    assert (done_metrics or {}).get("visible_evidence_only_enabled") is True
    assert (done_metrics or {}).get("visible_evidence_only_requested") is True


@pytest.mark.asyncio
async def test_request_visible_evidence_only_scrubs_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    import json as _json

    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    # Keep the test deterministic / single-query.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    # Structured LLM output: includes one supported and one unsupported claim.
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(
        settings,
        "LLM_MOCK_RESPONSE",
        _json.dumps({"answer": "Sky is blue. Bananas are red.", "citations": []}),
        raising=False,
    )

    monkeypatch.setattr(settings, "RAG_CLAIM_CHECK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)

    from langchain_core.documents import Document

    class _OneDocRetriever:
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

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _OneDocRetriever(), raising=True)

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
        structured_output=True,
        structured_preset="summary",
        visible_evidence_only=True,
        db=None,
    )

    parts: list[str] = []
    done_metrics = None
    async for item in agen:
        if item.get("type") == "token":
            parts.append(str((item.get("data") or {}).get("content") or ""))
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    raw = "".join(parts).strip()
    payload = _json.loads(raw)
    assert isinstance(payload, dict)
    assert "Sky is blue" in str(payload.get("answer") or "")
    assert "Bananas" not in str(payload.get("answer") or "")
    assert (done_metrics or {}).get("claim_check_mode") == "structured"
    assert (done_metrics or {}).get("claim_check_removed") == 1

def test_langgraph_strict_mode_forces_claim_check(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.engine as engine_mod
    import app.rag.pipelines.langgraph as lg_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    # Use a deterministic fake LLM that includes one supported and one unsupported claim.
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "Sky is blue. Bananas are red.", raising=False)

    monkeypatch.setattr(settings, "RAG_CLAIM_CHECK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", True, raising=False)

    from langchain_core.documents import Document

    state = {
        "question": "Why is the sky blue?",
        "history": None,
        "docs": [
            Document(
                page_content="The sky is blue due to Rayleigh scattering.",
                metadata={"source": "doc.txt", "page": 1},
                id=str(uuid.uuid4()),
            )
        ],
        "citations": [],
        "structured_output": False,
        "structured_preset": None,
        "metrics": {},
    }

    out = lg_mod._generate_node(state)  # type: ignore[arg-type]
    answer = str(out.get("answer") or "")
    assert "Sky is blue" in answer
    assert "Bananas" not in answer
    metrics = out.get("metrics") or {}
    assert metrics.get("claim_check_removed") == 1
    claim_evidence = metrics.get("claim_evidence")
    assert isinstance(claim_evidence, list) and claim_evidence
    sky = [x for x in claim_evidence if "Sky is blue" in str(x.get("claim") or "")]
    assert sky and isinstance(sky[0].get("evidence"), list) and sky[0].get("evidence")


def test_langgraph_strict_mode_abstain_followup(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.engine as engine_mod
    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    # Keep the test deterministic / single-query.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    # No generation should happen, but keep LLM deterministic anyway.
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "SHOULD_NOT_APPEAR", raising=False)

    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_CITATIONS", 1, raising=False)

    class _EmptyRetriever:
        _last_debug_metrics = {}

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

    def invoke(self, _q):  # noqa: ANN001
        return []

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _EmptyRetriever(), raising=True)

    state = {
        "question": "What is X?",
        "history": None,
        "tenant_id": uuid.uuid4(),
        "document_ids": None,
        "top_k": 3,
        "score_threshold": 0.0,
        "retrieval_mode": "vector",
        "metrics": {},
    }

    out = lg_mod._retrieve_node(state)  # type: ignore[arg-type]
    assert bool(out.get("abstain_triggered")) is True
    assert out.get("abstain_reason") == "citations_lt_min"
    metrics = out.get("metrics") or {}
    followup = metrics.get("abstain_followup")
    assert isinstance(followup, dict)
    assert followup.get("type") == "refine_query"
    assert isinstance(followup.get("question"), str) and followup.get("question")
    assert followup.get("options") == []


def test_langgraph_generate_node_uses_out_of_scope_abstain_message(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.engine as engine_mod
    import app.rag.pipelines.langgraph as lg_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "SHOULD_NOT_APPEAR", raising=False)

    out = lg_mod._generate_node(
        {
            "question": "新型号 X200 怎么接线",
            "history": [],
            "docs": [],
            "citations": [],
            "abstain_triggered": True,
            "abstain_reason": "out_of_scope",
            "metrics": {"abstain_followup": {"type": "refine_query", "question": "outside the current knowledge base", "options": []}},
            "structured_output": False,
            "structured_preset": None,
        }
    )

    assert out.get("answer") == "This question appears to be outside the current knowledge base."
