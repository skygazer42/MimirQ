from __future__ import annotations

import json
import uuid

from langchain_core.documents import Document


def test_tag_table_store_citations_are_schema_compatible_and_readable() -> None:
    """
    Regression: TAG-injected table_store context docs must still produce citations that:
    - validate against the ChatResponse Citation schema (UUID chunk_id/document_id),
    - render human-readable citation snippets (not raw JSON blobs).
    """
    from app.api.schemas.chat import Citation as CitationSchema
    from app.rag.core.citations import build_citations_from_docs

    doc_id = uuid.uuid4()
    table_id = f"doc:{doc_id}:sheet:0"
    payload = {
        "kind": "tag_table_store",
        "document": "sales.xlsx",
        "table_id": table_id,
        "sheet_index": 0,
        "sheet_name": "Sales",
        "row_count": 10,
        "col_count": 2,
        "sql": 'SELECT "amount","region" FROM "sheet_0" LIMIT 5',
        "columns": ["amount", "region"],
        "rows": [[1, "EU"], [2, "US"]],
        "truncated": False,
    }

    tag_doc = Document(
        page_content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        metadata={
            "document_id": doc_id,
            "source": "sales.xlsx",
            "retrieval_role": "tag",
            "chunk_strategy": "tag",
            "chunk_role": "tag_sql_result",
            "table_id": table_id,
            "sheet_index": 0,
            "sheet_name": "Sales",
            "score": 1.0,
            "retrieval_score": 1.0,
        },
        # Historically this was a non-UUID (e.g. "tag:<table_id>"), which broke schema validation.
        id=f"tag:{table_id}",
    )

    citations = build_citations_from_docs(
        [tag_doc],
        retrieval_elapsed_sec=0.1,
        retrieval_mode="hybrid",
        query="统计一下这张表里 amount 的总数",
    )
    assert len(citations) == 1

    # Must validate (chunk_id/document_id are UUIDs).
    CitationSchema.model_validate(citations[0])

    # Snippet should be readable, not a raw JSON blob.
    content = str(citations[0].get("chunk_content") or "")
    assert content
    assert not content.lstrip().startswith("{")
    assert ("SQL" in content) or ("SELECT" in content)

