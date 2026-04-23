from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_hierarchical_retrieval_tools_wrap_existing_document_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.tools.hierarchical_retrieval_tools as mod

    monkeypatch.setattr(
        mod,
        "search_documents",
        lambda query, top_k=5, dataset_id=None, filter=None: {  # noqa: ARG001
            "count": 1,
            "results": [{"chunk_id": "c1", "document_id": "d1", "source": "doc.txt"}],
        },
        raising=True,
    )
    monkeypatch.setattr(
        mod,
        "get_document_content",
        lambda document_id, page=None, dataset_id=None, account_id=None, max_chars=50_000: {  # noqa: ARG001
            "document_id": document_id,
            "content": "full content",
            "returned_chunks": 2,
        },
        raising=True,
    )

    keyword = await mod.keyword_search("485", dataset_id="ds-1", top_k=3)
    semantic = await mod.semantic_search("怎么配置 485", dataset_id="ds-1", top_k=5)
    chunk = await mod.chunk_read(document_id="d1", dataset_id="ds-1")

    assert keyword["count"] == 1
    assert semantic["results"][0]["chunk_id"] == "c1"
    assert chunk["document_id"] == "d1"
    assert chunk["content"] == "full content"
