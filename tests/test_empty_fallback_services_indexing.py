from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from app.services.indexer import Indexer
from app.services.indexing.vector_writer import _prepare_shadow_vector_items
from app.services.lotus_bridge import _invoke_sem_filter_batch


@pytest.mark.parametrize("content", [None, 0])
def test_semantic_filter_rejects_a_response_without_the_required_text_interface(content):
    llm = SimpleNamespace(invoke=lambda messages: SimpleNamespace(content=content))
    with pytest.raises(AttributeError, match="text"):
        _invoke_sem_filter_batch(
            llm=llm, system=SystemMessage(content="Return booleans"), instr="keep", cols=["value"], chunk=[{"value": 0}]
        )


def test_semantic_filter_reads_a_valid_langchain_text_block():
    llm = SimpleNamespace(invoke=lambda messages: AIMessage(content=[{"type": "text", "text": "[true]"}]))
    assert _invoke_sem_filter_batch(
        llm=llm, system=SystemMessage(content="Return booleans"), instr="keep", cols=["value"], chunk=[{"value": 0}]
    ) == [True]


def test_document_vector_payload_requires_the_chunk_content():
    with pytest.raises(KeyError, match="content"):
        Indexer._document_vector_item(None, doc={"metadata": {}}, document_id=uuid4(), tenant_id=uuid4(), index=0)


def test_shadow_vector_payload_requires_the_chunk_content():
    with pytest.raises(KeyError, match="content"):
        _prepare_shadow_vector_items([{"metadata": {"chunk_id": str(uuid4())}}], shadow_space="shadow")
