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


def test_select_best_parse_attempt_can_use_competition_matrix_weights():
    from app.parsing.quality.competition import select_best_parse_attempt  # noqa: WPS433

    attempts = [
        {"backend": "a", "grade": "warn", "parse_score": 0.9, "content_chars": 100, "text_score": 0.1},
        {"backend": "b", "grade": "warn", "parse_score": 0.1, "content_chars": 100, "text_score": 0.9},
    ]

    best = select_best_parse_attempt(attempts, weights={"text": 1.0})
    assert best["backend"] == "b"
