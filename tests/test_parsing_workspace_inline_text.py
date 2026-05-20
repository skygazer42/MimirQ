from __future__ import annotations

import uuid


def test_workspace_text_preview_uses_inline_markdown_parser(tmp_path):
    import app.api.v1.parsing as parsing_module

    source = tmp_path / "sample.md"
    source.write_text("# Enterprise Telemetry\n\nUpload path smoke test.", encoding="utf-8")

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()

    parsed = parsing_module._parse_inline_text_preview(
        source_path=source,
        resolved_backend="markdown",
        tenant_id=tenant_id,
        document_id=document_id,
        requested_backend="auto",
    )

    assert parsed["resolved_backend"] == "markdown"
    assert parsed["pdf_quality"] is None
    assert parsed["documents"][0]["page_content"].startswith("# Enterprise Telemetry")
    assert parsed["documents"][0]["metadata"]["parser_backend"] == "markdown"
    assert parsed["provenance"]["execution_mode"] == "inline_text_preview"


def test_workspace_preview_inline_parse_only_for_text_like_files():
    import app.api.v1.parsing as parsing_module

    assert parsing_module._should_inline_preview_parse(".md") is True
    assert parsing_module._should_inline_preview_parse(".txt") is True
    assert parsing_module._should_inline_preview_parse(".py") is True
    assert parsing_module._should_inline_preview_parse(".pdf") is False
    assert parsing_module._should_inline_preview_parse(".docx") is False
