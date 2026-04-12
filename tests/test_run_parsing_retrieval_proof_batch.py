from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script():
    path = _repo_root() / "scripts" / "run_parsing_retrieval_proof_batch.py"
    spec = importlib.util.spec_from_file_location("run_parsing_retrieval_proof_batch", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_run_parsing_retrieval_proof_batch_writes_per_case_outputs_and_summary(tmp_path: Path) -> None:
    mod = _load_script()
    spec_path = tmp_path / "batch.spec.json"
    out_dir = tmp_path / "proof-batch"

    q_table = tmp_path / "q-table.json"
    q_table.write_text(
        json.dumps(
            [{"id": "q-borderless", "question": "Which warehouse stores Paper?", "expected_chunk_indexes": [0]}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    q_layout = tmp_path / "q-layout.json"
    q_layout.write_text(
        json.dumps(
            [{"id": "q-layout", "question": "What is APAC Q2 revenue?", "expected_chunk_indexes": [1]}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    spec_path.write_text(
        json.dumps(
            {
                "schema": "mimirq.parsing_retrieval_proof_batch.v1",
                "defaults": {"top_k": 2, "retrieval_mode": "keyword"},
                "cases": [
                    {
                        "id": "borderless-table",
                        "input_file": str(
                            _repo_root()
                            / "tests"
                            / "fixtures"
                            / "parsing_golden_broader"
                            / "borderless_table_scan"
                            / "input"
                            / "sample.png"
                        ),
                        "queries_json": str(q_table),
                        "parser_backend": "image",
                    },
                    {
                        "id": "cross-page-table",
                        "input_file": str(
                            _repo_root()
                            / "tests"
                            / "fixtures"
                            / "parsing_golden_broader"
                            / "cross_page_table_pdf"
                            / "input"
                            / "sample.pdf"
                        ),
                        "queries_json": str(q_layout),
                        "parser_backend": "basic",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = mod.run_batch(spec_path=spec_path, out_dir=out_dir)  # type: ignore[attr-defined]

    assert report["cases_total"] == 2
    assert report["query_count_total"] == 2
    assert report["summary"]["hit_at_k_mean"] == 1.0
    assert report["summary"]["mrr_mean"] == 1.0
    assert report["provenance"]["spec_path"] == str(spec_path.resolve())
    assert report["case_family_counts"]["table"] == 2
    case_map = {item["id"]: item for item in report["cases"]}
    assert case_map["borderless-table"]["case_family"] == "table"
    assert case_map["borderless-table"]["case_category"] == "borderless_table_scan"
    assert case_map["borderless-table"]["query_count"] == 1
    assert case_map["borderless-table"]["provenance"]["queries_json"] == str(q_table.resolve())
    assert case_map["cross-page-table"]["case_family"] == "table"
    assert case_map["cross-page-table"]["case_category"] == "cross_page_table_pdf"
    assert case_map["cross-page-table"]["query_count"] == 1
    assert (out_dir / "borderless-table.fixture.json").exists()
    assert (out_dir / "borderless-table.report.json").exists()
    assert (out_dir / "cross-page-table.fixture.json").exists()
    assert (out_dir / "cross-page-table.report.json").exists()
    assert (out_dir / "batch.report.json").exists()


def test_run_parsing_retrieval_proof_batch_cli_writes_batch_report(tmp_path: Path) -> None:
    mod = _load_script()
    spec_path = tmp_path / "batch.spec.json"
    out_dir = tmp_path / "proof-batch"

    q_table = tmp_path / "q-table.json"
    q_table.write_text(
        json.dumps(
            [{"id": "q-borderless", "question": "Which warehouse stores Paper?", "expected_chunk_indexes": [0]}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    spec_path.write_text(
        json.dumps(
            {
                "schema": "mimirq.parsing_retrieval_proof_batch.v1",
                "cases": [
                    {
                        "id": "borderless-table",
                        "input_file": str(
                            _repo_root()
                            / "tests"
                            / "fixtures"
                            / "parsing_golden_broader"
                            / "borderless_table_scan"
                            / "input"
                            / "sample.png"
                        ),
                        "queries_json": str(q_table),
                        "parser_backend": "image",
                        "top_k": 1,
                        "retrieval_mode": "keyword",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--spec-json",
            str(spec_path),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    batch_report = json.loads((out_dir / "batch.report.json").read_text(encoding="utf-8"))
    assert batch_report["cases_total"] == 1
    assert batch_report["query_count_total"] == 1
    assert batch_report["summary"]["hit_at_k_mean"] == 1.0
    assert batch_report["provenance"]["spec_path"] == str(spec_path.resolve())
    assert batch_report["cases"][0]["case_family"] == "table"
    assert batch_report["cases"][0]["case_category"] == "borderless_table_scan"
    assert batch_report["cases"][0]["query_count"] == 1
