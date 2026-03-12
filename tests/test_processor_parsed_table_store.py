from __future__ import annotations

import uuid
from types import SimpleNamespace

from langchain_core.documents import Document


def test_processor_imports_parsed_table_segments_to_table_store(monkeypatch, tmp_path):  # noqa: ANN001
    """
    Parsed PDFs may emit table segments (`content_type=table`). When table_store is enabled,
    we should import those markdown tables into the per-document Table Store and persist
    doc_metadata.table_store so TAG endpoints + chat bridge can use them.
    """
    from app.core.config import settings
    from app.parsing.processors.processor import DocumentProcessorService
    from app.services.table_store import table_store_path

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    monkeypatch.setattr(settings, "TABLE_STORE_DIR", str(tmp_path / "table_store"), raising=False)

    class _DB:
        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    class _DBDoc:
        def __init__(self) -> None:
            self.id = document_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.doc_metadata = {}

    db_doc = _DBDoc()

    docs = [
        Document(
            page_content="\n".join(
                [
                    "| a | b |",
                    "| --- | --- |",
                    "| 1 | 2 |",
                    "| 3 | 4 |",
                ]
            ),
            metadata={"content_type": "table", "page": 1},
        )
    ]

    pipeline = SimpleNamespace(
        table_store_enabled=True,
        table_store_max_rows=0,
        table_store_max_cols=0,
        table_store_sample_rows=0,
    )

    svc = DocumentProcessorService()
    imported = svc._import_parsed_markdown_tables_to_store(  # type: ignore[attr-defined]
        _DB(),
        db_document=db_doc,
        tenant_id=tenant_id,
        documents=docs,
        pipeline_effective=pipeline,
    )
    assert imported == 1

    store = (db_doc.doc_metadata or {}).get("table_store")
    assert isinstance(store, dict)
    routing = store.get("routing")
    assert isinstance(routing, dict)
    assert routing.get("kind") == "tag_sidecar"
    assert routing.get("source") == "parser_table_segments"
    tables = store.get("tables")
    assert isinstance(tables, list)
    assert len(tables) == 1
    assert tables[0]["table_id"] == f"doc:{document_id}:sheet:0"
    assert tables[0]["routing_kind"] == "tag_sidecar"
    assert tables[0]["routing_source"] == "parser_table_segment"

    db_path = table_store_path(tenant_id=tenant_id, dataset_id=dataset_id, document_id=document_id)
    assert db_path.exists()
