import pytest

from app.rag.kg.extraction.alias import (
    AliasCandidate,
    extract_alias_candidates,
    is_abbrev_token,
    split_trailing_parenthetical_alias,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Large Language Model (LLM)", ("Large Language Model", "LLM")),
        ("统一身份认证（SSO）", ("统一身份认证", "SSO")),
        ("No alias", None),
        ("Mismatched (alias）", ("Mismatched", "alias")),
        ("Mismatched（alias)", ("Mismatched", "alias")),
        ("(alias)", None),
        ("Name ()", None),
        ("Name (x)", None),
        ("Name (nested(value))", None),
        ("Same (Same)", None),
        ("Name (" + "x" * 41 + ")", None),
    ],
)
def test_split_trailing_parenthetical_alias_preserves_validation_contract(
    name: str,
    expected: tuple[str, str] | None,
) -> None:
    assert split_trailing_parenthetical_alias(name) == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("RAG", True),
        ("Foo", False),
        ("GPT-4", True),
        ("DeepSeekV3", True),
        ("123", False),
        ("v2", False),
        ("清华", True),
        ("中科院", True),
        ("清华大学", False),
        ("微软公司", False),
        ("中A", False),
        ("A", False),
    ],
)
def test_is_abbrev_token_preserves_precision_heuristic(token: str, expected: bool) -> None:
    assert is_abbrev_token(token) is expected


def test_extract_alias_candidates_preserves_method_order_quotes_and_deduplication() -> None:
    text = (
        "Retrieval-Augmented Generation (RAG)\n"
        "Retrieval-Augmented Generation (RAG)\n"
        "统一身份认证，简称 SSO\n"
        "Large Language Model, aka LLM"
    )

    assert extract_alias_candidates(text) == [
        AliasCandidate(
            a="Retrieval-Augmented Generation",
            b="RAG",
            method="parentheses",
            quote="Retrieval-Augmented Generation (RAG)",
        ),
        AliasCandidate(
            a="统一身份认证",
            b="SSO",
            method="zh_abbr",
            quote="统一身份认证,简称 SSO",
        ),
        AliasCandidate(
            a="Large Language Model",
            b="LLM",
            method="en_aka",
            quote="Large Language Model, aka LLM",
        ),
    ]
    assert extract_alias_candidates(text, max_candidates=2) == extract_alias_candidates(text)[:2]
    assert extract_alias_candidates(text, max_candidates=0) == []
