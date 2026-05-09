from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_hierarchical_tools_expose_pageindex_style_document_structure_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.tools.hierarchical_retrieval_tools as mod

    monkeypatch.setattr(
        mod,
        "get_document",
        lambda document_id, dataset_id=None, account_id=None: {  # noqa: ARG005
            "document_id": document_id,
            "dataset_id": dataset_id,
            "filename": "annual-report.pdf",
        },
        raising=True,
    )
    monkeypatch.setattr(
        mod,
        "get_document_structure",
        lambda document_id, dataset_id=None, account_id=None, max_nodes=200: {  # noqa: ARG005
            "schema": "mimirq.document_structure.v1",
            "document": {"document_id": document_id},
            "nodes": [{"title": "Risk Factors"}],
        },
        raising=True,
    )
    monkeypatch.setattr(
        mod,
        "get_page_content",
        lambda document_id, pages, dataset_id=None, account_id=None, max_chars=50_000: {  # noqa: ARG005
            "document_id": document_id,
            "pages": [7, 8],
            "content": "risk text",
        },
        raising=True,
    )

    info = await mod.document_info(document_id="doc-1", dataset_id="ds-1", account_id="acct")
    structure = await mod.document_structure(document_id="doc-1", dataset_id="ds-1", account_id="acct")
    page = await mod.page_content(document_id="doc-1", pages="7-8", dataset_id="ds-1", account_id="acct")

    assert info["filename"] == "annual-report.pdf"
    assert structure["nodes"][0]["title"] == "Risk Factors"
    assert page["content"] == "risk text"
