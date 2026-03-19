from __future__ import annotations

from app.parsing.processors.vlm_correction import maybe_correct_markdown_pages


def test_vlm_correction_disabled_is_noop() -> None:
    pages = ["hello", "world"]
    out, audit = maybe_correct_markdown_pages(pages, enabled=False, api_url="http://example.invalid")
    assert out == pages
    assert audit.applied is False
    assert audit.changed is False


def test_vlm_correction_missing_url_is_noop() -> None:
    pages = ["hello"]
    out, audit = maybe_correct_markdown_pages(pages, enabled=True, api_url="")
    assert out == pages
    assert audit.applied is False
    assert audit.error == "missing_api_url"


def test_vlm_correction_no_eligible_pages() -> None:
    out, audit = maybe_correct_markdown_pages([], enabled=True, api_url="http://example.invalid")
    assert out == []
    assert audit.applied is False
    assert audit.error in {"no_pages_eligible", "missing_api_url"}

