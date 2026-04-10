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


def test_parser_benchmark_reports_specialty_element_counts(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()

    input_dir = tmp_path / "golden"
    input_dir.mkdir(parents=True, exist_ok=True)
    sample_path = input_dir / "sample.md"
    sample_path.write_text("合同正文\n", encoding="utf-8")
    golden_path = input_dir / "sample.golden.md"
    golden_path.write_text("合同正文\n", encoding="utf-8")
    manifest_path = input_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "seal-formula-case",
                        "path": "sample.md",
                        "golden_markdown": "sample.golden.md",
                        "specialty_elements": {
                            "seal": 1,
                            "equation": 1,
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    factory_mod = ModuleType("app.parsing.factory")

    class _Factory:
        def parse_with_provenance(self, *_args, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return (
                [
                    Document(page_content="合同正文", metadata={"page": 1}),
                    Document(
                        page_content="印章识别：甲方公章",
                        metadata={"doc_type_kwd": "seal", "page": 1, "seal_score": 0.97},
                    ),
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
                ],
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
    assert payload["cases"][0]["attempts"][0]["specialty_elements"]["seal"] == 1
    assert payload["cases"][0]["attempts"][0]["specialty_elements"]["equation"] == 1
    assert payload["cases"][0]["attempts"][0]["specialty_recall"]["seal"] == 1.0
    assert payload["cases"][0]["attempts"][0]["specialty_recall"]["equation"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_seal_recall"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_equation_recall"] == 1.0
