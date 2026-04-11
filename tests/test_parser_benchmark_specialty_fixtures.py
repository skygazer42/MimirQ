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


def _install_fake_parser_benchmark_modules(monkeypatch) -> None:  # noqa: ANN001
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
            elif "qr_sheet" in path_str:
                docs = [
                    Document(
                        page_content="Customer service QR code\n\n![qrcode](qr.png)",
                        metadata={"doc_type_kwd": "image", "page": 1, "visual_kind": "qr"},
                    ),
                ]
            elif "diagram_page" in path_str:
                docs = [
                    Document(
                        page_content="System architecture diagram\n\n![diagram](diagram.png)",
                        metadata={"doc_type_kwd": "image", "page": 1, "visual_kind": "diagram"},
                    ),
                ]
            elif "barcode_label" in path_str:
                docs = [
                    Document(
                        page_content="Inventory barcode label\n\n![barcode](barcode.png)",
                        metadata={"doc_type_kwd": "image", "page": 1, "visual_kind": "barcode"},
                    ),
                ]
            else:
                docs = [
                    Document(
                        page_content="![chart](chart.png)\n\n| A | B |\n| --- | --- |\n| 1 | 2 |",
                        metadata={"doc_type_kwd": "table", "page": 1},
                    ),
                    Document(
                        page_content="Revenue growth chart",
                        metadata={"doc_type_kwd": "image", "page": 1, "visual_kind": "chart"},
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


def test_parser_benchmark_reports_specialty_element_counts(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()
    input_dir = _fixture_root()
    manifest_path = input_dir / "manifest.json"

    _install_fake_parser_benchmark_modules(monkeypatch)

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
    assert len(payload["cases"]) == 6
    by_case = {row["id"]: row for row in payload["cases"]}
    assert by_case["seal_invoice_case"]["golden"]["specialty_elements"]["seal"] == 1
    assert by_case["formula_pdf_case"]["golden"]["specialty_elements"]["equation"] == 1
    assert by_case["table_scan_case"]["golden"]["specialty_elements"]["table"] == 1
    assert by_case["table_scan_case"]["golden"]["specialty_elements"]["image"] == 1
    assert by_case["table_scan_case"]["golden"]["image_visual_kinds"]["chart"] == 1
    assert by_case["qr_sheet_case"]["golden"]["image_visual_kinds"]["qr"] == 1
    assert by_case["diagram_page_case"]["golden"]["image_visual_kinds"]["diagram"] == 1
    assert by_case["barcode_label_case"]["golden"]["image_visual_kinds"]["barcode"] == 1
    assert by_case["seal_invoice_case"]["attempts"][0]["specialty_recall"]["seal"] == 1.0
    assert by_case["formula_pdf_case"]["attempts"][0]["specialty_recall"]["equation"] == 1.0
    assert by_case["table_scan_case"]["attempts"][0]["specialty_recall"]["table"] == 1.0
    assert by_case["table_scan_case"]["attempts"][0]["specialty_recall"]["image"] == 1.0
    assert by_case["table_scan_case"]["attempts"][0]["specialty_image_visual_kinds"]["chart"] == 1
    assert by_case["table_scan_case"]["attempts"][0]["specialty_image_visual_kind_recall"]["chart"] == 1.0
    assert by_case["qr_sheet_case"]["attempts"][0]["specialty_recall"]["image"] == 1.0
    assert by_case["qr_sheet_case"]["attempts"][0]["specialty_image_visual_kinds"]["qr"] == 1
    assert by_case["qr_sheet_case"]["attempts"][0]["specialty_image_visual_kind_recall"]["qr"] == 1.0
    assert by_case["diagram_page_case"]["attempts"][0]["specialty_recall"]["image"] == 1.0
    assert by_case["diagram_page_case"]["attempts"][0]["specialty_image_visual_kinds"]["diagram"] == 1
    assert by_case["diagram_page_case"]["attempts"][0]["specialty_image_visual_kind_recall"]["diagram"] == 1.0
    assert by_case["barcode_label_case"]["attempts"][0]["specialty_recall"]["image"] == 1.0
    assert by_case["barcode_label_case"]["attempts"][0]["specialty_image_visual_kinds"]["barcode"] == 1
    assert by_case["barcode_label_case"]["attempts"][0]["specialty_image_visual_kind_recall"]["barcode"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_seal_recall"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_equation_recall"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_table_recall"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_image_recall"] == 1.0
    assert payload["summary"]["deepdoc"]["golden_image_ref_recall_mean"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_chart_image_recall"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_qr_image_recall"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_barcode_image_recall"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_diagram_image_recall"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_image_visual_kind_recall"]["chart"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_image_visual_kind_recall"]["qr"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_image_visual_kind_recall"]["barcode"] == 1.0
    assert payload["summary"]["deepdoc"]["mean_image_visual_kind_recall"]["diagram"] == 1.0


def test_parser_benchmark_strict_fails_when_baseline_hashes_mismatch(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()
    input_dir = _fixture_root()
    manifest_path = input_dir / "manifest.json"

    _install_fake_parser_benchmark_modules(monkeypatch)

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "schema": "mimirq.parser_benchmark.v1",
                "fixture_hash": "fixture-mismatch",
                "profile_hash": "profile-mismatch",
                "summary": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out_path = tmp_path / "parser_benchmark.strict.json"
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
            "--strict",
            "--baseline",
            str(baseline_path),
            "--out",
            str(out_path),
        ],
    )

    rc = mod.main()  # type: ignore[attr-defined]
    assert rc == 2

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    strict_gate = payload.get("strict_gate") or {}
    assert strict_gate.get("passed") is False
    compatibility = strict_gate.get("compatibility") or {}
    assert compatibility.get("compatible") is False
    mismatches = list(compatibility.get("mismatches") or [])
    assert any("fixture_hash" in item for item in mismatches)
    assert any("profile_hash" in item for item in mismatches)


def test_parser_benchmark_strict_passes_with_repo_fixture_baseline(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()
    input_dir = _fixture_root()
    manifest_path = input_dir / "manifest.json"

    _install_fake_parser_benchmark_modules(monkeypatch)

    out_path = tmp_path / "parser_benchmark.strict.ok.json"
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
            "--max-files",
            "6",
            "--strict",
            "--baseline",
            str(_repo_root() / "ci" / "parser_benchmark_baseline.v1.json"),
            "--strict-profile",
            str(_repo_root() / "ci" / "parser_strict_profile.v1.json"),
            "--out",
            str(out_path),
        ],
    )

    rc = mod.main()  # type: ignore[attr-defined]
    assert rc == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    strict_gate = payload.get("strict_gate") or {}
    assert strict_gate.get("passed") is True
    compatibility = strict_gate.get("compatibility") or {}
    assert compatibility.get("compatible") is True
    assert list(compatibility.get("mismatches") or []) == []


def test_repo_parser_benchmark_baseline_matches_fake_fixture_smoke(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()
    input_dir = _fixture_root()
    manifest_path = input_dir / "manifest.json"

    out_path = tmp_path / "parser_benchmark.baseline.check.json"
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
            "--max-files",
            "6",
            "--strict-profile",
            str(_repo_root() / "ci" / "parser_strict_profile.v1.json"),
            "--out",
            str(out_path),
        ],
    )

    rc = mod.main()  # type: ignore[attr-defined]
    assert rc == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    baseline = json.loads((_repo_root() / "ci" / "parser_benchmark_baseline.v1.json").read_text(encoding="utf-8"))

    assert payload.get("fixture_hash") == baseline.get("fixture_hash")
    assert payload.get("profile_hash") == baseline.get("profile_hash")
    payload_summary = (payload.get("summary") or {}).get("basic") or {}
    baseline_summary = (baseline.get("summary") or {}).get("basic") or {}
    for key, value in baseline_summary.items():
        assert payload_summary.get(key) == value


def test_parser_benchmark_reports_missing_local_markdown_assets(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()
    fixture_root = tmp_path / "fixture"
    (fixture_root / "input").mkdir(parents=True, exist_ok=True)
    (fixture_root / "golden").mkdir(parents=True, exist_ok=True)
    (fixture_root / "input" / "sample.md").write_text("正文。", encoding="utf-8")
    (fixture_root / "golden" / "sample.md").write_text("![chart](missing-chart.png)\n", encoding="utf-8")
    (fixture_root / "manifest.json").write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "missing-asset-case",
                        "path": "input/sample.md",
                        "golden_markdown": "golden/sample.md",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    _install_fake_parser_benchmark_modules(monkeypatch)

    out_path = tmp_path / "parser_benchmark.missing-asset.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parser_benchmark.py",
            "--input-dir",
            str(fixture_root),
            "--manifest",
            str(fixture_root / "manifest.json"),
            "--backends",
            "deepdoc",
            "--out",
            str(out_path),
        ],
    )

    rc = mod.main()  # type: ignore[attr-defined]
    assert rc == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["fixture_issues"][0]["case_id"] == "missing-asset-case"
    assert payload["fixture_issues"][0]["type"] == "missing_local_assets"
    assert payload["fixture_issues"][0]["items"] == ["missing-chart.png"]


def test_parser_benchmark_strict_fails_on_fixture_issues_even_with_matching_baseline(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()
    fixture_root = tmp_path / "fixture"
    (fixture_root / "input").mkdir(parents=True, exist_ok=True)
    (fixture_root / "golden").mkdir(parents=True, exist_ok=True)
    (fixture_root / "input" / "sample.md").write_text("正文。", encoding="utf-8")
    (fixture_root / "golden" / "sample.md").write_text("![chart](missing-chart.png)\n", encoding="utf-8")
    (fixture_root / "manifest.json").write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "missing-asset-case",
                        "path": "input/sample.md",
                        "golden_markdown": "golden/sample.md",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    _install_fake_parser_benchmark_modules(monkeypatch)

    preflight_out = tmp_path / "preflight.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parser_benchmark.py",
            "--input-dir",
            str(fixture_root),
            "--manifest",
            str(fixture_root / "manifest.json"),
            "--backends",
            "deepdoc",
            "--out",
            str(preflight_out),
        ],
    )
    rc = mod.main()  # type: ignore[attr-defined]
    assert rc == 0
    preflight = json.loads(preflight_out.read_text(encoding="utf-8"))

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "schema": "mimirq.parser_benchmark.v1",
                "fixture_hash": preflight["fixture_hash"],
                "profile_hash": preflight["profile_hash"],
                "summary": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    strict_out = tmp_path / "strict.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parser_benchmark.py",
            "--input-dir",
            str(fixture_root),
            "--manifest",
            str(fixture_root / "manifest.json"),
            "--backends",
            "deepdoc",
            "--strict",
            "--baseline",
            str(baseline_path),
            "--out",
            str(strict_out),
        ],
    )
    rc = mod.main()  # type: ignore[attr-defined]
    assert rc == 2

    payload = json.loads(strict_out.read_text(encoding="utf-8"))
    strict_gate = payload.get("strict_gate") or {}
    assert strict_gate.get("passed") is False
    failures = list(strict_gate.get("failures") or [])
    assert any("missing_local_assets" in item for item in failures)
