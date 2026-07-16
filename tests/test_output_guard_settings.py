import pytest

from app.core.config import settings
from app.rag.safety.output_guard import OutputGuard
from app.rag.safety.regex_safety_guard import RegexSafetyGuard


def test_output_guard_accepts_zero_thresholds(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OUTPUT_GUARD_MODE", "block")
    monkeypatch.setattr(settings, "OUTPUT_GUARD_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr(settings, "OUTPUT_GUARD_WARN_THRESHOLD", 0.0)

    assert OutputGuard._resolve_action(score=0.0, matched_rules=["test_rule"]) == "block"


@pytest.mark.asyncio
async def test_output_guards_detect_pii_adjacent_to_chinese() -> None:
    text = "电话13800138000，身份证138001380001234567"

    output_result = OutputGuard()._check_sync(text, [])
    safety_result = await RegexSafetyGuard().guard_agent_response(text)

    assert {"pii_phone", "pii_id_card"} <= set(output_result.matched_rules)
    assert safety_result.action == "block"
    assert safety_result.categories == ["sensitive_info"]
