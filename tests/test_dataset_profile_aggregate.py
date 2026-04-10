import uuid

from app.services.dataset_profile_service import aggregate_profile_from_rows


def _row(
    *,
    filename: str,
    file_type: str,
    file_size: int = 0,
    status: str = "completed",
    chunk_count: int = 0,
    total_characters: int = 0,
    error_message: str | None = None,
    metadata: dict | None = None,
):
    # Row shape must match `compute_dataset_profile_summary(...with_entities...)`.
    return (
        uuid.uuid4(),  # id
        filename,
        file_type,
        file_size,
        status,
        chunk_count,
        total_characters,
        error_message,
        metadata or {},
    )


def test_dataset_profile_aggregate_empty():
    dsid = uuid.uuid4()
    summary = aggregate_profile_from_rows(dataset_id=dsid, rows=[])
    assert summary.dataset_id == dsid
    assert summary.total_documents == 0
    assert summary.total_size_bytes == 0
    assert summary.by_status == {}
    assert summary.by_file_type == {}
    assert summary.pdf_scan.scanned == 0
    assert summary.pdf_scan.unknown == 0
    # Stable keys exist.
    keys = [f.key for f in summary.findings]
    assert "parse_failed" in keys
    assert "preprocess_failed" in keys
    assert "pdf_scanned" in keys
    assert summary.parsing_provenance.docs_with_provenance == 0


def test_dataset_profile_aggregate_basic_distributions_and_findings():
    dsid = uuid.uuid4()
    rows = [
        _row(
            filename="a.pdf",
            file_type="pdf",
            file_size=1200,
            status="completed",
            total_characters=0,
            metadata={
                "pdf_quality": {"is_scanned": True},
                "parsed_text_quality": {"density": 0.2},
                "parse_provenance": {
                    "resolved_backend": "basic",
                    "elapsed_ms": 12,
                    "attempts": [{"backend": "basic", "ok": True, "elapsed_ms": 12}],
                },
            },
        ),
        _row(
            filename="b.pdf",
            file_type="pdf",
            file_size=2200,
            status="completed",
            total_characters=1000,
            metadata={
                "parsed_text_quality": {"density": 0.05},  # low density
                "parse_provenance": {
                    "resolved_backend": "basic",
                    "elapsed_ms": 120,
                    "attempts": [
                        {"backend": "olmocr", "ok": False, "elapsed_ms": 80, "error_type": "RuntimeError"},
                        {"backend": "basic", "ok": True, "elapsed_ms": 40, "fallback_from": "olmocr"},
                    ],
                },
            },
        ),
        _row(
            filename="c.docx",
            file_type="docx",
            file_size=800,
            status="failed",
            total_characters=200,
            error_message="preprocess_failed: encoding_error",
            metadata={},
        ),
        _row(
            filename="d.md",
            file_type="md",
            file_size=400,
            status="completed",
            total_characters=500,
            metadata={"governance_pii_hits": {"phone": 2}},
        ),
    ]

    summary = aggregate_profile_from_rows(dataset_id=dsid, rows=rows, density_threshold=0.12)
    assert summary.total_documents == 4
    assert summary.total_size_bytes == 1200 + 2200 + 800 + 400
    assert summary.by_file_type["pdf"] == 2
    assert summary.by_file_type["docx"] == 1
    assert summary.by_status["completed"] == 3
    assert summary.by_status["failed"] == 1

    assert summary.pdf_scan.scanned == 1
    assert summary.pdf_scan.unknown == 1  # b.pdf has no pdf_quality

    finding_map = {f.key: f.count for f in summary.findings}
    assert finding_map["pdf_scanned"] == 1
    assert finding_map["pdf_unknown"] == 1
    assert finding_map["parse_failed"] == 1
    assert finding_map["preprocess_failed"] == 1
    assert finding_map["low_density"] == 1
    assert finding_map["pii"] == 1

    # Percentiles should reflect [200, 500, 1000] (0 length excluded)
    assert summary.length_percentiles.p50 == 500

    assert summary.parsing_provenance.docs_with_provenance == 2
    assert summary.parsing_provenance.by_resolved_backend.get("basic") == 2
    assert summary.parsing_provenance.fallback_docs == 1


def test_dataset_profile_aggregate_exact_duplicates():
    dsid = uuid.uuid4()
    sha = "a" * 64
    rows = [
        _row(filename="a.txt", file_type="txt", metadata={"file_sha256": sha}, file_size=10, total_characters=10),
        _row(filename="b.txt", file_type="txt", metadata={"file_sha256": sha}, file_size=12, total_characters=12),
        _row(filename="c.txt", file_type="txt", metadata={"file_sha256": "b" * 64}, file_size=14, total_characters=14),
    ]
    summary = aggregate_profile_from_rows(dataset_id=dsid, rows=rows)
    finding_map = {f.key: f.count for f in summary.findings}
    assert finding_map["exact_dup"] == 2


def test_dataset_profile_aggregate_chunk_targets_missing_stats_are_reported():
    dsid = uuid.uuid4()
    rows = [
        _row(filename="a.md", file_type="md", status="completed", total_characters=100, metadata={}),
    ]
    summary = aggregate_profile_from_rows(dataset_id=dsid, rows=rows)
    keys = [c.key for c in (summary.chunk_targets or [])]
    assert "chunk_tokens_missing" in keys
    assert "chunk_overlap_waste_missing" in keys


def test_dataset_profile_aggregate_parse_low_quality_bucket():
    dsid = uuid.uuid4()
    rows = [
        _row(
            filename="a.pdf",
            file_type="pdf",
            file_size=1200,
            status="completed",
            total_characters=0,
            metadata={"parse_quality": {"score": 0.2}},
        ),
        _row(
            filename="b.md",
            file_type="md",
            file_size=200,
            status="completed",
            total_characters=100,
            metadata={"parse_quality": {"score": 0.8}},
        ),
    ]

    summary = aggregate_profile_from_rows(dataset_id=dsid, rows=rows)
    finding_map = {f.key: f.count for f in summary.findings}
    assert finding_map["parse_low_quality"] == 1


def test_dataset_profile_aggregate_seal_low_confidence_bucket():
    dsid = uuid.uuid4()
    rows = [
        _row(
            filename="a.pdf",
            file_type="pdf",
            file_size=1200,
            status="completed",
            total_characters=0,
            metadata={
                "seal_summary": {
                    "detected": True,
                    "primary_score": 0.22,
                    "primary_text": "杭州测试科技有限公司",
                }
            },
        ),
        _row(
            filename="b.pdf",
            file_type="pdf",
            file_size=800,
            status="completed",
            total_characters=0,
            metadata={
                "seal_summary": {
                    "detected": True,
                    "primary_score": 0.91,
                    "primary_text": "财务专用章",
                }
            },
        ),
    ]

    summary = aggregate_profile_from_rows(dataset_id=dsid, rows=rows)
    finding_map = {f.key: f.count for f in summary.findings}
    assert finding_map["seal_low_confidence"] == 1


def test_dataset_profile_aggregate_chunk_count_and_avg_chunk_distributions():
    dsid = uuid.uuid4()
    rows = [
        _row(filename="a.md", file_type="md", chunk_count=5, total_characters=1000),
        _row(filename="b.md", file_type="md", chunk_count=10, total_characters=4000),
        _row(filename="c.md", file_type="md", chunk_count=20, total_characters=10000),
        _row(filename="d.md", file_type="md", chunk_count=0, total_characters=9999),  # excluded from chunk proxies
    ]

    summary = aggregate_profile_from_rows(dataset_id=dsid, rows=rows)

    assert summary.chunk_count_percentiles.p50 == 10
    assert summary.avg_chunk_chars_percentiles.p50 == 400

    cc = {b.label: int(b.count or 0) for b in (summary.chunk_count_histogram or [])}
    assert cc.get("1-5") == 1
    assert cc.get("6-10") == 1
    assert cc.get("11-20") == 1

    avg = {b.label: int(b.count or 0) for b in (summary.avg_chunk_chars_histogram or [])}
    assert avg.get("200-500") == 2
    assert avg.get("500-800") == 1


def test_dataset_profile_aggregate_chunk_length_distribution_from_chunking_stats_histogram():
    dsid = uuid.uuid4()
    rows = [
        _row(
            filename="a.md",
            file_type="md",
            metadata={
                "chunking_stats": {
                    "histogram": [
                        {"label": "0-200", "count": 2},
                        {"label": "200-500", "count": 1},
                    ]
                }
            },
        ),
        _row(
            filename="b.md",
            file_type="md",
            metadata={
                "chunking_stats": {
                    "histogram": [
                        {"label": "200-500", "count": 3},
                        {"label": "2k+", "count": 1},
                    ]
                }
            },
        ),
    ]

    summary = aggregate_profile_from_rows(dataset_id=dsid, rows=rows)

    hist = {b.label: int(b.count or 0) for b in (summary.chunk_length_histogram or [])}
    assert hist.get("0-200") == 2
    assert hist.get("200-500") == 4
    assert hist.get("2k+") == 1


def test_dataset_profile_aggregate_chunk_token_distribution_from_chunking_stats_tokens_histogram():
    dsid = uuid.uuid4()
    rows = [
        _row(
            filename="a.md",
            file_type="md",
            metadata={
                "chunking_stats_tokens": {
                    "histogram": [
                        {"label": "0-50", "count": 2},
                        {"label": "200-400", "count": 1},
                    ]
                }
            },
        ),
        _row(
            filename="b.md",
            file_type="md",
            metadata={
                "chunking_stats_tokens": {
                    "histogram": [
                        {"label": "0-50", "count": 1},
                        {"label": "400-800", "count": 2},
                        {"label": "800+", "count": 1},
                    ]
                }
            },
        ),
    ]

    summary = aggregate_profile_from_rows(dataset_id=dsid, rows=rows)

    hist = {b.label: int(b.count or 0) for b in (summary.chunk_token_histogram or [])}
    assert hist.get("0-50") == 3
    assert hist.get("200-400") == 1
    assert hist.get("400-800") == 2
    assert hist.get("800+") == 1


def test_dataset_profile_aggregate_chunk_coverage_histogram_from_chunk_coverage():
    dsid = uuid.uuid4()
    rows = [
        _row(
            filename="a.md",
            file_type="md",
            metadata={"chunk_coverage": {"coverage_ratio": 0.95, "overlap_waste_ratio": 0.10}},
        ),
        _row(
            filename="b.md",
            file_type="md",
            metadata={"chunk_coverage": {"coverage_ratio": 0.99, "overlap_waste_ratio": 0.50}},
        ),
    ]

    summary = aggregate_profile_from_rows(dataset_id=dsid, rows=rows)

    cov_hist = {b.label: int(b.count or 0) for b in (summary.chunk_coverage_histogram or [])}
    assert cov_hist.get("90-98%") == 1
    assert cov_hist.get("98-100%") == 1

    waste_hist = {b.label: int(b.count or 0) for b in (summary.chunk_overlap_waste_histogram or [])}
    # 10% waste lands in 10-20% bin due to [min, max) semantics.
    assert waste_hist.get("10-20%") == 1
    assert waste_hist.get("35-60%") == 1
