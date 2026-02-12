from __future__ import annotations


def test_parse_qa_faq_import_csv_basic() -> None:
    from app.services.evidence_item_import import parse_qa_faq_import_bytes

    raw = (
        "query,expected_answer,tags,source_url\n"
        "What is MimirQ?,A RAG system,a;b,https://example.com\n"
    ).encode("utf-8")

    items, errors = parse_qa_faq_import_bytes(raw=raw, filename="qa.csv", max_items=100)

    assert errors == []
    assert len(items) == 1
    assert items[0]["query"] == "What is MimirQ?"
    assert items[0]["expected_answer"] == "A RAG system"
    assert items[0]["tags"] == ["a", "b"]
    assert items[0]["source_metadata"]["source_url"] == "https://example.com"


def test_parse_qa_faq_import_jsonl_with_errors_and_aliases() -> None:
    from app.services.evidence_item_import import parse_qa_faq_import_bytes

    raw = (
        '{"query":"q1","expected_answer":"a1","tags":["t1"],"source":"kb"}\n'
        "notjson\n"
        '{"question":"q2","answer":"a2","tags":"x,y","foo":1}\n'
    ).encode("utf-8")

    items, errors = parse_qa_faq_import_bytes(raw=raw, filename="qa.jsonl", max_items=100)

    assert len(items) == 2
    assert len(errors) == 1
    assert errors[0]["line"] == 2

    assert items[0]["query"] == "q1"
    assert items[0]["expected_answer"] == "a1"
    assert items[0]["tags"] == ["t1"]
    assert items[0]["source_metadata"].get("source") == "kb"

    assert items[1]["query"] == "q2"
    assert items[1]["expected_answer"] == "a2"
    assert items[1]["tags"] == ["x", "y"]
    assert items[1]["source_metadata"].get("foo") == 1


def test_plan_evidence_item_import_dedupes_existing_and_batch() -> None:
    from app.services.evidence_item_import import plan_evidence_item_import

    items = [
        {"query": " q1  ", "expected_answer": None, "tags": [], "source_metadata": {}},
        {"query": "q1", "expected_answer": None, "tags": ["t"], "source_metadata": {}},
        {"query": "q2", "expected_answer": None, "tags": [], "source_metadata": {}},
    ]
    plan = plan_evidence_item_import(existing_queries={"q2"}, items=items, max_items=100)

    assert plan["created"] == 1
    assert plan["skipped"] == 2
    assert len(plan["errors"]) == 1
    assert plan["errors"][0]["error"] == "duplicate query in import batch"
    assert plan["create_items"][0]["query"] == "q1"

