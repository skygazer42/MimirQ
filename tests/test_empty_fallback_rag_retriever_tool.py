import pytest

from app.rag.agents.prebuilt import create_retriever_tool


@pytest.mark.parametrize("key", ["content", "page_content"])
def test_retriever_tool_formats_both_supported_document_shapes(key):
    tool = create_retriever_tool(lambda query: [{key: "Retrieved text."}])
    assert "Retrieved text." in tool.invoke({"query": "question"})


def test_retriever_tool_exposes_a_missing_required_text_variant():
    tool = create_retriever_tool(lambda query: [{"metadata": {"source": "document"}}])
    with pytest.raises(KeyError, match="page_content"):
        tool.invoke({"query": "question"})


def test_retriever_tool_does_not_return_store_errors_as_successful_text():
    def unavailable(query):
        raise RuntimeError("authoritative retrieval unavailable")

    tool = create_retriever_tool(unavailable)
    with pytest.raises(RuntimeError, match="authoritative retrieval unavailable"):
        tool.invoke({"query": "question"})
