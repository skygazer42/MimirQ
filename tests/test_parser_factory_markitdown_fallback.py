from pathlib import Path

from app.parsing.factory import ParserFactory


class _BrokenMarkItDown:
    def parse(self, file_path: Path):
        raise RuntimeError("boom")


def test_parser_factory_falls_back_to_html_parser_when_markitdown_fails(tmp_path):
    p = tmp_path / "a.html"
    p.write_text("<html><head><title>T</title></head><body><h1>Hello</h1><p>World</p></body></html>", encoding="utf-8")
    factory = ParserFactory()
    factory._get_markitdown_parser = lambda: _BrokenMarkItDown()  # type: ignore[attr-defined]
    docs, backend = factory.parse(p)
    assert backend == "html"
    assert "Hello" in docs[0].page_content
    assert docs[0].metadata.get("source") == "a.html"


def test_parser_factory_falls_back_to_json_parser_when_markitdown_fails(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"a": 1, "b": 2}', encoding="utf-8")
    factory = ParserFactory()
    factory._get_markitdown_parser = lambda: _BrokenMarkItDown()  # type: ignore[attr-defined]
    docs, backend = factory.parse(p)
    assert backend == "json"
    assert '"a": 1' in docs[0].page_content
    assert docs[0].metadata.get("source") == "a.json"


def test_parser_factory_falls_back_to_csv_parser_when_markitdown_fails(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("name,age\nalice,30\nbob,40\n", encoding="utf-8")
    factory = ParserFactory()
    factory._get_markitdown_parser = lambda: _BrokenMarkItDown()  # type: ignore[attr-defined]
    docs, backend = factory.parse(p)
    assert backend == "csv"
    assert "Columns:" in docs[0].page_content
    assert "row 1:" in docs[0].page_content
    assert docs[0].metadata.get("source") == "a.csv"

