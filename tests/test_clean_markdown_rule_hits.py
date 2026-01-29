from app.rag.preprocessing.cleaning import RegexRule, clean_markdown


def test_clean_markdown_reports_rule_hits():
    res = clean_markdown(
        "foo foo",
        rules=[RegexRule(pattern=r"foo", repl="bar", flags=0)],
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        trim_trailing_spaces=False,
        collapse_blank_lines=False,
    )

    assert res.markdown == "bar bar"
    assert res.applied_rules == 1
    assert res.changed is True
    assert res.rule_hits == [2]


def test_clean_markdown_rule_hits_zero_when_no_match():
    res = clean_markdown(
        "hello",
        rules=[RegexRule(pattern=r"foo", repl="bar", flags=0)],
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        trim_trailing_spaces=False,
        collapse_blank_lines=False,
    )

    assert res.markdown == "hello"
    assert res.applied_rules == 0
    assert res.changed is False
    assert res.rule_hits == [0]

