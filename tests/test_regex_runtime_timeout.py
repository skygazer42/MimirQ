from __future__ import annotations


def test_safe_subn_timeout_raises_structured_error():  # noqa: ANN001
    from app.core.regex_runtime import RegexSubstitutionTimeoutError, safe_subn

    # Classic catastrophic-backtracking shape on a failing input.
    text = ("a" * 1000) + "b"

    try:
        safe_subn(pattern=r"(a+)+$", repl="", text=text, timeout_ms=1, rule_index=3)
    except RegexSubstitutionTimeoutError as exc:
        detail = exc.to_detail()
        assert detail.get("code") == "regex_timeout"
        assert detail.get("rule_index") == 3
        assert detail.get("timeout_ms") == 1
        assert "(a+)+$" in str(detail.get("pattern") or "")
    else:
        raise AssertionError("expected RegexSubstitutionTimeoutError")


def test_clean_markdown_skips_timed_out_rule_and_keeps_document():  # noqa: ANN001
    from app.rag.preprocessing.cleaning import RegexRule, clean_markdown

    text = ("a" * 1000) + "b"
    result = clean_markdown(text, rules=[RegexRule(pattern=r"(a+)+$", repl="", flags=0)], regex_timeout_ms=1)

    assert result.markdown == text
    assert result.stats["regex_timeout_count"] == 1
    assert result.stats["regex_timeout_rules"][0]["rule_index"] == 0
