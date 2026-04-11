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
    spec = importlib.util.spec_from_file_location("parser_benchmark_specialty", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _fixture_root() -> Path:
    return _repo_root() / "tests" / "fixtures" / "parsing_golden"


def test_parser_benchmark_reports_specialty_element_counts(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()
    input_dir = _fixture_root()
    manifest_path = input_dir / "manifest.json"

    factory_mod = ModuleType("app.parsing.factory")

    class _Factory:
        def parse_with_provenance(self, path, *_args, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            path_str = str(path)
            if "seal_invoice" in path_str:
                docs = [
                    Document(page_content="合同正文", metadata={"page": 1}),
                    Document(
                        page_content="印章识别：甲方公章",
                        metadata={"doc_type_kwd": "seal", "page": 1, "seal_score": 0.97},
                    ),
                ]
            elif "formula_pdf" in path_str:
                docs = [
                    Document(
                        page_content="![formula](eq.png)\n$$ E = mc^2 $$\n",
                        metadata={
                            "page": 1,
                            "derived_elements": [
                                {
                                    "kind": "equation",
                                    "text": "E = mc^2",
                                    "page": 1,
                                    "attributes": {
                                        "source_content_type": "formula_ocr",
                                        "source_doc_type": "formula_ocr",
                                    },
                                }
                            ],
                        },
                    ),
                ]
            else:
                docs = [
                    Document(
                        page_content="| A | B |\n| --- | --- |\n| 1 | 2 |",
                        metadata={"doc_type_kwd": "table", "page": 1},
                    ),
                    Document(
                        page_content="Figure 1",
                        metadata={"doc_type_kwd": "image", "page": 1},
                    ),
                ]
            return (
                docs,
                "deepdoc",
                {"attempts": [{"backend": "deepdoc"}]},
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

    out_path = tmp_path / "parser_benchmark.json"
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
            "deepdoc",
            "--out",
            str(out_path),
        ],
    )

    rc = mod.main()  # type: ignore[attr-defined]
    assert rc == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(payload.get("fixture_hash"), str) and len(payload["fixture_hash"]) == 24
    assert isinstance(payload.get("profile_hash"), str) and len(payload["profile_hash"]) == 24
    assert len(payload["cases"]) == 3
    by_case = {row["id"]: row for row in payload["cases"]}
    assert by_case["seal_invoice_case"]["golden"]["specialty_elements"]["seal"] == 1
    assert by_case["formula_pdf_case"]["golden"]["specialty_elements"]["equation"] == 1
    assert by_case["table_scan_case"]["golden"]["specialty_elements"]["table"] == 1
    assert by_case["table_scan_case"]["golden"]["specialty_elements"]["image"] == 1
    assert by_case["seal_invoice_case"]["attempts"][0]["specialty_recall"]["seal"] == 1.0
    assert by_case["formula_pdf_case"]["attempts"][0]["specialty_recall"]["equation"] == 1.0
    assert by_case["table_scan_case"]["attempts"][0]["specialty_recall"]["table"] == 1.0
    assert by_case["table_scan_case"]["attempts"][0]["specialty_recall"]["image"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_seal_recall"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_equation_recall"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_table_recall"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_image_recall"] == 1.0
