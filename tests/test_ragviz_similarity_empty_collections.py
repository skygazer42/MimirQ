from __future__ import annotations

from uuid import UUID

import pytest

from app.services import ragviz_similarity


def test_similarity_matrix_reports_empty_axis(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_collection_items(db, tenant_id, account_id, collection_id, *, max_items):  # noqa: ANN001
        if collection_id == "dataset_chunks:ok":
            return ([{"id": "chunk-1", "text": "有数据"}], ["有数据"])
        return ([], [])

    monkeypatch.setattr(ragviz_similarity, "get_collection_items", fake_get_collection_items)

    with pytest.raises(ValueError, match="Y 轴无数据: regression_questions:empty"):
        ragviz_similarity.calculate_similarity_matrix(
            None,
            UUID("00000000-0000-0000-0000-000000000000"),
            "demo",
            x_collection="dataset_chunks:ok",
            y_collection="regression_questions:empty",
            x_max_items=100,
            y_max_items=100,
        )
