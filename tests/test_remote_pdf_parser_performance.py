from __future__ import annotations

from scripts.remote_pdf_parser_performance import classify_result


def test_classify_result_rejects_advanced_backend_fallback_to_basic():
    summary = {"backend": "basic", "markdown_chars": 10000}

    assert classify_result(200, summary, "marker", 5000) == "resolved_backend_mismatch:basic"


def test_classify_result_accepts_matching_backend():
    summary = {"backend": "etl4llm", "markdown_chars": 10000}

    assert classify_result(200, summary, "etl4llm", 5000) == "ok"


def test_classify_result_allows_auto_resolution():
    summary = {"backend": "basic", "markdown_chars": 10000}

    assert classify_result(200, summary, "auto", 5000) == "ok"
