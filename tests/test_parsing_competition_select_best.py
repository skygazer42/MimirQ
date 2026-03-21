from __future__ import annotations


def test_select_best_parse_attempt_prefers_grade_then_score_then_content():
    from app.parsing.quality.competition import select_best_parse_attempt  # noqa: WPS433

    attempts = [
        {"backend": "a", "grade": "warn", "parse_score": 0.9, "content_chars": 100},
        {"backend": "b", "grade": "pass", "parse_score": 0.3, "content_chars": 50},
        {"backend": "c", "grade": "warn", "parse_score": 0.95, "content_chars": 5000},
    ]

    # 'pass' wins even with lower score.
    assert select_best_parse_attempt(attempts)["backend"] == "b"


def test_select_best_parse_attempt_breaks_ties_by_score_then_content():
    from app.parsing.quality.competition import select_best_parse_attempt  # noqa: WPS433

    attempts = [
        {"backend": "a", "grade": "warn", "parse_score": 0.4, "content_chars": 1000},
        {"backend": "b", "grade": "warn", "parse_score": 0.6, "content_chars": 10},
        {"backend": "c", "grade": "warn", "parse_score": 0.6, "content_chars": 999},
    ]

    assert select_best_parse_attempt(attempts)["backend"] == "c"


def test_select_best_parse_attempt_supports_weighted_quality_matrix() -> None:
    from app.parsing.quality.competition import select_best_parse_attempt  # noqa: WPS433

    attempts = [
        {
            "backend": "text_heavy",
            "grade": "warn",
            "parse_score": 0.82,
            "table_score": 0.20,
            "image_score": 0.10,
            "reading_order_score": 0.20,
            "content_chars": 1000,
        },
        {
            "backend": "balanced",
            "grade": "warn",
            "parse_score": 0.68,
            "table_score": 0.92,
            "image_score": 0.80,
            "reading_order_score": 0.90,
            "content_chars": 800,
        },
    ]

    best = select_best_parse_attempt(
        attempts,
        weights={
            "text": 0.40,
            "table": 0.30,
            "image": 0.15,
            "reading_order": 0.15,
        },
    )

    assert best["backend"] == "balanced"
