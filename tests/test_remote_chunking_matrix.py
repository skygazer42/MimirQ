from __future__ import annotations

from pathlib import Path

from scripts.remote_chunking_matrix import (
    evaluate_preview_summary,
    evaluate_profile_summary,
    maybe_copy_or_download_long_pdf,
    prepare_fixture_files,
    summarize_preview_result,
)


def test_remote_chunking_matrix_prepare_fixture_files_covers_required_file_families(tmp_path) -> None:
    cases = prepare_fixture_files(tmp_path)

    assert {case["file_type"] for case in cases} >= {"md", "html", "csv", "docx", "xlsx", "pdf"}
    assert any(case["name"] == "rfc9000_long_pdf" for case in cases)
    long_case = next(case for case in cases if case["name"] == "rfc9000_long_pdf")
    assert long_case["preview_include_chunks"] is False
    assert long_case["parser_backend"] == "magicpdf"


def test_remote_chunking_matrix_uses_configured_long_pdf_fixture(tmp_path, monkeypatch) -> None:
    custom_pdf = tmp_path / "custom-long.pdf"
    custom_pdf.write_bytes(b"%PDF-1.7\ncustom long fixture\n")
    monkeypatch.setenv("MIMIRQ_REMOTE_LONG_PDF_FIXTURE", str(custom_pdf))
    monkeypatch.delenv("MIMIRQ_REMOTE_FIXTURE_DOWNLOADS", raising=False)

    copied = maybe_copy_or_download_long_pdf(tmp_path / "fixtures")

    assert copied.read_bytes() == custom_pdf.read_bytes()


def test_remote_chunking_matrix_does_not_pin_historical_artifact_paths() -> None:
    source = Path("scripts/remote_chunking_matrix.py").read_text(encoding="utf-8")

    assert "artifacts/production-readiness" not in source
    assert "20260522" not in source


def test_remote_chunking_matrix_summarize_preview_result_extracts_core_metrics() -> None:
    case = {"name": "markdown_handbook", "parser_backend": "auto"}
    preview = summarize_preview_result(
        case,
        "langchain_recursive",
        {
            "total_chunks": 3,
            "total_chunks_full": 3,
            "parse_cache_hit": True,
            "stats": {
                "avg": 120,
                "coverage_ratio": 0.99,
                "overlap_waste_ratio": 0.12,
                "short_count": 0,
                "duplicate_count": 0,
                "gap_count": 0,
                "histogram": [{"label": "0-200", "count": 3}],
            },
            "chunks": [
                {"content": "alpha"},
                {"content": "beta"},
                {"content": "gamma"},
            ],
            "quality_gate": {"grade": "pass"},
        },
    )

    assert preview["case"] == "markdown_handbook"
    assert preview["strategy"] == "langchain_recursive"
    assert preview["total_chunks_full"] == 3
    assert preview["avg_chunk_length"] == 120
    assert preview["coverage_ratio"] == 0.99
    assert preview["overlap_waste_ratio"] == 0.12
    assert preview["empty_chunks"] == 0
    assert preview["parse_cache_hit"] is True


def test_remote_chunking_matrix_flags_invalid_preview_and_profile_shapes() -> None:
    preview_failures = evaluate_preview_summary(
        {"name": "csv_metrics"},
        {
            "strategy": "csv_rows",
            "total_chunks_full": 0,
            "avg_chunk_length": 0,
            "coverage_ratio": 1.5,
            "overlap_waste_ratio": -0.1,
            "empty_chunks": 2,
        },
    )

    assert any("total_chunks" in item for item in preview_failures)
    assert any("avg_chunk_length" in item for item in preview_failures)
    assert any("coverage_ratio" in item for item in preview_failures)
    assert any("overlap_waste_ratio" in item for item in preview_failures)
    assert any("empty_chunks" in item for item in preview_failures)

    profile_failures = evaluate_profile_summary(
        {
            "total_documents": 3,
            "chunk_count_histogram_bins": 0,
            "avg_chunk_chars_histogram_bins": 0,
            "chunk_length_histogram_bins": 0,
            "chunk_coverage_histogram_bins": 0,
            "chunk_overlap_waste_histogram_bins": 0,
            "by_file_type": {"md": 1},
        },
        expected_documents=7,
        expected_file_types={"md", "html", "csv"},
    )

    assert any("total_documents" in item for item in profile_failures)
    assert any("missing chunk_count_histogram_bins" in item for item in profile_failures)
    assert any("missing file types" in item for item in profile_failures)
