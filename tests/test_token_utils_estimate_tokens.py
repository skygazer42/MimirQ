from __future__ import annotations


def test_estimate_tokens_ascii_matches_legacy() -> None:
    from app.core.token_utils import estimate_tokens

    text = "hello world"
    assert estimate_tokens(text) == max(1, len(text) // 4)


def test_estimate_tokens_cjk_counts_characters() -> None:
    from app.core.token_utils import estimate_tokens

    text = "你好世界"
    assert estimate_tokens(text) == len(text)


def test_estimate_tokens_mixed_cjk_and_ascii() -> None:
    from app.core.token_utils import estimate_tokens

    # 2 CJK chars + 5 non-CJK chars -> 2 + (5 // 4) = 3
    text = "hello你好"
    assert estimate_tokens(text) == 3

