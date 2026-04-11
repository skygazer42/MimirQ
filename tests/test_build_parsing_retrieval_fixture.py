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


def test_build_retrieval_fixture_emits_sample_retrieval_schema() -> None:
    mod = _load_script()

    payload = mod.build_retrieval_fixture(  # type: ignore[attr-defined]
        documents=[
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "text": "APAC Q2 revenue amount 138",
                "metadata": {"source": "strong.md"},
            }
        ],
        queries=[
            {
                "id": "q1",
                "question": "For APAC, what is the Q2 revenue amount?",
                "expected_chunk_ids": ["chunk-1"],
            }
        ],
        top_k=1,
        retrieval_mode="keyword",
    )

    assert payload["schema"] == "mimirq.sample_retrieval_fixture.v1"
    assert payload["defaults"]["top_k"] == 1
    assert payload["defaults"]["retrieval_mode"] == "keyword"
    assert payload["documents"][0]["chunk_id"] == "chunk-1"
    assert payload["queries"][0]["expected_chunk_ids"] == ["chunk-1"]


def test_build_retrieval_fixture_cli_writes_json(tmp_path: Path, monkeypatch) -> None:
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
                    "text": "East region revenue accelerated in Q3.",
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
                    "expected_chunk_ids": ["chunk-1"],
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
    assert payload["queries"][0]["question"] == "Which region accelerated in Q3?"
