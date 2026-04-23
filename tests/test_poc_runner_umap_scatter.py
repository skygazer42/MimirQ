from __future__ import annotations

from app.rag.evaluation.poc_runner.reports.umap_scatter import build_umap_scatter


def test_build_umap_scatter_projects_document_and_query_points() -> None:
    scatter = build_umap_scatter(
        [
            {
                "interaction_id": "req-1",
                "original_query": "485 怎么配置",
                "feedback_polarity": "negative",
                "citation_count": 0,
                "final_context_filenames": ["manual-a.pdf", "wiring-guide.md"],
            },
            {
                "interaction_id": "req-2",
                "original_query": "PLC 接线图 在哪",
                "feedback_polarity": "positive",
                "citation_count": 2,
                "final_context_filenames": ["manual-a.pdf"],
            },
        ]
    )

    assert scatter["schema"] == "mimirq.dataset_analysis.umap_scatter.v1"
    assert scatter["point_count"] >= 4
    groups = {str(point.get("group") or "") for point in scatter["points"]}
    assert "document" in groups
    assert "out_of_scope_candidate" in groups
    assert "query" in groups
    for point in scatter["points"]:
        assert isinstance(point["x"], float)
        assert isinstance(point["y"], float)
