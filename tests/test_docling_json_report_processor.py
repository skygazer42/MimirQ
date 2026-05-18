from __future__ import annotations

from types import SimpleNamespace


def _prov(page_no: int, bbox: tuple[float, float, float, float]) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            page_no=page_no,
            bbox=SimpleNamespace(l=float(bbox[0]), t=float(bbox[1]), r=float(bbox[2]), b=float(bbox[3])),
        )
    ]


def test_docling_json_report_processor_builds_sections_tables_pictures_and_page_continuity(monkeypatch):  # noqa: ANN001
    from app.deepdoc.parser.docling_parser import DoclingParser, JsonReportProcessor

    parser = DoclingParser()
    processor = JsonReportProcessor(parser)

    monkeypatch.setattr(
        parser,
        "cropout_docling_table",
        lambda page_no, bbox, zoomin=1: (f"img-{page_no}", [(page_no - 1, *bbox)]),
        raising=True,
    )

    doc = SimpleNamespace(
        num_pages=2,
        texts=[
            SimpleNamespace(
                text="Section one",
                label="text",
                parent=SimpleNamespace(cref="#/body"),
                prov=_prov(1, (10, 20, 30, 40)),
            ),
                SimpleNamespace(
                    text="Equation body",
                    label="FORMULA",
                    parent=SimpleNamespace(cref="#/body"),
                    prov=SimpleNamespace(page_no=2, bbox=SimpleNamespace(l=11.0, t=21.0, r=31.0, b=41.0)),
                ),
        ],
        tables=[
            SimpleNamespace(
                prov=_prov(1, (1, 2, 3, 4)),
                export_to_html=lambda doc=None: "<table><tr><td>A</td></tr></table>",
            ),
        ],
        pictures=[
            SimpleNamespace(
                prov=_prov(2, (5, 6, 7, 8)),
                caption_text=lambda doc=None: "Picture caption",
            ),
        ],
    )

    report = processor.build_report(doc, parse_method="raw")

    assert report["schema"] == "mimirq.docling_json_report.v1"
    assert report["metainfo"]["page_count"] == 2
    assert report["metainfo"]["page_continuity"]["continuous"] is True
    assert report["metainfo"]["page_continuity"]["pages_seen"] == [1, 2]
    assert len(report["content"]) == 2
    assert len(report["tables"]) == 1
    assert len(report["pictures"]) == 1

    sections, tables = processor.to_sections_tables(report)
    assert len(sections) == 2
    assert len(tables) == 2
    assert "Section one" in sections[0][0]
    assert tables[0][0][1] == "<table><tr><td>A</td></tr></table>"
    assert tables[1][0][1] == ["Picture caption"]


def test_docling_json_report_processor_flags_missing_pages_in_continuity() -> None:
    from app.deepdoc.parser.docling_parser import DoclingParser, JsonReportProcessor

    parser = DoclingParser()
    processor = JsonReportProcessor(parser)
    doc = SimpleNamespace(
        num_pages=3,
        texts=[
            SimpleNamespace(
                text="Page one",
                label="text",
                parent=SimpleNamespace(cref="#/body"),
                prov=_prov(1, (10, 20, 30, 40)),
            ),
            SimpleNamespace(
                text="Page three",
                label="text",
                parent=SimpleNamespace(cref="#/body"),
                prov=_prov(3, (10, 20, 30, 40)),
            ),
        ],
        tables=[],
        pictures=[],
    )

    report = processor.build_report(doc, parse_method="raw")
    continuity = report["metainfo"]["page_continuity"]

    assert continuity["continuous"] is False
    assert continuity["pages_seen"] == [1, 3]
    assert continuity["missing_pages"] == [2]


def test_docling_json_report_processor_accepts_num_pages_method() -> None:
    from app.deepdoc.parser.docling_parser import DoclingParser, JsonReportProcessor

    parser = DoclingParser()
    processor = JsonReportProcessor(parser)
    doc = SimpleNamespace(
        num_pages=lambda: 4,
        texts=[
            SimpleNamespace(
                text="Page one",
                label="text",
                parent=SimpleNamespace(cref="#/body"),
                prov=_prov(1, (10, 20, 30, 40)),
            ),
        ],
        tables=[],
        pictures=[],
    )

    report = processor.build_report(doc, parse_method="raw")

    assert report["metainfo"]["page_count"] == 4
