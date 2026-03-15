import pytest

from app.parsing.quality.text_quality import score_parsed_text_quality


def test_score_parsed_text_quality_basic_metrics():
    score = score_parsed_text_quality("abc 123")
    assert score.content_chars == 6
    assert score.chars_non_space == 6
    assert score.density == pytest.approx(1.0)
    assert score.replacement_chars == 0
    assert score.replacement_ratio == pytest.approx(0.0)
    assert score.lines == 1
    assert score.avg_line_len == pytest.approx(6.0)


def test_score_parsed_text_quality_replacement_ratio_counts_fffd():
    score = score_parsed_text_quality("a\ufffdb")
    assert score.replacement_chars == 1
    assert score.replacement_ratio > 0

