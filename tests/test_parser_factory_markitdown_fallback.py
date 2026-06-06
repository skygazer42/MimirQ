from pathlib import Path
from types import SimpleNamespace

from langchain_core.documents import Document

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


def test_parser_factory_falls_back_to_legacy_office_converter_when_markitdown_fails(tmp_path):
    p = tmp_path / "legacy.doc"
    p.write_bytes(b"not a real doc; fallback is monkeypatched")
    factory = ParserFactory()
    factory._get_markitdown_parser = lambda: _BrokenMarkItDown()  # type: ignore[attr-defined]
    factory._try_legacy_office_pandoc_fallback = lambda file_path: ([  # type: ignore[attr-defined]
        Document(page_content="converted legacy office", metadata={"parser_backend": "pandoc"})
    ], "pandoc")

    docs, backend = factory.parse(p)

    assert backend == "pandoc"
    assert docs[0].page_content == "converted legacy office"
    assert docs[0].metadata.get("source") == "legacy.doc"


def test_pandoc_legacy_office_conversion_uses_absolute_input_path(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.parsing.parsers import pandoc_parser as mod

    monkeypatch.setattr(settings, "PANDOC_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LIBREOFFICE_ENABLED", True, raising=False)
    monkeypatch.setattr(mod, "resolve_cli_command", lambda value: f"/usr/bin/{value}", raising=True)

    captured: dict[str, list[str]] = {}

    def fake_run_resolved_cli(args, **_kwargs):  # noqa: ANN001
        captured["args"] = list(args)
        out_dir = Path(args[args.index("--outdir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "legacy.docx").write_text("converted", encoding="utf-8")
        return SimpleNamespace(stdout=b"", stderr=b"")

    monkeypatch.setattr(mod, "run_resolved_cli", fake_run_resolved_cli, raising=True)

    parser = mod.PandocParser()
    parser._convert_via_libreoffice(file_path=Path("relative/legacy.doc"), artifact_root=tmp_path / "artifact")

    assert Path(captured["args"][-1]).is_absolute()
