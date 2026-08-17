from app.services import report_html


def _assert_in_order(text: str, parts: list[str]) -> None:
    start = 0
    for part in parts:
        index = text.find(part, start)
        assert index >= 0, f"missing {part!r}"
        start = index + len(part)


def _assert_style_is_rendered(text: str) -> None:
    assert "{{" not in text
    assert "}}" not in text
    assert ".wrap { max-width: 1100px; margin: 0 auto; padding: 28px 18px 40px; }" in text


def test_render_dataset_profile_html_preserves_status_colors_and_sections() -> None:
    html = report_html.render_dataset_profile_html(
        title="Profile",
        dataset_name="Dataset",
        dataset_id="dataset-1",
        generated_at="2026-01-01T00:00:00Z",
        summary={
            "total_documents": 1,
            "total_size_bytes": 10,
            "by_file_type": {"pdf": 1},
            "by_status": {"ready": 1},
            "by_directory": {"docs": 1},
            "by_quality_bucket": {"good": 1},
            "language_mix": {"zh": 1},
            "pii_hits_total": {},
            "secrets_hits_total": {},
            "pdf_scan": {"scanned": 0, "not_scanned": 1, "unknown": 0},
        },
    )

    _assert_style_is_rendered(html)
    assert "--warn: #f59e0b;" in html
    assert "--err: #fb7185;" in html
    _assert_in_order(
        html,
        [
            "<h2>格式分布（Top）</h2>",
            "<h2>状态分布</h2>",
            "<h2>问题清单（可操作）</h2>",
            "<h2>长度分布（chars）</h2>",
            "<h2>目录分布（Top-level）</h2>",
            "<h2>Chunk coverage 分布（%）</h2>",
            "<h2>PII 命中（次数）</h2>",
        ],
    )


def test_render_dataset_report_html_preserves_escape_order_and_sections() -> None:
    html = report_html.render_dataset_report_html(
        title="Bundle <Report>",
        dataset_name='Dataset <One> & "Two"',
        dataset_id='dataset-"1"&<2>',
        generated_at="2026-01-01T00:00:00Z",
        report={
            "pipeline_hash": "pipe-123",
            "profile": {
                "total_documents": 2,
                "total_size_bytes": 2048,
                "by_status": {"ready": 2},
                "by_file_type": {"pdf": 2},
                "findings": [{"label": "Missing OCR", "count": 2}],
                "parsing_provenance": {
                    "docs_with_provenance": 2,
                    "fallback_docs": 1,
                    "elapsed_ms_percentiles": {"p50": 11, "p90": 99},
                    "by_resolved_backend": {"ocr": 2},
                },
                "chunk_targets": [
                    {
                        "label": "Target <A>",
                        "status": "warn",
                        "message": "Need <check>",
                        "suggestions": ["keep", "escape <tag>"],
                    }
                ],
                "recall_risk_hints": [
                    {
                        "label": "Long tail",
                        "severity": "warning",
                        "observed": {"b": 2, "a": 1},
                        "message": "Review <paths>",
                    }
                ],
            },
            "compliance": {"quarantined_documents": 1, "failed_documents": 0},
            "chunk_quality_metrics": {
                "gate_grade_docs": {"A": 1, "B": 1},
                "coverage_low_documents": 1,
                "overlap_waste_high_documents": 2,
                "token_stats_missing_documents": 0,
            },
            "kg_stats": {
                "events": 3,
                "entities": 4,
                "links": 5,
                "events_with_chunk_id": 3,
                "events_with_page_ref": 2,
                "links_with_provenance": 1,
                "links_with_page_ref": 1,
                "documents_with_kg_extracted_at": 2,
                "documents_with_kg_events": 2,
                "event_count_from_documents": 3,
                "skipped_chunks_total": 1,
                "skipped_short_chunks_total": 0,
                "failed_chunks_total": 0,
                "retry_chunks_total": 0,
                "updated_at": "2026-01-02T00:00:00Z",
                "entity_types": [{"type": "ORG", "count": 4}],
                "top_documents": [
                    {
                        "document_id": "doc-12345678",
                        "source": "doc<source>",
                        "event_count": 3,
                        "skipped_chunks": 1,
                        "failed_chunks": 0,
                    }
                ],
            },
            "latest_regression_run": {
                "status": "done",
                "created_at": "2026-01-03T00:00:00Z",
                "run_id": "run-1",
                "metrics": ["hit_at_1", "mrr"],
                "started_at": "2026-01-03T00:00:01Z",
                "finished_at": "2026-01-03T00:01:00Z",
                "summary": {
                    "retrieval_hit_at_1": 0.5,
                    "retrieval_slices": {
                        "file_type": {"buckets": [{"key": "pdf", "items": 2, "retrieval_recall": 0.5}]},
                        "language": {"buckets": [{"key": "zh", "items": 2, "retrieval_recall": 0.6}]},
                        "hit_type": {"buckets": [{"key": "dense", "items": 2, "retrieval_recall": 0.7}]},
                        "quality": {"buckets": [{"key": "gold", "items": 2, "retrieval_recall": 0.8}]},
                        "pipeline_hash": {"buckets": [{"key": "pipe-123", "items": 2, "retrieval_recall": 0.9}]},
                        "directory": {"buckets": [{"key": "docs/api", "items": 2, "retrieval_recall": 1.0}]},
                    },
                },
            },
            "retrieval_audit": {
                "status": "failed",
                "plugin_refs": ["plugin-a", "plugin-b"],
                "plugin_package_hashes": ["1234567890abcdef"],
                "failure_categories": {"beta": 2, "alpha": 1},
                "kg_recommendation": "Enable KG",
                "recommended_next_action": "Re-index",
                "gates": [
                    {
                        "name": "gate_1",
                        "status": "failed",
                        "metrics": {"hit_at_1": 0.25, "retrieval_mrr": 0.5},
                        "failed_conditions": ["bad recall"],
                        "generated_at": "2026-01-04T00:00:00Z",
                        "source": "audit",
                    }
                ],
            },
            "pipeline_versions": [{"pipeline_hash": "pipe-123", "documents": 2}],
            "connectors": [{"connector_id": "con<1>", "status": "ok", "created_at": "2026-01-05T00:00:00Z"}],
        },
    )

    assert "Bundle &lt;Report&gt;" in html
    assert "Dataset &lt;One&gt; &amp; &quot;Two&quot;" in html
    assert "dataset-&quot;1&quot;&amp;&lt;2&gt;" in html
    assert "doc&lt;source&gt;" in html
    assert "Need &lt;check&gt;" in html
    assert "escape &lt;tag&gt;" in html
    assert "Review &lt;paths&gt;" in html
    assert "con&lt;1&gt;" in html
    assert "&quot;plugin_package_hashes&quot;: [" in html
    assert "12345678" in html
    _assert_style_is_rendered(html)
    _assert_in_order(
        html,
        [
            '<td class="k">status</td>',
            '<td class="k">plugin_refs</td>',
            '<td class="k">plugin_package_hashes</td>',
            '<td class="k">failure_categories</td>',
            '<td class="k">kg_recommendation</td>',
            '<td class="k">next_action</td>',
        ],
    )
    _assert_in_order(
        html,
        [
            "<h2>KG Drilldown（Top Documents）</h2>",
            "doc&lt;source&gt;",
            "<h2>评估（Regression Run）</h2>",
            "<h2>评估 Summary</h2>",
            "<h2>Retrieval Audit</h2>",
            "<h2>Retrieval Audit Metrics</h2>",
            "<h2>Pipeline 版本分布</h2>",
            "<h2>最近 Connector Runs</h2>",
            "<h2>Raw JSON（用于审计/分享）</h2>",
        ],
    )


def test_render_rag_audit_html_preserves_redaction_and_branch_output() -> None:
    html = report_html.render_rag_audit_html(
        title="RAG <Audit>",
        dataset_name="Dataset",
        dataset_id="dataset-1",
        generated_at="2026-01-01T00:00:00Z",
        redact=True,
        report={
            "profile": {
                "total_documents": 2,
                "total_size_bytes": 256,
                "by_status": {"done": 2},
                "by_file_type": {"pdf": 2},
                "length_percentiles": {"p50": 1, "p90": 2},
                "chunk_token_percentiles": {"p50": 3},
                "chunk_coverage_percentiles": {"p50": 4},
                "length_histogram": [{"label": "0-10", "count": 2}],
                "file_size_histogram": [{"label": "0-1KB", "count": 2}],
            },
            "compliance": {"quarantined_documents": 1, "failed_documents": 0},
            "governance_metrics": {
                "docs_with_governance": 2,
                "rules_applied_total": 4,
                "dropped_documents_total": 1,
                "drop_reasons_total": {"pii": 1},
                "rule_packs_docs": {"strict": 2},
            },
            "governance_audit": {
                "used_documents": 2,
                "truncated": True,
                "docs_changed": 1,
                "docs_dropped": 1,
                "docs_with_char_stats": 2,
                "docs_with_parsed_content_persisted": 2,
                "parsed_content_truncated_docs": 1,
                "original_chars_total": 100,
                "cleaned_chars_total": 40,
                "char_reduction_ratio": 0.6,
                "char_reduction_pct_percentiles": {"p50": 50, "p90": 75},
                "density_pct_percentiles": {"p50": 10, "p90": 20},
                "heading_ratio_pct_percentiles": {"p50": 5, "p90": 15},
            },
            "chunk_quality_metrics": {
                "gate_grade_docs": {"A": 2},
                "coverage_low_documents": 0,
                "overlap_waste_high_documents": 1,
                "token_stats_missing_documents": 0,
            },
            "precheck_summary": {
                "scan_run_id": "scan-secret",
                "generated_at": "2026-01-01T00:00:00Z",
                "total_files": 2,
                "total_size_bytes": 99,
                "by_file_type": {"pdf": 2},
                "file_size_histogram": [{"label": "0-1KB", "count": 2}],
                "token_histogram": [{"label": "0-99", "count": 2}],
                "language_mix": {"zh": 2},
                "findings": [{"label": "OCR", "count": 1}],
                "pii_hits_total": {"email": 1},
                "secrets_hits_total": {"token": 1},
                "directory_stats": [{"path": "secret/dir", "total_files": 2, "risky_files": 1, "total_size_bytes": 99}],
                "pdf_scan": {"scanned": 1, "not_scanned": 1, "unknown": 0},
            },
            "kg_stats": {
                "events": 1,
                "entities": 1,
                "links": 1,
                "events_with_chunk_id": 1,
                "events_with_page_ref": 1,
                "links_with_provenance": 1,
                "links_with_page_ref": 1,
                "documents_with_kg_extracted_at": 1,
                "documents_with_kg_events": 1,
                "event_count_from_documents": 1,
                "skipped_chunks_total": 0,
                "skipped_short_chunks_total": 0,
                "failed_chunks_total": 0,
                "retry_chunks_total": 0,
                "entity_types": [{"type": "ORG", "count": 1}],
                "top_documents": [{"document_id": "doc-1", "source": "secret/dir", "event_count": 1}],
            },
            "latest_regression_run": {
                "status": "done",
                "created_at": "2026-01-02T00:00:00Z",
                "finished_at": "2026-01-03T00:00:00Z",
                "summary": {
                    "retrieval_hit_at_1": 0.5,
                    "retrieval_slices": {
                        "file_type": {"buckets": [{"key": "pdf", "items": 2, "retrieval_recall": 0.5}]},
                        "language": {"buckets": [{"key": "zh", "items": 2, "retrieval_recall": 0.6}]},
                        "directory": {"buckets": [{"key": "secret/dir", "items": 2, "retrieval_recall": 0.7}]},
                    },
                },
            },
            "retrieval_audit": {
                "status": "warn",
                "failure_categories": {"missing": 2},
                "plugin_refs": ["private-plugin"],
                "gates": [{"name": "gate", "metrics": {"hit_at_1": 0.5}}],
            },
        },
    )

    assert "RAG &lt;Audit&gt;" in html
    assert "scan-secret" not in html
    assert "secret/dir" not in html
    assert "已脱敏：directory 不展示" in html
    assert "sample: 2 (truncated)" in html
    assert '<td class="k">updated_at</td><td class="v"></td><td></td>' in html
    assert "<h2>Precheck（入库前摸底）</h2>" in html
    assert "<h2>Governance Audit（治理效果）</h2>" in html
    _assert_style_is_rendered(html)
    _assert_in_order(
        html,
        [
            "<h2>状态分布</h2>",
            "<h2>格式分布（Top）</h2>",
            "<h2>Precheck（入库前摸底）</h2>",
            "<h2>Knowledge Graph（KG）</h2>",
            "<h2>评估（Latest Regression Run）</h2>",
            "<h2>Retrieval Audit</h2>",
            "<h2>Raw JSON（用于审计/分享）</h2>",
        ],
    )


def test_render_precheck_html_preserves_escape_order_and_tips() -> None:
    html = report_html.render_precheck_html(
        title="Preview <Check>",
        dataset_name="Sensitive <Name>",
        dataset_id="dataset-1",
        root_path="/srv/<secret>/root",
        generated_at="2026-01-01T00:00:00Z",
        redact=False,
        summary={
            "total_files": 4,
            "total_size_bytes": 2048,
            "length_percentiles": {"p50": 10, "p90": 50},
            "token_percentiles": {"p50": 5, "p90": 25_000},
            "pdf_scan": {"scanned": 1, "not_scanned": 2, "unknown": 1},
            "by_file_type": {"pdf": 4},
            "language_mix": {"zh": 4},
            "pii_hits_total": {"email": 1},
            "secrets_hits_total": {"token": 1},
            "primary_tag_counts": {"finance": 4},
            "processing_path_counts": {"ocr": 4},
            "findings": [{"key": "empty_text", "label": "Empty Text", "count": 1}],
            "directory_stats": [
                {"path": "dept/<secret>", "total_files": 4, "risky_files": 2, "total_size_bytes": 2048}
            ],
            "pdf_detection": {
                "sample_pages": "<2>",
                "scan_max_chars_per_page": 10,
                "text_min_chars_per_page": 20,
                "scan_ratio_threshold": 0.8,
            },
        },
        samples={
            "representative": [{"name": "sample<1>.pdf", "file_type": "pdf", "file_size": 128}],
            "needs_review": {"ocr": [{}]},
        },
    )

    assert "Preview &lt;Check&gt;" in html
    assert "Sensitive &lt;Name&gt;" in html
    assert "/srv/&lt;secret&gt;/root" in html
    assert "dept/&lt;secret&gt;" in html
    assert "sample&lt;1&gt;.pdf" in html
    assert "&lt;2&gt;" in html
    assert "P90 文本长度较长" in html
    assert "enable_text_extract" not in html
    _assert_style_is_rendered(html)
    _assert_in_order(
        html,
        [
            "<h2>格式分布（Top）</h2>",
            "<h2>长度分布（chars）</h2>",
            "<h2>长度分布（tokens）</h2>",
            "<h2>语言分布（抽样）</h2>",
            "<h2>文件大小分布</h2>",
            "<h2>目录结构（Top 风险聚集区）</h2>",
            "<h2>主标签分布</h2>",
            "<h2>处理路径建议</h2>",
            "<h2>PII 命中（次数）</h2>",
            "<h2>Secrets/Token 命中（次数）</h2>",
            "<h2>问题清单（可操作）</h2>",
            "<h2>入库建议（best-effort）</h2>",
            "<h2>PDF 判定参数（透明阈值）</h2>",
            "<h2>代表性样本（按格式/大小/PDF类型分层）</h2>",
            "<h2>需复核样本（按问题分桶）</h2>",
        ],
    )


def test_render_rag_audit_html_keeps_empty_precheck_meta_rows() -> None:
    html = report_html.render_rag_audit_html(
        title="Empty Meta",
        dataset_name="Dataset",
        dataset_id="dataset-1",
        generated_at="2026-01-01T00:00:00Z",
        report={
            "profile": {
                "total_documents": 1,
                "total_size_bytes": 1,
                "by_status": {"done": 1},
                "by_file_type": {"pdf": 1},
                "length_percentiles": {"p50": 1, "p90": 1},
                "chunk_token_percentiles": {"p50": 1},
                "chunk_coverage_percentiles": {"p50": 1},
            },
            "precheck_summary": {
                "scan_run_id": "",
                "generated_at": "",
                "total_files": 0,
                "total_size_bytes": 0,
                "by_file_type": {},
                "file_size_histogram": [],
                "token_histogram": [],
                "language_mix": {},
                "findings": [],
                "pii_hits_total": {},
                "secrets_hits_total": {},
                "directory_stats": [],
                "pdf_scan": {"scanned": 0, "not_scanned": 0, "unknown": 0},
            },
        },
    )

    assert '<td class="k">scan_run_id</td><td class="v"></td><td></td>' in html
    assert '<td class="k">generated_at</td><td class="v"></td><td></td>' in html
    assert '<td class="k">pdf_scan (scanned/text/unknown)</td><td class="v">0/0/0</td><td></td>' in html
