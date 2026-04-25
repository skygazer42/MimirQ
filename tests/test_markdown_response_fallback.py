from __future__ import annotations


def test_extract_markdown_response_text_prefers_markdown_then_output() -> None:
    from app.parsing.utils.markdown_response import extract_markdown_response_text

    assert extract_markdown_response_text({"markdown": "## primary", "output": "secondary"}) == "## primary"
    assert extract_markdown_response_text({"format": "markdown", "output": "## fallback"}) == "## fallback"


def test_extract_markdown_response_text_recurses_into_nested_data_and_result() -> None:
    from app.parsing.utils.markdown_response import extract_markdown_response_text

    nested = {
        "code": 0,
        "data": {
            "result": {
                "content": "# nested markdown",
            }
        },
    }

    assert extract_markdown_response_text(nested) == "# nested markdown"
