from __future__ import annotations

import sys
import uuid
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from langchain_core.documents import Document


def _load_rag_agent_module():
    import langchain

    if not hasattr(langchain, "debug"):
        langchain.debug = False
    if not hasattr(langchain, "verbose"):
        langchain.verbose = False
    if not hasattr(langchain, "llm_cache"):
        langchain.llm_cache = None

    base = Path(__file__).resolve().parents[1]
    src = base / "app" / "rag" / "agents" / "rag_agent.py"
    name = "agentic_self_rag_module"
    spec = spec_from_file_location(name, src)
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_agentic_runner_emits_self_rag_metrics_after_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    rag_agent_mod = _load_rag_agent_module()
    agentic_plan_step = rag_agent_mod.AgenticPlanStep
    agentic_rag_runner = rag_agent_mod.AgenticRAGRunner

    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "Use the MQTT keepalive value from the broker connection settings.", raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "RAG_SELF_RAG_ENABLED", True, raising=False)

    engine = RAGEngine()
    runner = agentic_rag_runner(engine=engine)

    async def _fake_plan(*_args, **_kwargs):  # noqa: ANN003
        return [agentic_plan_step(query="focused retrieval query", rationale="Need one grounded answer.")]

    monkeypatch.setattr(runner, "_plan", _fake_plan, raising=True)
    monkeypatch.setattr(
        rag_agent_mod,
        "build_rag_state",
        lambda **_kwargs: {"question": "focused retrieval query", "history": [], "top_k": 3},
        raising=True,
    )
    monkeypatch.setattr(
        rag_agent_mod,
        "run_retrieval",
        lambda _state: {
            "docs": [
                Document(
                    page_content="Use the MQTT keepalive value from the broker connection settings.",
                    metadata={"document_id": "doc-1", "chunk_id": "chunk-1", "page": 1, "source": "guide.md"},
                )
            ],
            "citations": [{"document_id": "doc-1", "chunk_id": "chunk-1", "page_number": 1, "relevance_score": 0.9}],
            "metrics": {"retrieval_mode": "vector", "top_relevance_score": 0.9},
            "abstain_triggered": False,
            "abstain_reason": None,
        },
        raising=True,
    )

    events: list[dict[str, object]] = []
    agen = runner.stream(
        question="How do I configure MQTT keepalive?",
        history=[],
        conversation_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        dataset_id=uuid.uuid4(),
        top_k=3,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="agentic-self-rag-test",
    )

    async for event in agen:
        events.append(event)
        if event.get("type") == "done":
            break

    done_metrics = (events[-1].get("data") or {}).get("metrics") or {}
    assert done_metrics.get("agentic_self_rag_used") is True
    assert done_metrics.get("agentic_self_rag_verdict") == "accept"
    assert done_metrics.get("agentic_self_rag_need_retrieval") is False
