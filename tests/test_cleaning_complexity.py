from app.rag.preprocessing.cleaning import (
    build_common_line_signatures,
    learn_common_line_candidates,
)


def test_common_line_signatures_skip_structure_and_count_each_document_once() -> None:
    texts = [
        "Acme Handbook Page 1\nShared footer\nShared footer\n# Structural heading\n```\ncode repeat\n```",
        "Acme Handbook Page 2\nshared footer\n# Structural heading\n```\ncode repeat\n```",
        "Acme Handbook Page 3\nSHARED FOOTER\n# Structural heading\n```\ncode repeat\n```",
    ]

    signatures = build_common_line_signatures(texts, min_docs=3, min_ratio=1.0)

    assert signatures == {"acme handbook", "shared footer"}


def test_common_line_signatures_apply_length_and_document_thresholds() -> None:
    texts = [
        "short common\nrare line\nvery long common line",
        "short common\nvery long common line",
        "short common\nvery long common line",
    ]

    signatures = build_common_line_signatures(
        texts,
        min_docs=3,
        min_ratio=1.0,
        max_line_length=12,
    )

    assert signatures == {"short common"}


def test_common_line_candidates_preserve_sample_frequency_order_and_cap() -> None:
    texts = [
        "Alpha Banner\nBeta notice\nGamma footer",
        "alpha banner\nBeta notice\nGamma footer",
        "ALPHA BANNER\nBeta notice",
        "Alpha Banner",
    ]

    candidates = learn_common_line_candidates(
        texts,
        min_docs=2,
        min_ratio=0.5,
        max_candidates=2,
    )

    assert candidates == [
        {"signature": "alpha banner", "sample": "Alpha Banner", "docs": 4, "ratio": 1.0},
        {"signature": "beta notice", "sample": "Beta notice", "docs": 3, "ratio": 0.75},
    ]


def test_common_line_candidates_return_empty_when_document_floor_is_unmet() -> None:
    assert learn_common_line_candidates(["header", "header"], min_docs=3) == []
