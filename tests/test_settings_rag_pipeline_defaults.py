def test_zero_corrective_faithfulness_threshold_does_not_retry(monkeypatch):
    from app.rag.pipelines import langgraph

    monkeypatch.setattr(langgraph.settings, "RAG_CORRECTIVE_ENABLED", True)
    monkeypatch.setattr(langgraph.settings, "RAG_CORRECTIVE_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(langgraph.settings, "RAG_CORRECTIVE_MIN_FAITHFULNESS_SCORE", 0.0)
    calls = []

    def retrieve(state):
        calls.append("retrieve")
        return state

    def generate(state):
        return {**state, "metrics": {**state.get("metrics", {}), "faithfulness_score": 0.0}}

    result = langgraph._run_corrective_loop({}, retrieve_fn=retrieve, generate_fn=generate)
    assert calls == ["retrieve"]
    assert len(result["metrics"]["corrective_attempts"]) == 1


def test_zero_agent_reflection_threshold_is_preserved(monkeypatch):
    from app.rag.agents.rag_agent import AgenticRAGRunner, settings

    monkeypatch.setattr(settings, "RAG_AGENTIC_REFLECT_TOP_SCORE_MIN", 0.0)
    result = {"citations": [], "metrics": {"top_relevance_score": 0.0}}
    assert AgenticRAGRunner._is_sufficient(result) is True
