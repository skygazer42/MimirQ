from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script():
    path = _repo_root() / "scripts" / "run_parsing_retrieval_proof_from_file.py"
    spec = importlib.util.spec_from_file_location("run_parsing_retrieval_proof_from_file", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_run_parsing_retrieval_proof_from_file_writes_fixture_and_report(tmp_path: Path) -> None:
    mod = _load_script()
    fixture_path = tmp_path / "fixture.json"
    report_path = tmp_path / "report.json"
    queries_path = tmp_path / "queries.json"

    queries_path.write_text(
        json.dumps(
            [
                {
                    "id": "q-borderless",
                    "question": "Which warehouse stores Paper?",
                    "expected_chunk_indexes": [0],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = mod.run_parsing_retrieval_proof_from_file(  # type: ignore[attr-defined]
        input_file=_repo_root() / "tests" / "fixtures" / "parsing_golden_broader" / "borderless_table_scan" / "input" / "sample.png",
        queries_path=queries_path,
        fixture_output_path=fixture_path,
        report_output_path=report_path,
        parser_backend="image",
        top_k=1,
        retrieval_mode="keyword",
    )

    assert fixture_path.exists()
    assert report_path.exists()
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["documents"][0]["metadata"]["doc_type_kwd"] == "table"
    assert report["summary"]["hit_at_k"] == 1.0
    assert report["summary"]["mrr"] == 1.0


def test_run_parsing_retrieval_proof_from_file_cli_accepts_pdf_parser_output(tmp_path: Path) -> None:
    mod = _load_script()
    fixture_path = tmp_path / "fixture.json"
    report_path = tmp_path / "report.json"
    queries_path = tmp_path / "queries.json"

    queries_path.write_text(
        json.dumps(
            [
                {
                    "id": "q-cross-page",
                    "question": "What is APAC Q2 revenue?",
                    "expected_chunk_indexes": [1],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--input-file",
            str(_repo_root() / "tests" / "fixtures" / "parsing_golden_broader" / "cross_page_table_pdf" / "input" / "sample.pdf"),
            "--queries-json",
            str(queries_path),
            "--fixture-out",
            str(fixture_path),
            "--report-out",
            str(report_path),
            "--parser-backend",
            "basic",
            "--top-k",
            "2",
            "--retrieval-mode",
            "keyword",
        ]
    )

    assert rc == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["hit_at_k"] == 1.0
    assert report["summary"]["mrr"] == 1.0


def test_run_parsing_retrieval_proof_from_file_augments_handwriting_image_with_local_ocr(tmp_path: Path) -> None:
    mod = _load_script()
    fixture_path = tmp_path / "fixture.json"
    report_path = tmp_path / "report.json"
    queries_path = tmp_path / "queries.json"

    queries_path.write_text(
        json.dumps(
            [
                {
                    "id": "q-handwriting",
                    "question": "What number is written in the handwritten approval note?",
                    "expected_chunk_indexes": [0],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = mod.run_parsing_retrieval_proof_from_file(  # type: ignore[attr-defined]
        input_file=_repo_root() / "tests" / "fixtures" / "parsing_golden_broader" / "handwriting_note_image" / "input" / "sample.png",
        queries_path=queries_path,
        fixture_output_path=fixture_path,
        report_output_path=report_path,
        parser_backend="image",
        top_k=1,
        retrieval_mode="keyword",
    )

    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert "Image OCR:" in fixture["documents"][0]["text"]
    assert "Approved72" in fixture["documents"][0]["text"]
    assert report["summary"]["hit_at_k"] == 1.0
    assert report["summary"]["mrr"] == 1.0


def test_run_parsing_retrieval_proof_from_file_applies_governance_rule_packs(tmp_path: Path) -> None:
    mod = _load_script()
    fixture_path = tmp_path / "fixture.json"
    report_path = tmp_path / "report.json"
    queries_path = tmp_path / "queries.json"

    queries_path.write_text(
        json.dumps(
            [
                {
                    "id": "q-watermark",
                    "question": "In the watermark-heavy memo, what date is the launch rehearsal?",
                    "expected_chunk_indexes": [0],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = mod.run_parsing_retrieval_proof_from_file(  # type: ignore[attr-defined]
        input_file=_repo_root() / "tests" / "fixtures" / "parsing_golden_broader" / "watermark_heavy_pdf" / "input" / "sample.pdf",
        queries_path=queries_path,
        fixture_output_path=fixture_path,
        report_output_path=report_path,
        parser_backend="basic",
        top_k=1,
        retrieval_mode="keyword",
        governance_rule_packs=["pdf_watermark"],
    )

    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    text = fixture["documents"][0]["text"]
    assert "DRAFT" not in text
    assert "Company Confidential" not in text
    assert "仅供内部使用" not in text
    assert "Launch rehearsal: 2026-05-03" in text
    assert report["summary"]["hit_at_k"] == 1.0
    assert report["summary"]["mrr"] == 1.0
