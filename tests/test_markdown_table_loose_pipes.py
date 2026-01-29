from __future__ import annotations

from app.rag.preprocessing.cleaning import clean_markdown
from app.rag.preprocessing.tables import normalize_markdown_tables


def test_clean_markdown_preserves_tables_without_outer_pipes() -> None:
    md = "a | b\n---|---\n1 | 2\n"
    res = clean_markdown(
        md,
        remove_toc_lines=False,
        remove_noise_lines=True,
        remove_common_lines=False,
        unwrap_lines=True,
    )
    assert "a | b" in res.markdown
    assert "---|---" in res.markdown
    assert "1 | 2" in res.markdown


def test_normalize_markdown_tables_handles_rows_without_outer_pipes() -> None:
    md = "a | b\n---|---\n1 | 2\n"
    res = normalize_markdown_tables(md)
    assert res.changed is True
    assert "| a | b |" in res.text
    assert "| --- | --- |" in res.text
