from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script(rel_path: str):
    path = _repo_root() / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _fixture_helper():
    return _load_script("scripts/build_parsing_retrieval_fixture.py")


def test_stronger_layout_parsing_fixture_beats_weaker_layout_parsing_in_retrieval(tmp_path: Path) -> None:
    mod = _load_script("scripts/run_sample_retrieval_benchmark.py")
    helper = _fixture_helper()

    strong_fixture = helper.build_retrieval_fixture(  # type: ignore[attr-defined]
        documents=[
            {"chunk_id": "layout_answer", "document_id": "layout-doc", "text": "East region revenue accelerated in Q3.", "metadata": {}},
            {"chunk_id": "layout_noise", "document_id": "layout-doc", "text": "North region revenue increased steadily.", "metadata": {}},
        ],
        queries=[{"id": "layout-q1", "question": "Which region accelerated in Q3?", "expected_chunk_ids": ["layout_answer"]}],
        top_k=1,
        retrieval_mode="keyword",
    )
    weak_fixture = helper.build_retrieval_fixture(  # type: ignore[attr-defined]
        documents=[
            {"chunk_id": "layout_answer", "document_id": "layout-doc", "text": "East region", "metadata": {}},
            {"chunk_id": "layout_split_tail", "document_id": "layout-doc", "text": "accelerated in Q3", "metadata": {}},
            {"chunk_id": "layout_noise", "document_id": "layout-doc", "text": "North region revenue increased steadily.", "metadata": {}},
        ],
        queries=[{"id": "layout-q1", "question": "Which region accelerated in Q3?", "expected_chunk_ids": ["layout_answer"]}],
        top_k=1,
        retrieval_mode="keyword",
    )

    strong_path = tmp_path / "layout-strong.fixture.json"
    weak_path = tmp_path / "layout-weak.fixture.json"
    strong_path.write_text(__import__("json").dumps(strong_fixture, ensure_ascii=False), encoding="utf-8")
    weak_path.write_text(__import__("json").dumps(weak_fixture, ensure_ascii=False), encoding="utf-8")

    strong = mod.run_benchmark(  # type: ignore[attr-defined]
        fixture_path=strong_path,
        output_path=tmp_path / "strong.json",
        top_k=1,
        retrieval_mode="keyword",
    )
    weak = mod.run_benchmark(  # type: ignore[attr-defined]
        fixture_path=weak_path,
        output_path=tmp_path / "weak.json",
        top_k=1,
        retrieval_mode="keyword",
    )

    strong_summary = strong["summary"]
    weak_summary = weak["summary"]

    assert strong_summary["hit_at_k"] == 1.0
    assert strong_summary["mrr"] == 1.0
    assert weak_summary["hit_at_k"] < strong_summary["hit_at_k"]
    assert weak_summary["mrr"] < strong_summary["mrr"]


def test_stronger_table_parsing_fixture_beats_weaker_table_parsing_in_retrieval(tmp_path: Path) -> None:
    mod = _load_script("scripts/run_sample_retrieval_benchmark.py")
    helper = _fixture_helper()

    strong_fixture = helper.build_retrieval_fixture(  # type: ignore[attr-defined]
        documents=[
            {"chunk_id": "table_answer", "document_id": "table-doc", "text": "APAC Q2 revenue amount 138", "metadata": {}},
            {"chunk_id": "noise1", "document_id": "noise-doc", "text": "APAC value 126", "metadata": {}},
            {"chunk_id": "noise2", "document_id": "noise-doc", "text": "Q2 revenue 132 North", "metadata": {}},
        ],
        queries=[
            {
                "id": "table-q1",
                "question": "For APAC, what is the Q2 revenue amount?",
                "expected_chunk_ids": ["table_answer"],
            }
        ],
        top_k=1,
        retrieval_mode="keyword",
    )
    weak_fixture = helper.build_retrieval_fixture(  # type: ignore[attr-defined]
        documents=[
            {"chunk_id": "table_answer", "document_id": "table-doc", "text": "APAC revenue", "metadata": {}},
            {"chunk_id": "table_split", "document_id": "table-doc", "text": "APAC Q2 revenue amount 138", "metadata": {}},
            {"chunk_id": "noise1", "document_id": "noise-doc", "text": "APAC value 126", "metadata": {}},
            {"chunk_id": "noise2", "document_id": "noise-doc", "text": "Q2 revenue 132 North", "metadata": {}},
        ],
        queries=[
            {
                "id": "table-q1",
                "question": "For APAC, what is the Q2 revenue amount?",
                "expected_chunk_ids": ["table_answer"],
            }
        ],
        top_k=1,
        retrieval_mode="keyword",
    )

    strong_path = tmp_path / "table-strong.fixture.json"
    weak_path = tmp_path / "table-weak.fixture.json"
    strong_path.write_text(__import__("json").dumps(strong_fixture, ensure_ascii=False), encoding="utf-8")
    weak_path.write_text(__import__("json").dumps(weak_fixture, ensure_ascii=False), encoding="utf-8")

    strong = mod.run_benchmark(  # type: ignore[attr-defined]
        fixture_path=strong_path,
        output_path=tmp_path / "table-strong.json",
        top_k=1,
        retrieval_mode="keyword",
    )
    weak = mod.run_benchmark(  # type: ignore[attr-defined]
        fixture_path=weak_path,
        output_path=tmp_path / "table-weak.json",
        top_k=1,
        retrieval_mode="keyword",
    )

    strong_summary = strong["summary"]
    weak_summary = weak["summary"]

    assert strong_summary["hit_at_k"] == 1.0
    assert strong_summary["mrr"] == 1.0
    assert weak_summary["hit_at_k"] == 0.0
    assert weak_summary["mrr"] == 0.0


def test_stronger_table_parsing_preserves_cross_page_extract_evidence() -> None:
    from app.services.parsing_extract_service import extract_parsing_fields  # noqa: WPS433

    strong = extract_parsing_fields(
        markdown=(
            "Quarterly revenue by region.\n\n"
            "| Region | Q1 | Q2 |\n"
            "| --- | --- | --- |\n"
            "| North | 120 | 132 |\n"
            "| South | 98 | 110 |\n"
            "| West | 115 | 121 |\n"
            "| East | 107 | 116 |\n"
            "| Central | 111 | 119 |\n"
            "| APAC | 126 | 138 |"
        ),
        elements=[
            {
                "id": "table:1:0",
                "kind": "table",
                "page": 1,
                "pages": [1, 2],
                "text": (
                    "| Region | Q1 | Q2 |\n"
                    "| --- | --- | --- |\n"
                    "| North | 120 | 132 |\n"
                    "| South | 98 | 110 |\n"
                    "| West | 115 | 121 |\n"
                    "| East | 107 | 116 |\n"
                    "| Central | 111 | 119 |\n"
                    "| APAC | 126 | 138 |"
                ),
                "confidence": 0.92,
                "bbox": {"x0": 10, "y0": 20, "x1": 300, "y1": 520},
                "attributes": {},
            }
        ],
        mode="schema",
        schema={"apac_table": {"type": "string", "source_kind": "table", "aliases": ["APAC"]}},
    )

    weak = extract_parsing_fields(
        markdown=(
            "Quarterly revenue by region.\n\n"
            "| Region | Q1 | Q2 |\n"
            "| --- | --- | --- |\n"
            "| North | 120 | 132 |\n"
            "| South | 98 | 110 |\n"
            "| West | 115 | 121 |"
        ),
        elements=[
            {
                "id": "table:1:0",
                "kind": "table",
                "page": 1,
                "text": (
                    "| Region | Q1 | Q2 |\n"
                    "| --- | --- | --- |\n"
                    "| North | 120 | 132 |\n"
                    "| South | 98 | 110 |\n"
                    "| West | 115 | 121 |"
                ),
                "confidence": 0.45,
                "bbox": {"x0": 10, "y0": 20, "x1": 300, "y1": 260},
                "attributes": {},
            }
        ],
        mode="schema",
        schema={"apac_table": {"type": "string", "source_kind": "table", "aliases": ["APAC"]}},
    )

    strong_field = strong["apac_table"]
    weak_field = weak["apac_table"]

    assert "APAC" in str(strong_field["value"] or "")
    assert strong_field["strategy"] == "element_match"
    assert strong_field["evidence"][0]["pages"] == [1, 2]
    assert strong_field["evidence"][0]["bbox"]["x0"] == 10
    assert "APAC" not in str(weak_field["value"] or "")
    assert weak_field["strategy"] == "element_match"
    assert weak_field["evidence"][0]["pages"] is None
    assert float(strong_field["confidence"] or 0.0) > float(weak_field["confidence"] or 0.0)
