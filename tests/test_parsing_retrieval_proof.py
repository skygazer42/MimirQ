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


def test_stronger_layout_parsing_fixture_beats_weaker_layout_parsing_in_retrieval(tmp_path: Path) -> None:
    mod = _load_script("scripts/run_sample_retrieval_benchmark.py")
    fixture_root = _repo_root() / "tests" / "fixtures" / "parsing_retrieval_proof"

    strong = mod.run_benchmark(  # type: ignore[attr-defined]
        fixture_path=fixture_root / "layout_strong.fixture.json",
        output_path=tmp_path / "strong.json",
        top_k=1,
        retrieval_mode="keyword",
    )
    weak = mod.run_benchmark(  # type: ignore[attr-defined]
        fixture_path=fixture_root / "layout_weak.fixture.json",
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
    fixture_root = _repo_root() / "tests" / "fixtures" / "parsing_retrieval_proof"

    strong = mod.run_benchmark(  # type: ignore[attr-defined]
        fixture_path=fixture_root / "table_strong.fixture.json",
        output_path=tmp_path / "table-strong.json",
        top_k=1,
        retrieval_mode="keyword",
    )
    weak = mod.run_benchmark(  # type: ignore[attr-defined]
        fixture_path=fixture_root / "table_weak.fixture.json",
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
