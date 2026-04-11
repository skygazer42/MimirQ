from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script():
    path = _repo_root() / "scripts" / "run_parsing_retrieval_proof.py"
    spec = importlib.util.spec_from_file_location("run_parsing_retrieval_proof", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_run_parsing_retrieval_proof_writes_fixture_and_report(tmp_path: Path) -> None:
    mod = _load_script()
    docs_path = tmp_path / "documents.json"
    queries_path = tmp_path / "queries.json"
    fixture_path = tmp_path / "fixture.json"
    report_path = tmp_path / "report.json"

    docs_path.write_text(
        json.dumps(
            [
                {
                    "chunk_id": "layout-answer",
                    "document_id": "layout-doc",
                    "page_content": "East region revenue accelerated in Q3.",
                    "metadata": {"source": "layout.md"},
                },
                {
                    "chunk_id": "layout-noise",
                    "document_id": "layout-doc",
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
                    "expected_chunk_ids": ["layout-answer"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = mod.run_parsing_retrieval_proof(  # type: ignore[attr-defined]
        documents_path=docs_path,
        queries_path=queries_path,
        fixture_output_path=fixture_path,
        report_output_path=report_path,
        top_k=1,
        retrieval_mode="keyword",
    )

    assert fixture_path.exists()
    assert report_path.exists()
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["queries"][0]["expected_chunk_ids"] == ["layout-answer"]
    assert report["summary"]["hit_at_k"] == 1.0
    assert report["summary"]["mrr"] == 1.0


def test_run_parsing_retrieval_proof_cli_accepts_preview_segments_payload(tmp_path: Path) -> None:
    mod = _load_script()
    docs_path = tmp_path / "preview.json"
    queries_path = tmp_path / "queries.json"
    fixture_path = tmp_path / "fixture.json"
    report_path = tmp_path / "report.json"

    docs_path.write_text(
        json.dumps(
            {
                "parser_backend": "basic",
                "segments": [
                    {"id": "seg-answer", "text": "East region revenue accelerated in Q3.", "page": 1},
                    {"id": "seg-noise", "text": "North region revenue increased steadily.", "page": 1},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    queries_path.write_text(
        json.dumps(
            [{"id": "q-layout", "question": "Which region accelerated in Q3?", "expected_chunk_ids": ["seg-answer"]}],
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
            "--fixture-out",
            str(fixture_path),
            "--report-out",
            str(report_path),
            "--top-k",
            "1",
            "--retrieval-mode",
            "keyword",
        ]
    )

    assert rc == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["hit_at_k"] == 1.0
    assert report["summary"]["mrr"] == 1.0
