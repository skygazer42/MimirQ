from __future__ import annotations

from pathlib import Path


def test_precheck_pdf_text_sample_dependency_missing(monkeypatch, tmp_path: Path):
    import app.services.dataset_precheck_scan_runner as mod

    monkeypatch.setattr(mod, "_get_pdfplumber", lambda: None)
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    _text, _estimated, _page_count, _per_page_chars, err = mod._pdf_text_sample(p, sample_pages=1)
    assert err
    assert str(err).startswith("dependency_missing:pdfplumber")


def test_precheck_xlsx_stats_dependency_missing(monkeypatch, tmp_path: Path):
    import app.services.dataset_precheck_scan_runner as mod

    monkeypatch.setattr(mod, "_get_openpyxl", lambda: None)
    p = tmp_path / "a.xlsx"
    p.write_bytes(b"not a real xlsx")
    stats, err = mod._xlsx_spreadsheet_stats(p)
    assert stats is None
    assert err
    assert str(err).startswith("dependency_missing:openpyxl")

