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
        "row_source": {
            "table": "demo.sales",
            "sync_token": "tok-sales-v1",
            "pk_hashes": ["pkhash-1", "pkhash-2"],
        },
        "schema_link": {
            "score": 0.78,
            "strategy": "column_overlap",
            "reason": "matched_columns",
            "matched_columns": ["amount"],
            "matched_values": [],
            "matched_tables": ["sheet_0"],
        },
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
                "schema_link_score": 0.78,
                "schema_link_strategy": "column_overlap",
                "row_source_table": "demo.sales",
                "row_source_sync_token": "tok-sales-v1",
                "row_source_pk_hashes": ["pkhash-1", "pkhash-2"],
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
    assert float(c0.get("tag_schema_link_score") or 0.0) == 0.78
    assert str(c0.get("tag_schema_link_strategy") or "") == "column_overlap"
    assert str(c0.get("row_source_table") or "") == "demo.sales"
    assert str(c0.get("row_source_sync_token") or "") == "tok-sales-v1"
    assert list(c0.get("row_source_pk_hashes") or []) == ["pkhash-1", "pkhash-2"]

    # TAG citations should expose UUID-like chunk_id for schema compatibility.
    cid = str(c0.get("chunk_id") or "")
    assert cid
    uuid.UUID(cid)


def test_tag_citation_includes_join_provenance() -> None:
    doc_id = uuid.uuid4()
    table_orders = f"doc:{doc_id}:sheet:0"
    table_users = f"doc:{doc_id}:sheet:1"
    payload = {
        "kind": "tag_table_store",
        "document": "sales.xlsx",
        "table_id": table_orders,
        "sheet_index": 0,
        "sheet_name": "orders",
        "sql": (
            'SELECT u."region", SUM(o."amount") AS total '
            'FROM "sheet_0" AS o JOIN "sheet_1" AS u ON o."user_id" = u."id" '
            'GROUP BY u."region" LIMIT 10'
        ),
        "columns": ["region", "total"],
        "rows": [["APAC", 100.0]],
        "truncated": False,
        "join_provenance": [
            {
                "left_table": "sheet_0",
                "left_column": "user_id",
                "right_table": "sheet_1",
                "right_column": "id",
                "confidence": 0.95,
                "reason": "fk_to_id",
            }
        ],
        "join_table_ids": [table_orders, table_users],
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
                "table_id": table_orders,
                "join_provenance": payload["join_provenance"],
                "join_table_ids": payload["join_table_ids"],
                "score": 1.0,
                "retrieval_score": 1.0,
            },
        )
    ]

    citations = build_citations_from_docs(
        docs,
        retrieval_elapsed_sec=0.1,
        retrieval_mode="hybrid",
        query="按 region 统计订单金额前10",
    )
    assert len(citations) == 1
    c0 = citations[0]
    assert isinstance(c0.get("join_provenance"), list)
    assert list(c0.get("join_table_ids") or []) == [table_orders, table_users]
