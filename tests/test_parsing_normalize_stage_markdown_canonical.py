from __future__ import annotations

from langchain_core.documents import Document


def test_normalize_stage_applies_markdown_canonicalization() -> None:
    from app.parsing.processors.processor import NormalizeStage

    stage = NormalizeStage()
    docs = [Document(page_content="##Heading\n*  item\n", metadata={})]

    out = stage.run(items=docs)
    assert len(out) == 1
    assert (out[0].page_content or "") == "## Heading\n- item"

    meta = dict(out[0].metadata or {})
    assert meta.get("text_normalized") is True
    assert meta.get("markdown_canonicalized") is True
    assert meta.get("markdown_canonical_changed") is True
