import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import chunk_preview_batch_eval as batch_eval


class _Dumpable:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def model_dump(self) -> dict[str, Any]:
        return self.value


def test_best_effort_offsets_preserve_forward_order_for_missing_chunks() -> None:
    assert batch_eval._best_effort_offsets("alpha xx beta", ["alpha", "missing", "", "beta"]) == [
        (0, 5),
        (5, 12),
        (12, 12),
        (12, 16),
    ]


def test_main_emits_quality_row_with_separator_overlap_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample.md"
    output = tmp_path / "reports" / "preview.jsonl"
    source.write_text("alpha xx alpha", encoding="utf-8")
    quality_inputs: dict[str, Any] = {}

    class _Chunker:
        def split_documents(self, documents: list[Any]) -> list[SimpleNamespace]:
            assert documents[0].page_content == "alpha xx alpha"
            return [
                SimpleNamespace(page_content="alpha", metadata={"page": 1}),
                SimpleNamespace(page_content="alpha", metadata={"page": 2}),
            ]

    def compute_quality(**kwargs: Any):
        quality_inputs.update(kwargs)
        return _Dumpable({"status": "warn"}), ["increase size"], [_Dumpable({"op": "replace"})]

    monkeypatch.setattr(batch_eval.chunker_factory, "resolve_strategy", lambda _value: "separator")
    monkeypatch.setattr(batch_eval.chunker_factory, "get_chunker", lambda *_args: _Chunker())
    monkeypatch.setattr(
        batch_eval,
        "_compute_chunk_coverage_metrics_from_ranges",
        lambda ranges, **_kwargs: {
            "ranges": ranges,
            "covered_chars": 10,
            "coverage_ratio": 10 / 14,
            "overlap_waste_ratio": 0.0,
            "gap_count": 1,
            "largest_gap": 4,
        },
    )
    monkeypatch.setattr(batch_eval, "_compute_chunk_preview_quality", compute_quality)

    assert (
        batch_eval.main(
            [
                str(source),
                "--strategy",
                "separator",
                "--chunk-size",
                "20",
                "--chunk-overlap",
                "9",
                "--out",
                str(output),
            ]
        )
        == 0
    )

    row = json.loads(output.read_text(encoding="utf-8"))
    assert row == {
        "file": str(source),
        "chars": 14,
        "strategy": "separator",
        "chunk_size": 20,
        "chunk_overlap": 0,
        "chunks": 2,
        "coverage": {
            "ranges": [[0, 5], [9, 14]],
            "covered_chars": 10,
            "coverage_ratio": 10 / 14,
            "overlap_waste_ratio": 0.0,
            "gap_count": 1,
            "largest_gap": 4,
        },
        "quality_gate": {"status": "warn"},
        "recommendations": ["increase size"],
        "recommendation_patches": [{"op": "replace"}],
    }
    stats = quality_inputs["stats"]
    assert stats.count == 2
    assert stats.short_count == 2
    assert stats.duplicate_count == 1
    assert quality_inputs["chunk_overlap"] == 0
