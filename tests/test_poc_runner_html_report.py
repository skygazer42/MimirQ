from __future__ import annotations

from app.rag.evaluation.poc_runner.reports.html_renderer import render_dataset_analysis_html


def test_render_dataset_analysis_html_includes_key_sections_and_chart_container() -> None:
    html = render_dataset_analysis_html(
        {
            "meta": {
                "dataset_id": "ds-1",
                "dataset_name": "Dataset One",
                "generated_at": "2026-04-22T12:00:00+00:00",
                "filters": {"dataset_id": "ds-1"},
                "scope_summary": {"all_interactions": 20},
                "definitions": {"all_interactions": "all trace-backed interactions"},
            },
            "metrics": {"raw_positive_rate": 0.7, "feedback_coverage_rate": 0.5},
            "counts": {"retrieval_miss": 2, "generation_error": 1, "out_of_scope": 1},
            "top_examples": {"retrieval_miss": [{"interaction_id": "req-1", "original_query": "485 怎么配置？"}]},
            "manual_review_candidates": [{"interaction_id": "req-2"}],
            "glossary_candidates": [{"token": "485", "count": 5}],
                "umap_scatter": {
                    "schema": "mimirq.dataset_analysis.umap_scatter.v1",
                    "points": [
                        {"label": "manual-a.pdf", "kind": "document", "group": "document", "x": 0.1, "y": 0.2},
                        {"label": "req-1", "kind": "query", "group": "out_of_scope_candidate", "x": 0.8, "y": 0.7},
                    ],
                },
                "latency_breakdown": {
                    "schema": "mimirq.poc.latency_decomposer.v1",
                    "summary": {"avg_wait_in_queue_ms": 900, "avg_active_inference_ms": 2400},
                },
                "coverage_heatmap": {
                "x_axis": ["retrieval_hit_count", "negative_feedback_count"],
                "y_axis": ["manual-a.pdf"],
                "cells": [["manual-a.pdf", "retrieval_hit_count", 3], ["manual-a.pdf", "negative_feedback_count", 2]],
                "rows": [{"filename": "manual-a.pdf", "retrieval_hit_count": 3, "negative_feedback_count": 2}],
            },
        }
    )

    assert "Dataset One" in html
    assert "raw_positive_rate" in html
    assert "metric-cards" in html
    assert "feedback-coverage" in html
    assert "coverage-heatmap" in html
    assert "umap-scatter" in html
    assert "latency-breakdown" in html
    assert "req-1" in html
    assert "pyecharts" in html.lower() or "echarts" in html.lower()
