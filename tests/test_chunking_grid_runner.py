from __future__ import annotations

from pathlib import Path


def test_build_chunking_grid_configs_covers_expected_strategies_and_sizes() -> None:
    from scripts.chunking_grid_runner import build_chunking_grid_configs

    grid = build_chunking_grid_configs()

    keys = {(row["strategy"], int(row["chunk_size"]), float(row["chunk_overlap_ratio"])) for row in grid}
    assert ("langchain_recursive", 256, 0.0) in keys
    assert ("semantic_sentence", 512, 0.1) in keys
    assert ("sentence_window", 1024, 0.25) in keys
    assert ("parent_child", 512, 0.25) in keys
    assert ("contextual", 256, 0.1) in keys


def test_build_chunking_grid_configs_includes_ilya_300_50_control_group() -> None:
    from scripts.chunking_grid_runner import build_chunking_grid_configs

    grid = build_chunking_grid_configs()
    ilya_rows = [row for row in grid if str(row.get("control_group") or "") == "ilya_300_50"]

    assert len(ilya_rows) == 1
    row = ilya_rows[0]
    assert row["strategy"] == "langchain_recursive"
    assert int(row["chunk_size"]) == 300
    assert int(row["chunk_overlap"]) == 50


def test_evaluate_chunking_grid_file_reports_stable_metrics(tmp_path: Path) -> None:
    from scripts.chunking_grid_runner import evaluate_chunking_grid_file

    sample = tmp_path / "sample.md"
    sample.write_text(
        "# Title\n\nThis is a short paragraph.\n\nThis is another paragraph with more words.\n",
        encoding="utf-8",
    )

    out = evaluate_chunking_grid_file(
        path=sample,
        strategy="langchain_recursive",
        chunk_size=64,
        chunk_overlap=8,
    )

    assert out["file"] == str(sample)
    assert out["strategy"] == "langchain_recursive"
    assert out["chunk_count"] >= 1
    assert out["total_tokens_est"] >= 1
    assert out["median_tokens_est"] >= 1


def test_contextual_strategy_maps_to_recursive_chunker_with_contextual_flag(tmp_path: Path) -> None:
    from scripts.chunking_grid_runner import evaluate_chunking_grid_file

    sample = tmp_path / "sample.md"
    sample.write_text("Paragraph one.\n\nParagraph two.", encoding="utf-8")

    out = evaluate_chunking_grid_file(
        path=sample,
        strategy="contextual",
        chunk_size=64,
        chunk_overlap=8,
    )

    assert out["strategy"] == "contextual"
    assert out["resolved_strategy"] == "langchain_recursive"
    assert out["embedding_contextual_retrieval_enabled"] is True
