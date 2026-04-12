from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script():
    path = _repo_root() / "scripts" / "build_parsing_retrieval_proof_batch_spec.py"
    spec = importlib.util.spec_from_file_location("build_parsing_retrieval_proof_batch_spec", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_batch_spec_selects_only_cases_with_query_mapping(tmp_path: Path) -> None:
    mod = _load_script()
    manifest_path = tmp_path / "manifest.json"
    queries_one = tmp_path / "q1.json"
    queries_one.write_text("[]\n", encoding="utf-8")

    manifest_path.write_text(
        json.dumps(
            {
                "cases": [
                    {"id": "case-a", "path": "a/input/sample.pdf"},
                    {"id": "case-b", "path": "b/input/sample.pdf"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    spec = mod.build_batch_spec(  # type: ignore[attr-defined]
        manifest_path=manifest_path,
        case_queries={
            "case-a": {"queries_json": str(queries_one), "parser_backend": "basic", "top_k": 2, "retrieval_mode": "keyword"}
        },
        defaults={"parser_backend": "image", "top_k": 1, "retrieval_mode": "hybrid"},
    )

    assert spec["schema"] == "mimirq.parsing_retrieval_proof_batch.v1"
    assert spec["cases_total"] == 1
    assert spec["query_count_total"] == 0
    assert spec["provenance"]["manifest_path"] == str(manifest_path.resolve())
    assert len(spec["cases"]) == 1
    assert spec["cases"][0]["id"] == "case-a"
    assert spec["cases"][0]["parser_backend"] == "basic"
    assert spec["cases"][0]["top_k"] == 2
    assert spec["cases"][0]["retrieval_mode"] == "keyword"
    assert spec["cases"][0]["case_family"] == "document"
    assert spec["cases"][0]["case_category"] == "a"
    assert spec["cases"][0]["query_count"] == 0


def test_build_batch_spec_cli_writes_json(tmp_path: Path) -> None:
    mod = _load_script()
    manifest_path = tmp_path / "manifest.json"
    queries_one = tmp_path / "q1.json"
    case_queries_path = tmp_path / "case-queries.json"
    out_path = tmp_path / "batch.spec.json"

    queries_one.write_text("[]\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {"cases": [{"id": "case-a", "path": "a/input/sample.pdf"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    case_queries_path.write_text(
        json.dumps(
            {
                "case-a": {
                    "queries_json": str(queries_one),
                    "parser_backend": "basic",
                    "top_k": 2,
                    "retrieval_mode": "keyword",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--manifest-json",
            str(manifest_path),
            "--case-queries-json",
            str(case_queries_path),
            "--out",
            str(out_path),
            "--default-parser-backend",
            "image",
            "--default-top-k",
            "1",
            "--default-retrieval-mode",
            "hybrid",
        ]
    )

    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "mimirq.parsing_retrieval_proof_batch.v1"
    assert payload["cases_total"] == 1
    assert payload["query_count_total"] == 0
    assert payload["provenance"]["manifest_path"] == str(manifest_path.resolve())
    assert payload["provenance"]["case_queries_path"] == str(case_queries_path.resolve())
    assert len(payload["cases"]) == 1
    assert payload["cases"][0]["id"] == "case-a"
    assert payload["cases"][0]["parser_backend"] == "basic"
    assert payload["cases"][0]["query_count"] == 0


def test_real_broader_manifest_sample_query_map_can_build_and_run_batch_spec(tmp_path: Path) -> None:
    build_mod = _load_script()

    runner_path = _repo_root() / "scripts" / "run_parsing_retrieval_proof_batch.py"
    spec = importlib.util.spec_from_file_location("run_parsing_retrieval_proof_batch", str(runner_path))
    assert spec and spec.loader
    runner_mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner_mod
    spec.loader.exec_module(runner_mod)  # type: ignore[union-attr]

    manifest_path = _repo_root() / "tests" / "fixtures" / "parsing_golden_broader" / "manifest.json"
    case_queries_path = _repo_root() / "tests" / "fixtures" / "parsing_retrieval_proof" / "broader_case_queries.sample.json"
    out_path = tmp_path / "batch.spec.json"
    out_dir = tmp_path / "batch-run"

    rc = build_mod.main(  # type: ignore[attr-defined]
        [
            "--manifest-json",
            str(manifest_path),
            "--case-queries-json",
            str(case_queries_path),
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "mimirq.parsing_retrieval_proof_batch.v1"
    assert payload["cases_total"] == 14
    assert payload["query_count_total"] == 28
    assert payload["provenance"]["manifest_path"] == str(manifest_path.resolve())
    assert payload["provenance"]["case_queries_path"] == str(case_queries_path.resolve())
    assert len(payload["cases"]) == 14
    assert [item["id"] for item in payload["cases"]] == [
        "chart_pdf_case",
        "line_chart_pdf_case",
        "diagram_pdf_case",
        "qr_image_case",
        "barcode_image_case",
        "cross_page_table_pdf_case",
        "borderless_table_scan_case",
        "merged_header_table_pdf_case",
        "table_with_leading_paragraph_pdf_case",
        "two_column_pdf_case",
        "header_footer_noise_pdf_case",
        "mixed_layout_pdf_case",
        "multilingual_pdf_case",
        "formula_markdown_case",
    ]
    case_map = {item["id"]: item for item in payload["cases"]}
    assert case_map["chart_pdf_case"]["case_family"] == "specialty"
    assert case_map["chart_pdf_case"]["case_category"] == "chart"
    assert case_map["chart_pdf_case"]["query_count"] == 2
    assert case_map["line_chart_pdf_case"]["case_family"] == "specialty"
    assert case_map["line_chart_pdf_case"]["case_category"] == "chart"
    assert case_map["line_chart_pdf_case"]["query_count"] == 2
    assert case_map["two_column_pdf_case"]["case_family"] == "layout"
    assert case_map["cross_page_table_pdf_case"]["case_family"] == "table"
    assert case_map["multilingual_pdf_case"]["case_family"] == "document"
    assert case_map["multilingual_pdf_case"]["query_count"] == 2
    assert case_map["formula_markdown_case"]["case_family"] == "document"
    assert case_map["formula_markdown_case"]["query_count"] == 2

    report = runner_mod.run_batch(spec_path=out_path, out_dir=out_dir)  # type: ignore[attr-defined]
    assert report["cases_total"] == 14
    assert report["query_count_total"] == 28
    assert len(report["cases"]) == 14
    assert report["summary"]["hit_at_k_mean"] == 1.0
    assert report["summary"]["mrr_mean"] == 1.0
    assert report["case_family_counts"]["specialty"] == 5
    assert report["case_family_counts"]["table"] == 4
    assert report["case_family_counts"]["layout"] == 3
    assert report["case_family_counts"]["document"] == 2


def test_real_broader_sample_queries_are_case_specific() -> None:
    case_queries_path = _repo_root() / "tests" / "fixtures" / "parsing_retrieval_proof" / "broader_case_queries.sample.json"
    case_queries = json.loads(case_queries_path.read_text(encoding="utf-8"))

    banned_questions = {
        "What kind of image shows revenue growth?",
        "Which visual is a chart?",
        "Which visual is a workflow diagram?",
        "What type of image is shown on the page?",
        "Which region accelerated in Q3?",
        "What should appear after both text columns?",
        "What stayed flat?",
    }
    required_case_anchors = {
        "chart_pdf_case": ("chart image",),
        "line_chart_pdf_case": ("line chart", "trend chart"),
        "diagram_pdf_case": ("diagram image",),
        "qr_image_case": ("qr", "hello-qr"),
        "barcode_image_case": ("barcode", "5901234123457"),
        "cross_page_table_pdf_case": ("apac", "138"),
        "borderless_table_scan_case": ("inventory snapshot", "paper", "pens"),
        "merged_header_table_pdf_case": ("budget 2026", "approved and spent"),
        "table_with_leading_paragraph_pdf_case": ("97%", "leading paragraph"),
        "two_column_pdf_case": ("two-column", "stayed flat"),
        "header_footer_noise_pdf_case": ("quarterly operations report", "customer churn"),
        "mixed_layout_pdf_case": ("mixed layout", "two-column content"),
        "multilingual_pdf_case": ("apac revenue", "94%"),
        "formula_markdown_case": ("e = mc^2", "core formula"),
    }

    assert set(case_queries) == set(required_case_anchors)
    for case_id, anchors in required_case_anchors.items():
        query_rel_path = str(case_queries[case_id]["queries_json"])
        query_path = (_repo_root() / query_rel_path).resolve()
        questions = [
            str(item.get("question") or "").strip()
            for item in json.loads(query_path.read_text(encoding="utf-8"))
            if isinstance(item, dict)
        ]
        lowered = [question.lower() for question in questions]
        assert len(questions) == 2
        assert len(set(questions)) == len(questions)
        assert all(question.endswith("?") for question in questions)
        assert all(len(question.split()) >= 5 for question in questions)
        assert not any(question in banned_questions for question in questions)
        assert any(anchor in question for anchor in anchors for question in lowered), case_id
