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
    assert len(spec["cases"]) == 1
    assert spec["cases"][0]["id"] == "case-a"
    assert spec["cases"][0]["parser_backend"] == "basic"
    assert spec["cases"][0]["top_k"] == 2
    assert spec["cases"][0]["retrieval_mode"] == "keyword"


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
    assert payload["cases"][0]["id"] == "case-a"
    assert payload["cases"][0]["parser_backend"] == "basic"


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
    assert [item["id"] for item in payload["cases"]] == [
        "chart_pdf_case",
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
    ]

    report = runner_mod.run_batch(spec_path=out_path, out_dir=out_dir)  # type: ignore[attr-defined]
    assert report["cases_total"] == 11
    assert report["summary"]["hit_at_k_mean"] == 1.0
    assert report["summary"]["mrr_mean"] == 1.0
