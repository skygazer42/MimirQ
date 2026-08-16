import json
from pathlib import Path

from app.rag.evaluation.parse_bench.__main__ import main


def test_parse_bench_cli_builds_doc_type_matrix(tmp_path: Path) -> None:
    out_path = tmp_path / "parse_bench.json"

    rc = main(
        [
            "run",
            "--input-dir",
            "tests/fixtures/parsing_golden",
            "--manifest",
            "tests/fixtures/parsing_golden/manifest.json",
            "--parsers",
            "basic",
            "--out",
            str(out_path),
            "--max-files",
            "6",
        ]
    )

    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "mimirq.parser_benchmark.v1"
    assert "doc_type_matrix" in payload
    assert "basic" in payload["doc_type_matrix"]
    assert any(row.get("text_edit_similarity_mean") is not None for row in payload["doc_type_matrix"]["basic"].values())
