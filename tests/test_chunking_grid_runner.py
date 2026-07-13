from scripts.chunking_grid_runner import build_chunking_grid_configs, evaluate_chunking_grid_file


def test_chunking_grid_reports_real_strategies_and_quality_metrics(tmp_path) -> None:  # noqa: ANN001
    configs = build_chunking_grid_configs()
    assert all(config["strategy"] != "contextual" for config in configs)

    path = tmp_path / "long.txt"
    path.write_text("context " * 2000, encoding="utf-8")
    row = evaluate_chunking_grid_file(
        path=path,
        strategy="langchain_recursive",
        chunk_size=20_000,
        chunk_overlap=0,
    )

    assert row["resolved_strategy"] == "langchain_recursive"
    assert row["avg_chunk_chars"] > 10_000
    assert row["cliff_rate"] == 1.0
