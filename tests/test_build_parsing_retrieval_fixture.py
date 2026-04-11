from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script():
    path = _repo_root() / "scripts" / "build_parsing_retrieval_fixture.py"
    spec = importlib.util.spec_from_file_location("build_parsing_retrieval_fixture", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_retrieval_fixture_normalizes_parser_like_documents() -> None:
    mod = _load_script()

    payload = mod.build_retrieval_fixture(  # type: ignore[attr-defined]
        documents=[
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "page_content": "APAC Q2 revenue amount 138",
                "metadata": {"source": "parsed.md"},
            }
        ],
        queries=[
            {
                "id": "q1",
                "question": "For APAC, what is the Q2 revenue amount?",
                "expected_chunk_indexes": [0],
            }
        ],
        top_k=1,
        retrieval_mode="keyword",
    )

    assert payload["schema"] == "mimirq.sample_retrieval_fixture.v1"
    assert payload["defaults"]["top_k"] == 1
    assert payload["defaults"]["retrieval_mode"] == "keyword"
    assert payload["documents"][0]["chunk_id"] == "chunk-1"
    assert payload["documents"][0]["document_id"] == "doc-1"
    assert payload["documents"][0]["text"] == "APAC Q2 revenue amount 138"
    assert payload["queries"][0]["expected_chunk_ids"] == ["chunk-1"]


def test_build_retrieval_fixture_cli_writes_json(tmp_path: Path) -> None:
    mod = _load_script()
    docs_path = tmp_path / "documents.json"
    queries_path = tmp_path / "queries.json"
    out_path = tmp_path / "fixture.json"

    docs_path.write_text(
        json.dumps(
            [
                {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "page_content": "East region revenue accelerated in Q3.",
                    "metadata": {"source": "layout.md"},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    queries_path.write_text(
        json.dumps(
            [
                {
                    "id": "q1",
                    "question": "Which region accelerated in Q3?",
                    "expected_chunk_indexes": [0],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--documents-json",
            str(docs_path),
            "--queries-json",
            str(queries_path),
            "--out",
            str(out_path),
            "--top-k",
            "1",
            "--retrieval-mode",
            "keyword",
        ]
    )

    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "mimirq.sample_retrieval_fixture.v1"
    assert payload["queries"][0]["expected_chunk_ids"] == ["chunk-1"]


def test_generated_fixture_can_run_in_sample_retrieval_benchmark(tmp_path: Path) -> None:
    build_mod = _load_script()

    bench_path = _repo_root() / "scripts" / "run_sample_retrieval_benchmark.py"
    spec = importlib.util.spec_from_file_location("run_sample_retrieval_benchmark", str(bench_path))
    assert spec and spec.loader
    bench_mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = bench_mod
    spec.loader.exec_module(bench_mod)  # type: ignore[union-attr]

    docs_path = tmp_path / "documents.json"
    queries_path = tmp_path / "queries.json"
    fixture_path = tmp_path / "fixture.json"
    report_path = tmp_path / "report.json"

    docs_path.write_text(
        json.dumps(
            [
                {
                    "chunk_id": "chunk-answer",
                    "document_id": "doc-layout",
                    "page_content": "East region revenue accelerated in Q3.",
                    "metadata": {"source": "layout.md"},
                },
                {
                    "chunk_id": "chunk-noise",
                    "document_id": "doc-layout",
                    "page_content": "North region revenue increased steadily.",
                    "metadata": {"source": "layout.md"},
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
                    "id": "q-layout",
                    "question": "Which region accelerated in Q3?",
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


def test_helper_generated_strong_and_weak_table_fixtures_separate_retrieval_outcomes(tmp_path: Path) -> None:
    build_mod = _load_script()

    bench_path = _repo_root() / "scripts" / "run_sample_retrieval_benchmark.py"
    spec = importlib.util.spec_from_file_location("run_sample_retrieval_benchmark", str(bench_path))
    assert spec and spec.loader
    bench_mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = bench_mod
    spec.loader.exec_module(bench_mod)  # type: ignore[union-attr]

    strong_docs_path = tmp_path / "strong-docs.json"
    weak_docs_path = tmp_path / "weak-docs.json"
    queries_path = tmp_path / "queries.json"
    strong_fixture_path = tmp_path / "strong-fixture.json"
    weak_fixture_path = tmp_path / "weak-fixture.json"

    strong_docs_path.write_text(
        json.dumps(
            [
                {
                    "page_content": "APAC Q2 revenue amount 138",
                    "metadata": {"chunk_id": "table-answer", "document_id": "doc-table", "source": "strong.md"},
                },
                {
                    "page_content": "APAC value 126",
                    "metadata": {"chunk_id": "noise-1", "document_id": "doc-noise", "source": "noise.md"},
                },
                {
                    "page_content": "Q2 revenue 132 North",
                    "metadata": {"chunk_id": "noise-2", "document_id": "doc-noise", "source": "noise.md"},
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    weak_docs_path.write_text(
        json.dumps(
            [
                {
                    "page_content": "APAC revenue",
                    "metadata": {"chunk_id": "table-answer", "document_id": "doc-table", "source": "weak.md"},
                },
                {
                    "page_content": "APAC Q2 revenue amount 138",
                    "metadata": {"chunk_id": "table-split", "document_id": "doc-table", "source": "weak.md"},
                },
                {
                    "page_content": "APAC value 126",
                    "metadata": {"chunk_id": "noise-1", "document_id": "doc-noise", "source": "noise.md"},
                },
                {
                    "page_content": "Q2 revenue 132 North",
                    "metadata": {"chunk_id": "noise-2", "document_id": "doc-noise", "source": "noise.md"},
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
                    "expected_chunk_ids": ["table-answer"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = build_mod.main(  # type: ignore[attr-defined]
        ["--documents-json", str(strong_docs_path), "--queries-json", str(queries_path), "--out", str(strong_fixture_path)]
    )
    assert rc == 0
    rc = build_mod.main(  # type: ignore[attr-defined]
        ["--documents-json", str(weak_docs_path), "--queries-json", str(queries_path), "--out", str(weak_fixture_path)]
    )
    assert rc == 0

    strong_report = bench_mod.run_benchmark(  # type: ignore[attr-defined]
        fixture_path=strong_fixture_path,
        output_path=tmp_path / "strong-report.json",
        top_k=1,
        retrieval_mode="keyword",
    )
    weak_report = bench_mod.run_benchmark(  # type: ignore[attr-defined]
        fixture_path=weak_fixture_path,
        output_path=tmp_path / "weak-report.json",
        top_k=1,
        retrieval_mode="keyword",
    )

    assert strong_report["summary"]["hit_at_k"] == 1.0
    assert weak_report["summary"]["hit_at_k"] == 0.0


def test_build_fixture_accepts_flat_parser_element_shapes() -> None:
    mod = _load_script()

    payload = mod.build_fixture(  # type: ignore[attr-defined]
        documents=[
            {
                "element_id": "table:1:0",
                "element_text": "APAC Q2 revenue amount 138",
                "page": 1,
                "pages": [1, 2],
                "bbox": {"x0": 10, "y0": 20, "x1": 300, "y1": 520},
                "visual_kind": "table",
            }
        ],
        queries=[
            {
                "question": "For APAC, what is the Q2 revenue amount?",
                "expected_chunk_ids": ["table:1:0"],
            }
        ],
        top_k=1,
        retrieval_mode="keyword",
    )

    doc = payload["documents"][0]
    assert doc["chunk_id"] == "table:1:0"
    assert doc["text"] == "APAC Q2 revenue amount 138"
    assert doc["metadata"]["page"] == 1
    assert doc["metadata"]["pages"] == [1, 2]
    assert doc["metadata"]["bbox"] == {"x0": 10, "y0": 20, "x1": 300, "y1": 520}
    assert doc["metadata"]["visual_kind"] == "table"


def test_build_fixture_accepts_preview_segments_payload_shape() -> None:
    mod = _load_script()

    payload = mod.build_fixture(  # type: ignore[attr-defined]
        documents=[
            {
                "id": "seg-1",
                "text": "East region revenue accelerated in Q3.",
                "page": 1,
                "bbox": {"x0": 1, "y0": 2, "x1": 3, "y1": 4},
            }
        ],
        queries=[
            {
                "question": "Which region accelerated in Q3?",
                "expected_chunk_ids": ["seg-1"],
            }
        ],
        top_k=1,
        retrieval_mode="keyword",
    )

    doc = payload["documents"][0]
    assert doc["chunk_id"] == "seg-1"
    assert doc["text"] == "East region revenue accelerated in Q3."
    assert doc["metadata"]["page"] == 1
    assert doc["metadata"]["bbox"] == {"x0": 1, "y0": 2, "x1": 3, "y1": 4}


def test_build_fixture_cli_accepts_root_object_with_segments_array(tmp_path: Path) -> None:
    mod = _load_script()
    docs_path = tmp_path / "preview.json"
    queries_path = tmp_path / "queries.json"
    out_path = tmp_path / "fixture.json"

    docs_path.write_text(
        json.dumps(
            {
                "parser_backend": "basic",
                "segments": [
                    {
                        "id": "seg-1",
                        "text": "East region revenue accelerated in Q3.",
                        "page": 1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    queries_path.write_text(
        json.dumps(
            [
                {
                    "id": "q1",
                    "question": "Which region accelerated in Q3?",
                    "expected_chunk_ids": ["seg-1"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--documents-json",
            str(docs_path),
            "--queries-json",
            str(queries_path),
            "--out",
            str(out_path),
        ]
    )

    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["documents"][0]["chunk_id"] == "seg-1"
