from __future__ import annotations


def test_score_reading_order_returns_full_score_for_ordered_single_column_items() -> None:
    from app.parsing.quality.reading_order import score_reading_order

    items = [
        {"page": 1, "x0": 10, "y0": 10, "x1": 50, "y1": 20, "text": "alpha"},
        {"page": 1, "x0": 10, "y0": 30, "x1": 50, "y1": 40, "text": "beta"},
        {"page": 1, "x0": 10, "y0": 50, "x1": 50, "y1": 60, "text": "gamma"},
    ]

    result = score_reading_order(items)

    assert result["score"] == 1.0
    assert result["items"] == 3
    assert result["pages"] == 1


def test_score_reading_order_penalizes_interleaved_two_column_observed_order() -> None:
    from app.parsing.quality.reading_order import score_reading_order

    items = [
        {"page": 1, "x0": 10, "y0": 10, "x1": 60, "y1": 20, "text": "left top"},
        {"page": 1, "x0": 120, "y0": 10, "x1": 170, "y1": 20, "text": "right top"},
        {"page": 1, "x0": 10, "y0": 35, "x1": 60, "y1": 45, "text": "left bottom"},
        {"page": 1, "x0": 120, "y0": 35, "x1": 170, "y1": 45, "text": "right bottom"},
    ]

    result = score_reading_order(items)

    assert result["multi_column_pages"] == 1
    assert result["score"] < 1.0
    assert result["inversions"] > 0


def test_score_reading_order_returns_neutral_when_geometry_is_missing() -> None:
    from app.parsing.quality.reading_order import score_reading_order

    result = score_reading_order([{"page": 1, "text": "alpha"}])

    assert result["score"] == 1.0
    assert result["items"] == 0
