from __future__ import annotations

import json
import uuid

from langchain_core.documents import Document

from app.rag.core.citations import build_citations_from_docs


def test_tag_citation_includes_stable_traceability_keys() -> None:
    doc_id = uuid.uuid4()
    table_id = f"doc:{doc_id}:sheet:0"
    payload = {
        "kind": "tag_table_store",
        "document": "sales.xlsx",
        "table_id": table_id,
        "sheet_index": 0,
        "sheet_name": "Sales",
        "sql": 'SELECT COUNT(*) AS count FROM "sheet_0" LIMIT 1',
        "columns": ["count"],
        "rows": [[42]],
        "truncated": False,
        "sql_generation_mode": "deterministic",
    }
    docs = [
        Document(
            page_content=json.dumps(payload, ensure_ascii=False),
            id="tag-non-uuid-id",
            metadata={
                "retrieval_role": "tag",
                "chunk_role": "tag_sql_result",
                "document_id": str(doc_id),
                "source": "sales.xlsx",
                "table_id": table_id,
                "sheet_index": 0,
                "sheet_name": "Sales",
                "sql_generation_mode": "deterministic",
                "score": 1.0,
                "retrieval_score": 1.0,
            },
        )
    ]

    citations = build_citations_from_docs(
        docs,
        retrieval_elapsed_sec=0.1,
        retrieval_mode="hybrid",
        query="总数多少",
    )
    assert len(citations) == 1

    c0 = citations[0]
    assert str(c0.get("document_name") or "") == "sales.xlsx"
    assert str(c0.get("table_id") or "") == table_id
    assert c0.get("sheet_index") == 0
    assert str(c0.get("sheet_name") or "") == "Sales"
    assert str(c0.get("sql_generation_mode") or "") == "deterministic"

    # TAG citations should expose UUID-like chunk_id for schema compatibility.
    cid = str(c0.get("chunk_id") or "")
    assert cid
    uuid.UUID(cid)
