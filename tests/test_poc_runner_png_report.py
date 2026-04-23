from __future__ import annotations

from io import BytesIO

from PIL import Image

from app.rag.evaluation.poc_runner.reports.png_renderer import render_dataset_analysis_png


def test_render_dataset_analysis_png_returns_png_bytes_for_full_report() -> None:
    payload = render_dataset_analysis_png(
        {
            "meta": {
                "dataset_id": "ds-1",
                "dataset_name": "Dataset PNG",
                "generated_at": "2026-04-22T12:00:00+00:00",
                "filters": {"dataset_id": "ds-1"},
                "scope_summary": {"all_interactions": 20},
            },
            "metrics": {"raw_positive_rate": 0.7, "feedback_coverage_rate": 0.5},
            "counts": {"retrieval_miss": 2, "generation_error": 1, "out_of_scope": 1},
            "top_examples": {"retrieval_miss": [{"interaction_id": "req-1", "original_query": "485 怎么配置？"}]},
            "manual_review_candidates": [{"interaction_id": "req-2"}],
            "umap_scatter": {
                "schema": "mimirq.dataset_analysis.umap_scatter.v1",
                "points": [
                    {"label": "manual-a.pdf", "kind": "document", "group": "document", "x": 0.1, "y": 0.2},
                    {"label": "req-1", "kind": "query", "group": "out_of_scope_candidate", "x": 0.8, "y": 0.7},
                ],
            },
            "coverage_heatmap": {
                "rows": [{"filename": "manual-a.pdf", "retrieval_hit_count": 3, "negative_feedback_count": 2}],
            },
        }
    )

    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    image = Image.open(BytesIO(payload))
    assert image.width > 200
    assert image.height > 200
