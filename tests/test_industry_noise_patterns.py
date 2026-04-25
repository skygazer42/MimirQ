from __future__ import annotations

import re

import pytest


def test_industry_noise_patterns_registry_lists_expected_profiles() -> None:
    from app.parsing.preprocess.industry_noise_patterns import list_industry_noise_profiles

    assert set(list_industry_noise_profiles()) >= {"industrial_control", "finance", "legal"}


def test_industry_noise_patterns_returns_rules_for_industrial_control() -> None:
    from app.parsing.preprocess.industry_noise_patterns import get_industry_noise_rules

    rules = get_industry_noise_rules("industrial_control")

    patterns = [rule.pattern for rule in rules]
    assert any("点击文件名下载附件" in pattern for pattern in patterns)
    assert any("下载次数" in pattern for pattern in patterns)

    text = "点击文件名下载附件"
    assert any(re.search(rule.pattern, text) for rule in rules)


def test_industry_noise_patterns_rejects_unknown_profile() -> None:
    from app.parsing.preprocess.industry_noise_patterns import get_industry_noise_rules

    with pytest.raises(ValueError, match="unsupported industry noise profile"):
        get_industry_noise_rules("unknown")
