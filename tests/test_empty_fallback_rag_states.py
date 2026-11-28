import asyncio
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.documents import Document

from app.rag.agents import rag_agent
from app.rag.runtime.streaming.generation import _render_vision_messages
from app.rag.runtime.streaming.retrieval import _kg_document_from_chunk, inject_kg_chunks
from app.rag.runtime.streaming.state import StandardStreamState


def test_agent_request_requires_its_question_key():
    with pytest.raises(KeyError, match="question"):
        rag_agent.resolve_agentic_stream_request(request=None, legacy_overrides={})


@pytest.mark.parametrize("data,expected", [(None, None), (0, "[Tool: echo]\n0"), (False, "[Tool: echo]\nFalse")])
def test_tool_context_preserves_absence_and_supplied_scalar_values(data, expected):
    assert rag_agent.AgenticRAGRunner._format_tool_context("echo", data) == expected


def test_vision_message_requires_its_content_attribute():
    template = SimpleNamespace(format_messages=lambda **kwargs: [SimpleNamespace(type="human")])
    runtime = StandardStreamState(
        engine=None,
        payload={"current_prompt_template": template, "generation_inputs": {}},
    )
    with pytest.raises(AttributeError, match="content"):
        _render_vision_messages(runtime)


@pytest.mark.parametrize("missing", ["id", "document_id", "content"])
def test_kg_chunk_projection_requires_persisted_row_fields(missing):
    fields = {
        "id": uuid4(),
        "document_id": uuid4(),
        "content": "Stored chunk.",
        "doc_metadata": {},
        "chunk_index": 0,
        "page_number": 0,
        "start_char": 0,
        "end_char": 7,
    }
    fields.pop(missing)
    runtime = StandardStreamState(engine=None, payload={"score_by_chunk": {}})
    with pytest.raises(AttributeError, match=missing):
        _kg_document_from_chunk(runtime, uuid4(), SimpleNamespace(**fields))


def test_corrective_retrieval_requires_its_context_block(monkeypatch):
    monkeypatch.setattr(rag_agent.settings, "RAG_CRAG_STREAMING_ENABLED", True)

    async def incomplete_corrective_result(**kwargs):
        return {"used": True}

    monkeypatch.setattr(rag_agent, "run_crag_streaming", incomplete_corrective_result)
    runner = rag_agent.AgenticRAGRunner.__new__(rag_agent.AgenticRAGRunner)
    with pytest.raises(KeyError, match="context_block"):
        asyncio.run(
            runner._maybe_run_crag(
                question="Question?",
                retrieval_query="Question?",
                retrieval_result={},
                state=rag_agent._AgenticRetrievalState(),
            )
        )


@pytest.mark.parametrize("failure", ["database", "row_contract"])
def test_kg_injection_exposes_authoritative_chunk_failures(monkeypatch, caplog, failure):
    from app.rag.runtime.streaming import retrieval as standard_stream_retrieval

    monkeypatch.setattr(standard_stream_retrieval.settings, "KG_ENABLED", True)
    monkeypatch.setattr(standard_stream_retrieval.settings, "KG_CHAT_ENABLED", True)
    chunk_id = uuid4()

    def fetch_chunks(**kwargs):
        if failure == "database":
            raise RuntimeError("authoritative chunk read failed")
        return [
            SimpleNamespace(
                id=chunk_id,
                content="Stored chunk.",
                doc_metadata={},
                chunk_index=0,
                page_number=0,
                start_char=0,
                end_char=7,
            )
        ]

    monkeypatch.setattr(
        standard_stream_retrieval,
        "_resolve_kg_scope",
        lambda state: (state["document_ids"], state["dataset_id"], state["dataset_ids"]),
    )
    monkeypatch.setattr(standard_stream_retrieval, "_fetch_document_chunks_for_kg_injection", fetch_chunks)
    main_document = Document(page_content="main evidence", id="main")
    runtime = StandardStreamState(
        engine=None,
        payload={
            "document_ids": None,
            "dataset_id": uuid4(),
            "dataset_ids": None,
            "tenant_id": uuid4(),
            "account_id": "account-1",
            "db": object(),
            "kg_chunk_injection_enabled": True,
            "question": "Question?",
            "query_for_retrieval": "Question?",
            "kg_result_cached": {"events": [{"chunk_id": str(chunk_id), "score": 1.0}]},
            "kg_chunk_injection_max_chunks_i": 1,
            "docs": [main_document],
            "kg_chunks_injected": 0,
            "kg_chunk_injection_error": None,
        },
    )
    error = RuntimeError if failure == "database" else AttributeError
    message = "authoritative chunk read failed" if failure == "database" else "document_id"
    with caplog.at_level(logging.DEBUG):
        asyncio.run(inject_kg_chunks(runtime))
    assert message in runtime.data.kg_chunk_injection_error
    assert runtime.data.docs == [main_document] and runtime.data.docs[0] is main_document
    assert runtime.data.kg_chunks_injected == 0
    assert any(record.exc_info and isinstance(record.exc_info[1], error) for record in caplog.records)
