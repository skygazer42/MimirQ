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


def test_build_fixture_normalizes_parser_chunks_and_queries() -> None:
    mod = _load_script("scripts/build_parsing_retrieval_fixture.py")

    fixture = mod.build_fixture(  # type: ignore[attr-defined]
        documents=[
            {
                "page_content": "APAC Q2 revenue amount 138",
                "metadata": {"chunk_id": "chunk-a", "document_id": "doc-1", "source": "demo.md"},
            },
            {
                "chunk_id": "chunk-b",
                "text": "North Q2 revenue amount 132",
                "metadata": {"document_id": "doc-1"},
            },
        ],
        queries=[
            {"question": "What is APAC Q2 revenue?", "expected_chunk_ids": ["chunk-a", "chunk-a", ""]},
        ],
        top_k=3,
        retrieval_mode="keyword",
    )

    assert fixture["schema"] == "mimirq.sample_retrieval_fixture.v1"
    assert fixture["defaults"]["top_k"] == 3
    assert fixture["documents"][0]["chunk_id"] == "chunk-a"
    assert fixture["documents"][0]["document_id"] == "doc-1"
    assert fixture["documents"][0]["metadata"]["source"] == "demo.md"
    assert fixture["documents"][1]["chunk_id"] == "chunk-b"
    assert fixture["queries"][0]["expected_chunk_ids"] == ["chunk-a"]


def test_build_fixture_cli_writes_stable_json(tmp_path: Path) -> None:
    mod = _load_script("scripts/build_parsing_retrieval_fixture.py")

    chunks = tmp_path / "chunks.json"
    queries = tmp_path / "queries.json"
    out = tmp_path / "fixture.json"
    chunks.write_text(
        json.dumps(
            [
                {
                    "page_content": "East region revenue accelerated in Q3.",
                    "metadata": {"chunk_id": "layout-answer", "document_id": "doc-layout"},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    queries.write_text(
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

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--chunks-json",
            str(chunks),
            "--queries-json",
            str(queries),
            "--out",
            str(out),
            "--top-k",
            "1",
            "--retrieval-mode",
            "keyword",
        ]
    )

    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema"] == "mimirq.sample_retrieval_fixture.v1"
    assert payload["documents"][0]["chunk_id"] == "layout-answer"
    assert payload["queries"][0]["id"] == "q-layout"


def test_build_fixture_accepts_flat_parser_element_shapes() -> None:
    mod = _load_script("scripts/build_parsing_retrieval_fixture.py")

    fixture = mod.build_fixture(  # type: ignore[attr-defined]
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
        queries=[{"question": "What is APAC Q2 revenue?", "expected_chunk_ids": ["table:1:0"]}],
        top_k=1,
        retrieval_mode="keyword",
    )

    doc = fixture["documents"][0]
    assert doc["chunk_id"] == "table:1:0"
    assert doc["text"] == "APAC Q2 revenue amount 138"
    assert doc["metadata"]["page"] == 1
    assert doc["metadata"]["pages"] == [1, 2]
    assert doc["metadata"]["bbox"] == {"x0": 10, "y0": 20, "x1": 300, "y1": 520}
    assert doc["metadata"]["visual_kind"] == "table"
