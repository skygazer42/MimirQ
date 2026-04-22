from __future__ import annotations

from app.rag.evaluation.poc_runner.coverage_heatmap import build_document_heatmap


def test_build_document_heatmap_tracks_retrieval_and_negative_feedback_heat() -> None:
    heatmap = build_document_heatmap(
        [
            {"final_context_filenames": ["manual-a.pdf", "manual-b.pdf"], "feedback_polarity": "negative"},
            {"final_context_filenames": ["manual-a.pdf"], "feedback_polarity": "positive"},
            {"final_context_filenames": ["manual-a.pdf"], "feedback_polarity": "negative"},
        ]
    )

    assert heatmap["rows"][0] == {
        "filename": "manual-a.pdf",
        "retrieval_hit_count": 3,
        "negative_feedback_count": 2,
    }
    assert heatmap["rows"][1] == {
        "filename": "manual-b.pdf",
        "retrieval_hit_count": 1,
        "negative_feedback_count": 1,
    }
    assert heatmap["x_axis"] == ["retrieval_hit_count", "negative_feedback_count"]
    assert ["manual-a.pdf", "retrieval_hit_count", 3] in heatmap["cells"]
