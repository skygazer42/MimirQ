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


def test_build_parsing_retrieval_fixture_from_file_round_trips_real_image_parser_output(tmp_path: Path) -> None:
    build_mod = _load_script("scripts/build_parsing_retrieval_fixture_from_file.py")
    bench_mod = _load_script("scripts/run_sample_retrieval_benchmark.py")

    queries_path = tmp_path / "queries.json"
    fixture_path = tmp_path / "fixture.json"
    report_path = tmp_path / "report.json"

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

    rc = build_mod.main(  # type: ignore[attr-defined]
        [
            "--input-file",
            str(_repo_root() / "tests" / "fixtures" / "parsing_golden_broader" / "borderless_table_scan" / "input" / "sample.png"),
            "--queries-json",
            str(queries_path),
            "--out",
            str(fixture_path),
            "--parser-backend",
            "image",
            "--top-k",
            "1",
            "--retrieval-mode",
            "keyword",
        ]
    )

    assert rc == 0
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "mimirq.sample_retrieval_fixture.v1"
    assert payload["documents"][0]["metadata"]["doc_type_kwd"] == "table"

    report = bench_mod.run_benchmark(  # type: ignore[attr-defined]
        fixture_path=fixture_path,
        output_path=report_path,
        top_k=1,
        retrieval_mode="keyword",
    )

    assert report["summary"]["hit_at_k"] == 1.0
    assert report["summary"]["mrr"] == 1.0
