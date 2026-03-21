from __future__ import annotations

from pathlib import Path

from langchain_core.documents import Document


def test_should_apply_vlm_correction_requires_enabled_and_low_table_score() -> None:
    from app.parsing.processors.vlm_correction import should_apply_vlm_correction

    assert should_apply_vlm_correction(enabled=True, pdf_quality={"table_quality_score": 0.4}, min_table_score=0.6) is True
    assert should_apply_vlm_correction(enabled=True, pdf_quality={"table_quality_score": 0.8}, min_table_score=0.6) is False
    assert should_apply_vlm_correction(enabled=False, pdf_quality={"table_quality_score": 0.4}, min_table_score=0.6) is False


def test_apply_vlm_correction_updates_selected_pages(monkeypatch, tmp_path: Path) -> None:
    from app.parsing.processors import vlm_correction as mod

    docs = [
        Document(page_content="page one markdown", metadata={"page": 1}),
        Document(page_content="page two markdown", metadata={"page": 2}),
    ]

    monkeypatch.setattr(mod, "_render_pdf_page_png", lambda file_path, page_number: b"png", raising=True)
    monkeypatch.setattr(
        mod,
        "_correct_markdown_with_vision",
        lambda *, markdown, image_bytes: f"corrected::{markdown}",
        raising=True,
    )

    corrected, meta = mod.apply_vlm_correction(
        documents=docs,
        file_path=tmp_path / "sample.pdf",
        max_pages=1,
    )

    assert corrected[0].page_content == "corrected::page one markdown"
    assert corrected[1].page_content == "page two markdown"
    assert meta["applied_pages"] == [1]
