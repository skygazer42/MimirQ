from __future__ import annotations

import uuid

from langchain_core.documents import Document

from app.rag.core.citations import build_citations_from_docs


def test_build_citations_from_docs_includes_clean_docx_url_from_metadata_or_docx_source() -> None:
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    citations = build_citations_from_docs(
        [
            Document(
                page_content="配置步骤如下。",
                id=str(chunk_id),
                metadata={
                    "document_id": str(doc_id),
                    "source": "配置手册.docx",
                    "page": 2,
                },
            )
        ],
        retrieval_elapsed_sec=0.1,
        retrieval_mode="hybrid",
        query="怎么配置",
    )

    assert citations[0]["clean_docx_url"] == f"/api/v1/documents/{doc_id}/clean-docx"
