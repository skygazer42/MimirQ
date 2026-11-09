import pytest

from app.rag.preprocessing.normalization import normalize_query, normalize_text


@pytest.mark.parametrize("value", [None, 0, False])
def test_required_normalization_text_does_not_become_empty(value):
    with pytest.raises((AttributeError, TypeError)):
        normalize_text(value)


def test_normalization_preserves_empty_text_and_normalizes_real_text():
    assert normalize_text("") == ""
    assert normalize_text("A\r\nB\u00a0\ufb01\u200b\x00") == "A\nB fi"
    assert normalize_query(" A\r\n B\u00a0fi ") == "A B fi"
