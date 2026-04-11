from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script(rel: str):
    path = _repo_root() / rel
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_fixture_helper_round_trips_into_sample_retrieval_benchmark(tmp_path: Path) -> None:
    build_mod = _load_script("scripts/build_parsing_retrieval_fixture.py")
    bench_mod = _load_script("scripts/run_sample_retrieval_benchmark.py")

    docs_path = tmp_path / "documents.json"
    queries_path = tmp_path / "queries.json"
    fixture_path = tmp_path / "fixture.json"
    report_path = tmp_path / "report.json"

    docs_path.write_text(
        json.dumps(
            [
                {
                    "chunk_id": "table-answer",
                    "document_id": "doc-table",
                    "page_content": "APAC Q2 revenue amount 138",
                    "metadata": {"source": "parsed-strong.md"},
                },
                {
                    "chunk_id": "noise-1",
                    "document_id": "doc-noise",
                    "page_content": "APAC value 126",
                    "metadata": {"source": "noise.md"},
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    queries_path.write_text(
        json.dumps(
            [
                {
                    "id": "q-table",
                    "question": "For APAC, what is the Q2 revenue amount?",
                    "expected_chunk_indexes": [0],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = build_mod.main(  # type: ignore[attr-defined]
        [
            "--documents-json",
            str(docs_path),
            "--queries-json",
            str(queries_path),
            "--out",
            str(fixture_path),
            "--top-k",
            "1",
            "--retrieval-mode",
            "keyword",
        ]
    )

    assert rc == 0

    report = bench_mod.run_benchmark(  # type: ignore[attr-defined]
        fixture_path=fixture_path,
        output_path=report_path,
        top_k=1,
        retrieval_mode="keyword",
    )

    assert report["summary"]["hit_at_k"] == 1.0
    assert report["summary"]["mrr"] == 1.0
    assert report["cases"][0]["ranked_chunk_ids"] == ["table-answer"]


def test_real_pdf_parser_output_can_round_trip_through_helper_and_benchmark(tmp_path: Path) -> None:
    build_mod = _load_script("scripts/build_parsing_retrieval_fixture.py")
    bench_mod = _load_script("scripts/run_sample_retrieval_benchmark.py")

    from app.parsing.parsers.pdf_parser import PDFParser  # noqa: WPS433

    docs = PDFParser().parse(Path("tests/fixtures/parsing_golden_broader/cross_page_table_pdf/input/sample.pdf"))
    docs_path = tmp_path / "documents.json"
    queries_path = tmp_path / "queries.json"
    fixture_path = tmp_path / "fixture.json"
    report_path = tmp_path / "report.json"

    docs_path.write_text(
        json.dumps(
            [{"page_content": doc.page_content, "metadata": dict(doc.metadata or {})} for doc in docs],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
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

    rc = build_mod.main(  # type: ignore[attr-defined]
        [
            "--documents-json",
            str(docs_path),
            "--queries-json",
            str(queries_path),
            "--out",
            str(fixture_path),
            "--top-k",
            "2",
            "--retrieval-mode",
            "keyword",
        ]
    )

    assert rc == 0

    report = bench_mod.run_benchmark(  # type: ignore[attr-defined]
        fixture_path=fixture_path,
        output_path=report_path,
        top_k=2,
        retrieval_mode="keyword",
    )

    assert report["summary"]["hit_at_k"] == 1.0
    assert report["summary"]["mrr"] == 1.0
    assert report["cases"][0]["ranked_chunk_ids"][0].startswith("chunk-")
