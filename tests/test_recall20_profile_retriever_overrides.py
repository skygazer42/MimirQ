import uuid

import pytest


@pytest.mark.asyncio
async def test_rag_engine_recall20_profile_disables_result_trimming(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "OK", raising=False)

    captured_updates: list[dict] = []

    class _CapturingRetriever:
        _last_debug_metrics = {}

        def model_copy(self, **kwargs):  # noqa: ANN001, ANN002, ANN003
            captured_updates.append(dict((kwargs or {}).get("update") or {}))
            return self

        def invoke(self, _q):  # noqa: ANN001
            return []

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _CapturingRetriever(), raising=True)

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question="What fields does the orders table have?",
        history=None,
        conversation_id=None,
        tenant_id=uuid.uuid4(),
        document_ids=None,
        account_id="u",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="hybrid",
        retrieval_profile="recall20",
        db=None,
    )

    async for item in agen:
        if item.get("type") == "done":
            break
    await agen.aclose()

    update = captured_updates[0]
    assert update.get("dedup_enabled") is False
    assert update.get("max_chunks_per_doc") == 0
    assert update.get("max_chunks_per_page") == 0
    assert update.get("min_distinct_docs") == 0


def test_langgraph_recall20_profile_disables_result_trimming(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    # Keep the test deterministic / single-query.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)

    # Use a deterministic fake LLM.
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "OK", raising=False)

    captured_updates: list[dict] = []

    class _CapturingRetriever:
        _last_debug_metrics = {}

        def model_copy(self, **kwargs):  # noqa: ANN001, ANN002, ANN003
            captured_updates.append(dict((kwargs or {}).get("update") or {}))
            return self

    def invoke(self, _q):  # noqa: ANN001
        return []

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _CapturingRetriever(), raising=True)

    state = lg_mod.build_rag_state(
        question="What fields does the orders table have?",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="u",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="hybrid",
        retrieval_profile="recall20",
        db=None,
    )

    lg_mod._retrieve_node(state)

    update = captured_updates[0]
    assert update.get("dedup_enabled") is False
    assert update.get("max_chunks_per_doc") == 0
    assert update.get("max_chunks_per_page") == 0
    assert update.get("min_distinct_docs") == 0


def test_langgraph_hierarchy_recall20_profile_wires_hierarchy_family_overfetch(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)

    captured_updates: list[dict] = []

    class _CapturingRetriever:
        _last_debug_metrics = {}

        def model_copy(self, **kwargs):  # noqa: ANN001, ANN002, ANN003
            captured_updates.append(dict((kwargs or {}).get("update") or {}))
            return self

    def invoke(self, _q):  # noqa: ANN001
        return []

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _CapturingRetriever(), raising=True)

    state = lg_mod.build_rag_state(
        question="What fields does the orders table have?",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="u",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="hybrid",
        retrieval_profile="hierarchy_recall20",
        db=None,
    )

    lg_mod._retrieve_node(state)

    update = captured_updates[0]
    assert update.get("retrieval_profile") == "hierarchy_recall20"
    assert update.get("enable_hierarchy_recall") is True
    assert update.get("hierarchy_family_collapse") is True
    assert update.get("hierarchy_overfetch_factor") == 4
