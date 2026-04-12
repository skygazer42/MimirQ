from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

from langchain_core.documents import Document


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "parser_benchmark.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("parser_benchmark_broader", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _fixture_root() -> Path:
    return _repo_root() / "tests" / "fixtures" / "parsing_golden_broader"


def _install_fake_parser_benchmark_modules(monkeypatch) -> None:  # noqa: ANN001
    factory_mod = ModuleType("app.parsing.factory")

    class _Factory:
        def parse_with_provenance(self, path, *_args, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            path_str = str(path)
            if "line_chart_pdf" in path_str:
                docs = [
                    Document(
                        page_content="扫描版折线趋势图 PDF。\n\n![asset](line_chart.png)",
                        metadata={"doc_type_kwd": "image", "page": 1, "visual_kind": "chart"},
                    ),
                ]
            elif "chart_pdf" in path_str:
                docs = [
                    Document(
                        page_content="扫描版财务图表 PDF。\n\n![asset](chart.png)",
                        metadata={"doc_type_kwd": "image", "page": 1, "visual_kind": "chart"},
                    ),
                ]
            elif "diagram_pdf" in path_str:
                docs = [
                    Document(
                        page_content="扫描版流程图 PDF。\n\n![asset](diagram.png)",
                        metadata={"doc_type_kwd": "image", "page": 1, "visual_kind": "diagram"},
                    ),
                ]
            elif "qr_image" in path_str:
                docs = [
                    Document(
                        page_content="原始图片为客服二维码。\n\n![asset](sample.png)",
                        metadata={"doc_type_kwd": "image", "page": 1, "visual_kind": "qr", "image_code_text": "HELLO-QR"},
                    ),
                ]
            elif "cross_page_table_pdf" in path_str:
                docs = [
                    Document(
                        page_content=(
                            "Quarterly revenue by region.\n\n"
                            "| Region | Q1 | Q2 |\n"
                            "| --- | --- | --- |\n"
                            "| North | 120 | 132 |\n"
                            "| South | 98 | 110 |\n"
                            "| West | 115 | 121 |\n"
                            "| East | 107 | 116 |\n"
                            "| Central | 111 | 119 |\n"
                            "| APAC | 126 | 138 |"
                        ),
                        metadata={"doc_type_kwd": "table", "page": 1},
                    ),
                ]
            elif "borderless_table_scan" in path_str:
                docs = [
                    Document(
                        page_content=(
                            "Inventory snapshot.\n\n"
                            "| Item | Qty | Warehouse |\n"
                            "| --- | --- | --- |\n"
                            "| Paper | 220 | HZ-A |\n"
                            "| Pens | 540 | HZ-B |\n"
                            "| Folders | 180 | HZ-A |"
                        ),
                        metadata={"doc_type_kwd": "table", "page": 1},
                    ),
                ]
            elif "merged_header_table_pdf" in path_str:
                docs = [
                    Document(
                        page_content=(
                            "Project budget summary.\n\n"
                            "Budget 2026\n\n"
                            "| Team | Approved | Spent |\n"
                            "| --- | --- | --- |\n"
                            "| Platform | 320 | 188 |\n"
                            "| Search | 280 | 154 |\n"
                            "| Ops | 160 | 97 |"
                        ),
                        metadata={"doc_type_kwd": "table", "page": 1},
                    ),
                ]
            elif "table_with_leading_paragraph_pdf" in path_str:
                docs = [
                    Document(
                        page_content=(
                            "The following table summarizes the latest quarterly on-time delivery metrics.\n\n"
                            "All values are percentages and should be indexed with the table content.\n\n"
                            "| Quarter | On-time | Delayed |\n"
                            "| --- | --- | --- |\n"
                            "| Q1 | 96% | 4% |\n"
                            "| Q2 | 94% | 6% |\n"
                            "| Q3 | 97% | 3% |"
                        ),
                        metadata={"doc_type_kwd": "table", "page": 1},
                    ),
                ]
            elif "two_column_pdf" in path_str:
                docs = [
                    Document(
                        page_content="\n".join(
                            [
                                "L1@@1\t0\t40\t0\t10##",
                                "L2@@1\t0\t40\t20\t30##",
                                "L3@@1\t0\t40\t40\t50##",
                                "R1@@1\t60\t100\t0\t10##",
                                "R2@@1\t60\t100\t20\t30##",
                                "R3@@1\t60\t100\t40\t50##",
                            ]
                        ),
                        metadata={"page": 1},
                    ),
                ]
            elif "header_footer_noise_pdf" in path_str:
                docs = [
                    Document(
                        page_content="\n".join(
                            [
                                "North region revenue increased steadily.@@1\t0\t40\t20\t30##",
                                "Operating margin held above target.@@1\t0\t40\t40\t50##",
                                "East region revenue accelerated in Q3.@@1\t60\t100\t20\t30##",
                                "Customer churn declined year over year.@@1\t60\t100\t40\t50##",
                                "Quarterly Operations Report@@1\t0\t100\t60\t70##",
                                "Page 1@@1\t0\t100\t90\t100##",
                            ]
                        ),
                        metadata={"page": 1},
                    ),
                ]
            elif "mixed_layout_pdf" in path_str:
                docs = [
                    Document(
                        page_content="\n".join(
                            [
                                "North region revenue increased steadily.@@1\t0\t40\t0\t10##",
                                "Operating margin held above target.@@1\t0\t40\t20\t30##",
                                "East region revenue accelerated in Q3.@@1\t60\t100\t0\t10##",
                                "Customer churn declined year over year.@@1\t60\t100\t20\t30##",
                                "Diagram summary.@@1\t0\t100\t55\t65##",
                                "Diagram details remain within expected layout flow.@@1\t0\t100\t75\t85##",
                            ]
                        ),
                        metadata={"page": 1},
                    ),
                ]
            elif "multilingual_pdf" in path_str:
                docs = [
                    Document(
                        page_content=(
                            "Multilingual revenue summary.\n\n"
                            "APAC revenue 同比增长 12%。\n\n"
                            "North America customer retention remained 94%.\n\n"
                            "EMEA pipeline status 保持 stable。\n\n"
                            "Support contact alias is bilingual-helpdesk."
                        ),
                        metadata={"page": 1},
                    ),
                ]
            elif "formula_markdown" in path_str:
                docs = [
                    Document(
                        page_content="$$ E = mc^2 $$",
                        metadata={"page": 1},
                    ),
                ]
            else:
                docs = [
                    Document(
                        page_content="原始图片为库存条码。\n\n![asset](sample.png)",
                        metadata={"doc_type_kwd": "image", "page": 1, "visual_kind": "barcode", "image_code_text": "5901234123457"},
                    ),
                ]
            return (
                docs,
                "basic",
                {"attempts": [{"backend": "basic"}]},
            )

    factory_mod.parser_factory = _Factory()
    monkeypatch.setitem(sys.modules, "app.parsing.factory", factory_mod)

    quality_doc_mod = ModuleType("app.parsing.quality.document_quality")
    quality_doc_mod.score_document_parse_quality = lambda **_kwargs: {"score": 0.91}  # noqa: E731
    monkeypatch.setitem(sys.modules, "app.parsing.quality.document_quality", quality_doc_mod)

    scorer_mod = ModuleType("app.parsing.quality.scorer")
    scorer_mod.score_pdf_quality = lambda *_args, **_kwargs: None  # noqa: E731
    monkeypatch.setitem(sys.modules, "app.parsing.quality.scorer", scorer_mod)

    text_quality_mod = ModuleType("app.parsing.quality.text_quality")

    class _TextQuality:
        def to_dict(self) -> dict[str, float]:
            return {"density": 0.95, "replacement_ratio": 0.0}

    text_quality_mod.score_parsed_text_quality = lambda *_args, **_kwargs: _TextQuality()  # noqa: E731
    monkeypatch.setitem(sys.modules, "app.parsing.quality.text_quality", text_quality_mod)


def test_parser_benchmark_reports_broader_pdf_and_image_corpus(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()
    input_dir = _fixture_root()
    manifest_path = input_dir / "manifest.json"

    _install_fake_parser_benchmark_modules(monkeypatch)

    out_path = tmp_path / "parser_benchmark_broader.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parser_benchmark.py",
            "--input-dir",
            str(input_dir),
            "--manifest",
            str(manifest_path),
            "--backends",
            "basic",
            "--out",
            str(out_path),
        ],
    )

    rc = mod.main()  # type: ignore[attr-defined]
    assert rc == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(payload["cases"]) == 14
    by_case = {row["id"]: row for row in payload["cases"]}
    assert by_case["chart_pdf_case"]["golden"]["image_visual_kinds"]["chart"] == 1
    assert by_case["line_chart_pdf_case"]["golden"]["image_visual_kinds"]["chart"] == 1
    assert by_case["diagram_pdf_case"]["golden"]["image_visual_kinds"]["diagram"] == 1
    assert by_case["qr_image_case"]["golden"]["image_code_values"]["qr"] == ["HELLO-QR"]
    assert by_case["barcode_image_case"]["golden"]["image_code_values"]["barcode"] == ["5901234123457"]
    assert by_case["cross_page_table_pdf_case"]["golden"]["specialty_elements"]["table"] == 1
    assert by_case["borderless_table_scan_case"]["golden"]["specialty_elements"]["table"] == 1
    assert by_case["merged_header_table_pdf_case"]["golden"]["specialty_elements"]["table"] == 1
    assert by_case["table_with_leading_paragraph_pdf_case"]["golden"]["specialty_elements"]["table"] == 1
    assert by_case["formula_markdown_case"]["golden"]["specialty_elements"]["equation"] == 1
    assert by_case["two_column_pdf_case"]["golden"]["structure"]["image_refs"] == 0
    assert by_case["header_footer_noise_pdf_case"]["golden"]["structure"]["image_refs"] == 0
    assert by_case["mixed_layout_pdf_case"]["golden"]["structure"]["image_refs"] == 0
    assert by_case["multilingual_pdf_case"]["golden"]["structure"]["image_refs"] == 0
    assert payload["summary"]["basic"]["mean_image_recall"] == 1.0
    assert payload["summary"]["basic"]["mean_table_recall"] == 1.0
    assert payload["summary"]["basic"]["mean_table_continuity_recall"] == 1.0
    assert payload["summary"]["basic"]["mean_reading_order_score"] is not None
    assert payload["summary"]["basic"]["mean_chart_image_recall"] == 1.0
    assert payload["summary"]["basic"]["mean_diagram_image_recall"] == 1.0
    assert payload["summary"]["basic"]["mean_qr_image_recall"] == 1.0
    assert payload["summary"]["basic"]["mean_barcode_image_recall"] == 1.0
    assert payload["summary"]["basic"]["mean_qr_code_value_recall"] == 1.0
    assert payload["summary"]["basic"]["mean_barcode_code_value_recall"] == 1.0
    assert by_case["two_column_pdf_case"]["attempts"][0]["reading_order_score"] == 1.0
    assert by_case["cross_page_table_pdf_case"]["attempts"][0]["table_continuity_recall"] == 1.0
    assert by_case["borderless_table_scan_case"]["attempts"][0]["table_continuity_recall"] == 1.0
    assert by_case["merged_header_table_pdf_case"]["attempts"][0]["table_continuity_recall"] == 1.0
    assert by_case["table_with_leading_paragraph_pdf_case"]["attempts"][0]["table_continuity_recall"] == 1.0
    assert by_case["header_footer_noise_pdf_case"]["attempts"][0]["reading_order_score"] is not None
    assert by_case["header_footer_noise_pdf_case"]["attempts"][0]["reading_order_score"] >= 0.7
    assert by_case["mixed_layout_pdf_case"]["attempts"][0]["reading_order_score"] is not None
    assert by_case["mixed_layout_pdf_case"]["attempts"][0]["reading_order_score"] >= 0.7


def test_table_continuity_recall_penalizes_split_table_blocks() -> None:
    mod = _load_module()

    golden = (
        "| Region | Q1 | Q2 |\n"
        "| --- | --- | --- |\n"
        "| North | 120 | 132 |\n"
        "| South | 98 | 110 |\n"
        "| West | 115 | 121 |\n"
        "| East | 107 | 116 |\n"
    )
    parsed = (
        "| Region | Q1 | Q2 |\n"
        "| --- | --- | --- |\n"
        "| North | 120 | 132 |\n"
        "| South | 98 | 110 |\n\n"
        "| Region | Q1 | Q2 |\n"
        "| --- | --- | --- |\n"
        "| West | 115 | 121 |\n"
        "| East | 107 | 116 |\n"
    )

    recall = mod._table_continuity_recall(golden_markdown=golden, parsed_markdown=parsed)  # type: ignore[attr-defined]

    assert recall == 0.5


def test_join_documents_to_markdown_synthesizes_image_refs_for_image_docs() -> None:
    mod = _load_module()

    markdown = mod._join_documents_to_markdown(  # type: ignore[attr-defined]
        [
            Document(
                page_content="",
                metadata={"doc_type_kwd": "image", "page": 1, "visual_kind": "chart", "image_index": 0},
            )
        ]
    )

    assert "![chart](" in markdown
    assert mod._structure_metrics(markdown)["image_refs"] == 1  # type: ignore[attr-defined]
