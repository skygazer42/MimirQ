import pytest

from app.rag.retrieval.orchestration.query_invocation import (
    QueryInvocationRecordInput,
    RetrievalPerQueryItemInput,
    build_query_invocation_record,
    build_retrieval_per_query_item,
    format_retrieval_error,
)


def test_build_retrieval_per_query_item_includes_counts_and_optional_hop() -> None:
    item = build_retrieval_per_query_item(
        RetrievalPerQueryItemInput(
            kind="contextual_followup",
            query="follow up query",
            elapsed_sec=0.1237,
            ok=True,
            retriever_debug={"channels": {"attempted_channels": ["vector"]}},
            hop=2,
        )
    )

    assert item == {
        "kind": "contextual_followup",
        "hop": 2,
        "query_chars": 15,
        "query_tokens": 3,
        "elapsed_sec": 0.124,
        "ok": True,
        "retriever_debug": {"channels": {"attempted_channels": ["vector"]}},
    }


def test_format_retrieval_error_truncates_message_to_contract_limit() -> None:
    message = "x" * 300
    formatted = format_retrieval_error("hard_fallback", message)

    assert formatted == f"hard_fallback:{'x' * 160}"


def test_build_query_invocation_record_packages_item_error_and_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.orchestration import query_invocation

    monkeypatch.setattr(query_invocation, "num_tokens_from_string", lambda text: len(text.split()))
    docs = ["doc-a", "doc-b"]
    record = build_query_invocation_record(
        QueryInvocationRecordInput(
            kind="subq",
            query="sub question",
            docs=docs,
            error="timeout after retries",
            elapsed_sec=0.456,
            retriever_debug={"channels": {"successful_channels": []}},
        )
    )

    assert record.kind == "subq"
    assert record.docs == docs
    assert record.per_query_item == {
        "kind": "subq",
        "query_chars": 12,
        "query_tokens": 2,
        "elapsed_sec": 0.456,
        "ok": False,
        "retriever_debug": {"channels": {"successful_channels": []}},
    }
    assert record.error_entry == "subq:timeout after retries"
