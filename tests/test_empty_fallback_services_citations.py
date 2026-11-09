from types import SimpleNamespace

import pytest

from app.services import chat_execution_runtime, chat_persistence


@pytest.mark.parametrize("citation,error", [
    ({"document_name": "Guide"}, KeyError),
    ({"document_name": "Guide", "chunk_content": None}, AttributeError),
    ({"document_name": "Guide", "chunk_content": 0}, AttributeError),
])
def test_extractive_answer_exposes_invalid_live_citation_content(citation, error):
    with pytest.raises(error):
        chat_execution_runtime.build_extractive_fallback_answer(question="What is stated?", citations=[citation])


def test_retrieval_document_without_required_content_does_not_become_none_text():
    with pytest.raises(AttributeError):
        chat_execution_runtime._answer_evidence_from_retrieval(
            docs=[SimpleNamespace(metadata={}, page_content=None)], citations=[], max_items=4,
        )


def test_online_evaluation_requires_the_live_citation_content_key():
    with pytest.raises(KeyError, match="chunk_content"):
        chat_persistence._online_eval_contexts([{"document_name": "Guide"}])


def test_legitimate_empty_live_citation_remains_empty_evidence():
    answer = chat_execution_runtime.build_extractive_fallback_answer(
        question="What is stated?", citations=[{"document_name": "Guide", "chunk_content": ""}]
    )
    assert "没有找到可用于回答的引用证据" in answer
    assert chat_persistence._online_eval_contexts([{"document_name": "Guide", "chunk_content": ""}]) == []
