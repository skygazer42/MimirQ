from __future__ import annotations


def test_summarize_format_distribution_counts_extensions_case_insensitively() -> None:
    from app.rag.tools.pre_poc_scanner.format_distribution import summarize_format_distribution

    out = summarize_format_distribution(
        [
            "/tmp/a.PDF",
            "/tmp/b.pdf",
            "/tmp/c.docx",
            "/tmp/d",
        ]
    )

    assert out["schema"] == "mimirq.pre_poc.format_distribution.v1"
    assert out["total_files"] == 4
    assert out["by_extension"] == {"docx": 1, "pdf": 2, "unknown": 1}


def test_classify_pdf_page_density_uses_three_tier_page_and_file_logic() -> None:
    from app.rag.tools.pre_poc_scanner.pdf_page_classifier import classify_pdf_page_density

    out = classify_pdf_page_density([20, 30, 180, 260, 10])

    assert out["schema"] == "mimirq.pre_poc.pdf_page_classifier.v1"
    assert out["page_types"] == ["scan", "scan", "low_density", "text", "scan"]
    assert out["summary"]["page_count"] == 5
    assert out["summary"]["scan_pages"] == 3
    assert out["summary"]["low_density_pages"] == 1
    assert out["summary"]["text_pages"] == 1
    assert out["summary"]["pdf_type"] == "MIXED"


def test_summarize_length_distribution_reports_percentiles_and_histogram() -> None:
    from app.rag.tools.pre_poc_scanner.length_distribution import summarize_length_distribution

    out = summarize_length_distribution([100, 500, 2000, 10000])

    assert out["schema"] == "mimirq.pre_poc.length_distribution.v1"
    assert out["summary"]["count"] == 4
    assert out["percentiles"]["p50"] == 500
    assert out["percentiles"]["p90"] == 10000
    hist = {row["label"]: row["count"] for row in out["histogram"]}
    assert hist["0-500"] == 1
    assert hist["500-2000"] == 1
    assert hist["2000-10000"] == 1
    assert hist["10000+"] == 1


def test_find_exact_md5_duplicates_groups_duplicate_files_and_recommends_keep() -> None:
    from app.rag.tools.pre_poc_scanner.md5_dedup import find_exact_md5_duplicates

    out = find_exact_md5_duplicates(
        [
            {"path": "/tmp/a.pdf", "md5": "x" * 32, "size_bytes": 100, "mtime": 1},
            {"path": "/tmp/b.pdf", "md5": "x" * 32, "size_bytes": 120, "mtime": 2},
            {"path": "/tmp/c.pdf", "md5": "y" * 32, "size_bytes": 80, "mtime": 3},
        ]
    )

    assert out["schema"] == "mimirq.pre_poc.md5_dedup.v1"
    assert out["summary"]["duplicate_groups"] == 1
    assert out["summary"]["duplicate_files"] == 2
    group = out["groups"][0]
    assert group["keep_path"] == "/tmp/b.pdf"
    assert group["duplicate_paths"] == ["/tmp/a.pdf"]
