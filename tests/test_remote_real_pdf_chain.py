from __future__ import annotations

from scripts.remote_real_pdf_chain import (
    DEFAULT_CHAT_QUESTIONS,
    DEFAULT_KG_QUERIES,
    DOCUMENT_CHUNK_LIST_LIMIT,
    effective_questions,
    list_count,
    parsed_text_from_response,
)


def test_remote_real_pdf_chain_list_count_handles_common_shapes() -> None:
    assert list_count([1, 2, 3]) == 3
    assert list_count({"items": [1, 2]}) == 2
    assert list_count({"chunks": [1]}) == 1
    assert list_count({"results": [1, 2, 3, 4]}) == 4
    assert list_count({"count": 9}) == 9
    assert list_count({"total": 7}) == 7
    assert list_count({}) == 0


def test_remote_real_pdf_chain_parsed_text_prefers_markdown_fields() -> None:
    assert parsed_text_from_response({"markdown_content": "md"}) == "md"
    assert parsed_text_from_response({"content": "body"}) == "body"
    assert parsed_text_from_response({"text": "plain"}) == "plain"
    assert parsed_text_from_response({"original_markdown_content": "orig"}) == "orig"
    assert parsed_text_from_response("raw") == "raw"
    assert parsed_text_from_response({"foo": "bar"}) == ""


def test_remote_real_pdf_chain_uses_document_chunk_api_limit() -> None:
    assert DOCUMENT_CHUNK_LIST_LIMIT == 2000


def test_remote_real_pdf_chain_effective_questions_prefers_cli_values() -> None:
    assert effective_questions(["  A  ", "", "B"], ["fallback"]) == ["A", "B"]


def test_remote_real_pdf_chain_effective_questions_falls_back_to_defaults() -> None:
    assert effective_questions([], DEFAULT_KG_QUERIES) == DEFAULT_KG_QUERIES
    assert effective_questions(None, DEFAULT_CHAT_QUESTIONS) == DEFAULT_CHAT_QUESTIONS
