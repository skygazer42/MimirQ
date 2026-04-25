from __future__ import annotations

from pathlib import Path


def test_colpali_parser_emits_visual_reference_for_pdf(tmp_path: Path) -> None:
    from app.parsing.parsers.colpali_parser import ColPaliParser

    pdf = tmp_path / "visual.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    docs = ColPaliParser().parse(pdf)

    assert len(docs) == 1
    doc = docs[0]
    assert "[visual-document](visual.pdf)" in (doc.page_content or "")
    meta = doc.metadata or {}
    assert meta.get("parser_backend") == "colpali"
    assert meta.get("content_type") == "visual_document"


def test_colpali_parser_emits_image_reference_for_image(tmp_path: Path) -> None:
    from app.parsing.parsers.colpali_parser import ColPaliParser

    img = tmp_path / "visual sample.png"
    img.write_bytes(b"not-real")

    docs = ColPaliParser().parse(img)

    assert len(docs) == 1
    assert "visual%20sample.png" in (docs[0].page_content or "")
