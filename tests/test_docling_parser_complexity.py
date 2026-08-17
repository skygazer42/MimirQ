from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.deepdoc.parser.docling_parser import DoclingParser, JsonReportProcessor


def _prov(page_no: int, bbox: tuple[float, float, float, float]) -> SimpleNamespace:
    left, top, right, bottom = bbox
    return SimpleNamespace(
        page_no=page_no,
        bbox=SimpleNamespace(l=left, t=top, r=right, b=bottom),
    )


def test_json_report_processor_build_report_keeps_output_fields_and_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = DoclingParser()
    crop_positions = [(0, 10.0, 20.0, 30.0, 40.0)]
    crop_result = ("cropped-image", crop_positions)
    monkeypatch.setattr(
        parser,
        "_transfer_to_sections",
        lambda doc, parse_method="raw": [("Section body", "@@1\t10.0\t20.0\t30.0\t40.0##")],
    )
    monkeypatch.setattr(parser, "cropout_docling_table", lambda page_no, bbox: crop_result)

    table = SimpleNamespace(
        prov=[_prov(1, (10.0, 20.0, 30.0, 40.0))],
        export_to_html=lambda doc: (_ for _ in ()).throw(RuntimeError("table fallback")),
    )
    picture = SimpleNamespace(
        prov=[_prov(3, (11.0, 21.0, 31.0, 41.0))],
        caption_text=lambda doc: (_ for _ in ()).throw(RuntimeError("picture fallback")),
    )
    doc = SimpleNamespace(
        num_pages=lambda: (_ for _ in ()).throw(RuntimeError("page-count fallback")),
        texts=[SimpleNamespace(prov=[_prov(1, (1.0, 2.0, 3.0, 4.0))])],
        tables=[table],
        pictures=[picture],
    )

    report = JsonReportProcessor(parser).build_report(doc, parse_method="raw")
    sections, tables = JsonReportProcessor.to_sections_tables(report)

    assert report["schema"] == "mimirq.docling_json_report.v1"
    assert report["metainfo"]["page_count"] == 0
    assert report["metainfo"]["page_continuity"] == {
        "pages_seen": [1, 3],
        "missing_pages": [2],
        "continuous": False,
    }
    assert report["content"] == [("Section body", "@@1\t10.0\t20.0\t30.0\t40.0##")]
    assert report["tables"] == [((crop_result[0], ""), crop_positions)]
    assert report["pictures"] == [((crop_result[0], [""]), crop_positions)]
    assert sections == report["content"]
    assert tables == report["tables"] + report["pictures"]


def test_crop_normalizes_inverted_bottom_before_spanning_pages() -> None:
    parser = DoclingParser()
    parser.page_images = [
        Image.new("RGB", (10, 10), "white"),
        Image.new("RGB", (10, 10), "white"),
    ]
    parser.page_from = 0

    picture, positions = parser.crop("@@1-2\t0\t10\t8\t5##", need_position=True)

    assert picture is not None
    assert positions == [
        (0, 0, 10, 8, 10),
        (1, 0, 10, 0, 2),
    ]


def test_parse_pdf_returns_sections_tables_and_deletes_temp_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parser = DoclingParser()
    callback_events: list[tuple[float, str]] = []
    image_calls: list[str] = []
    convert_paths: list[str] = []
    report_calls: list[tuple[object, str]] = []

    class _FakeConverter:
        def convert(self, src_path: str) -> SimpleNamespace:
            convert_paths.append(src_path)
            return SimpleNamespace(document=SimpleNamespace(num_pages=2))

    def _build_report(self, doc: object, *, parse_method: str = "raw") -> dict[str, object]:
        report_calls.append((doc, parse_method))
        return {
            "content": [("Section A", "@@1\t1.0\t2.0\t3.0\t4.0##")],
            "tables": [(("table-image", "<table>"), [(0, 1.0, 2.0, 3.0, 4.0)])],
            "pictures": [],
        }

    def _callback(progress: float, message: str) -> None:
        callback_events.append((progress, message))

    monkeypatch.setattr(parser, "check_installation", lambda: True)
    monkeypatch.setattr(
        parser,
        "__images__",
        lambda src_path, zoomin=1, page_from=0, page_to=600, callback=None: image_calls.append(src_path),
    )
    monkeypatch.setattr("app.deepdoc.parser.docling_parser.DocumentConverter", lambda: _FakeConverter())
    monkeypatch.setattr(JsonReportProcessor, "build_report", _build_report)

    output_dir = tmp_path / "docling-output"
    sections, tables = parser.parse_pdf(
        filepath="nested/report.pdf",
        binary=BytesIO(b"%PDF-1.4\n"),
        callback=_callback,
        output_dir=str(output_dir),
        parse_method="paper",
    )

    temp_pdf = output_dir / "report.pdf"

    assert sections == [("Section A", "@@1\t1.0\t2.0\t3.0\t4.0##")]
    assert tables == [(("table-image", "<table>"), [(0, 1.0, 2.0, 3.0, 4.0)])]
    assert not temp_pdf.exists()
    assert image_calls == [str(temp_pdf)]
    assert convert_paths == [str(temp_pdf)]
    assert report_calls == [(SimpleNamespace(num_pages=2), "paper")]
    assert callback_events == [
        (0.1, f"[Docling] Converting: {temp_pdf}"),
        (0.7, "[Docling] Parsed doc: 2 pages"),
        (0.95, "[Docling] Sections: 1, Tables: 1"),
        (1.0, "[Docling] Done."),
    ]


def test_parse_pdf_swallow_render_failure_but_preserve_conversion_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    parser = DoclingParser()

    class _FakeConverter:
        def convert(self, src_path: str) -> SimpleNamespace:
            return SimpleNamespace(document=SimpleNamespace(num_pages="n/a"))

    monkeypatch.setattr(parser, "check_installation", lambda: True)
    monkeypatch.setattr(parser, "__images__", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("render")))
    monkeypatch.setattr("app.deepdoc.parser.docling_parser.DocumentConverter", lambda: _FakeConverter())
    monkeypatch.setattr(
        JsonReportProcessor,
        "build_report",
        lambda self, doc, *, parse_method="raw": {"content": [("Body", "")], "tables": [], "pictures": []},
    )

    sections, tables = parser.parse_pdf(filepath=pdf_path)

    assert sections == [("Body", "")]
    assert tables == []


def test_parse_pdf_preserves_runtime_and_missing_file_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parser = DoclingParser()
    missing_path = tmp_path / "missing.pdf"

    monkeypatch.setattr(parser, "check_installation", lambda: False)
    with pytest.raises(RuntimeError, match=r"^Docling not available, please install `docling`$"):
        parser.parse_pdf(filepath=missing_path)

    monkeypatch.setattr(parser, "check_installation", lambda: True)
    with pytest.raises(FileNotFoundError, match=rf"^PDF not found: {re.escape(str(missing_path))}$"):
        parser.parse_pdf(filepath=missing_path)
