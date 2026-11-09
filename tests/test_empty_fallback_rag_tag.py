import json

import pytest
from langchain_core.documents import Document

from app.rag.core.citations import build_citations_from_docs


@pytest.mark.parametrize("missing", ["table_id", "sql"])
def test_tag_citation_requires_fields_emitted_by_the_table_payload_builder(missing):
    payload = {"kind": "tag_table_store", "table_id": "table-1", "sql": "SELECT value FROM data"}
    payload.pop(missing)
    document = Document(
        page_content=json.dumps(payload),
        metadata={"retrieval_role": "tag", "table_id": "table-1"},
    )
    with pytest.raises(KeyError, match=missing):
        build_citations_from_docs([document], retrieval_elapsed_sec=0.0, retrieval_mode="hybrid")


def test_tag_citation_does_not_fabricate_identity_when_both_sources_are_absent():
    document = Document(page_content="Truncated TAG payload", metadata={"retrieval_role": "tag"})
    with pytest.raises((AttributeError, TypeError)):
        build_citations_from_docs([document], retrieval_elapsed_sec=0.0, retrieval_mode="hybrid")


def test_tag_citation_keeps_supplied_scalar_join_identifiers():
    document = Document(
        page_content=json.dumps({"kind": "tag_table_store", "table_id": "table-1", "sql": "SELECT 1"}),
        metadata={"retrieval_role": "tag", "table_id": "table-1", "join_table_ids": [None, 0, False, "table-1"]},
    )
    result = build_citations_from_docs([document], retrieval_elapsed_sec=0.0, retrieval_mode="hybrid")
    assert result[0]["join_table_ids"] == ["0", "False", "table-1"]
