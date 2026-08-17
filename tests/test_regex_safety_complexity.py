import pytest

from app.core.regex_safety import (
    RegexRulesValidationError,
    looks_like_nested_quantifier,
    validate_regex_rules,
)


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("", False),
        ("plain text", False),
        ("(abc)+", False),
        ("(a+)+", True),
        ("(a*)*", True),
        ("(?:a+)+", True),
        (r"(a\+)+", False),
        (r"\(a+\)+", False),
        (r"(a+)\+", False),
        (r"(a\\+)+", True),
        ("(a+", False),
    ],
)
def test_looks_like_nested_quantifier_preserves_escape_heuristic(pattern: str, expected: bool) -> None:
    assert looks_like_nested_quantifier(pattern) is expected


def test_validate_regex_rules_normalizes_mapping_and_attribute_rules() -> None:
    class AttributeRule:
        pattern = "beta+$"
        repl = "B"
        flags = 0

    assert validate_regex_rules(
        [
            {"pattern": "^alpha", "repl": "A", "flags": "2"},
            AttributeRule(),
        ]
    ) == [
        {"pattern": "^alpha", "repl": "A", "flags": 2},
        {"pattern": "beta+$", "repl": "B", "flags": 0},
    ]


def test_validate_regex_rules_accumulates_first_failure_per_rule() -> None:
    rules = [
        {"pattern": ""},
        {"pattern": "abcd"},
        {"pattern": "(a+)+"},
        {"pattern": "ok", "repl": "toolong"},
        {"pattern": "ok", "flags": "bad"},
        {"pattern": "ok", "flags": -1},
        {"pattern": "ok", "flags": 8},
        {"pattern": "["},
    ]

    with pytest.raises(RegexRulesValidationError) as exc_info:
        validate_regex_rules(rules, max_pattern_len=3, max_repl_len=3, allowed_flag_bits=2)

    assert [
        (error.index, error.field, error.code)
        for error in exc_info.value.errors
    ] == [
        (0, "pattern", "required"),
        (1, "pattern", "too_long"),
        (2, "pattern", "too_long"),
        (3, "repl", "too_long"),
        (4, "flags", "invalid"),
        (5, "flags", "invalid"),
        (6, "flags", "unsupported"),
        (7, "pattern", "compile_error"),
    ]


def test_validate_regex_rules_preserves_collection_errors_and_empty_input() -> None:
    assert validate_regex_rules(None) == []

    with pytest.raises(RegexRulesValidationError) as type_error:
        validate_regex_rules("not-a-list")
    assert type_error.value.to_detail()["errors"] == [
        {"index": -1, "field": "rules", "code": "type", "message": "expected list"}
    ]

    with pytest.raises(RegexRulesValidationError) as limit_error:
        validate_regex_rules([{"pattern": "a"}, {"pattern": "b"}], max_rules=1)
    assert limit_error.value.to_detail()["errors"] == [
        {"index": -1, "field": "rules", "code": "too_many", "message": "max=1"}
    ]
