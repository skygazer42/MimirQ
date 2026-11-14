from app.services.evidence_item_import import parse_qa_faq_import_bytes


def test_evidence_jsonl_import_keeps_zero_tags_and_source_values():
    items, errors = parse_qa_faq_import_bytes(
        raw=b'{"query": "zero", "tags": [0], "source_metadata": 0}\n', filename="faq.jsonl"
    )
    assert not errors
    assert items[0]["tags"] == ["0"]
    assert items[0]["source_metadata"] == {"source": "0"}
