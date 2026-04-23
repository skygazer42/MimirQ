from __future__ import annotations

from app.rag.preprocessing.pii_presidio import analyze_pii_text, anonymize_pii_text


def test_analyze_pii_text_detects_common_and_cn_specific_entities() -> None:
    out = analyze_pii_text(
        "Email: test@example.com 手机号: 13800138000 身份证: 110105199001010010 车牌: 京A12345 社保号: 123456789012"
    )

    assert out["schema"] == "mimirq.pii_presidio_analysis.v1"
    kinds = [item["entity_type"] for item in out["entities"]]
    assert "EMAIL_ADDRESS" in kinds
    assert "PHONE_NUMBER" in kinds
    assert "CN_ID" in kinds
    assert "CN_LICENSE_PLATE" in kinds
    assert "CN_SOCIAL_SECURITY" in kinds


def test_anonymize_pii_text_replaces_detected_entities_with_mask() -> None:
    out = anonymize_pii_text(
        "请联系 test@example.com 或拨打 13800138000，车牌京A12345。",
        mask="[X]",
    )

    assert out["schema"] == "mimirq.pii_presidio_anonymize.v1"
    assert out["changed"] is True
    assert "test@example.com" not in out["text"]
    assert "13800138000" not in out["text"]
    assert "京A12345" not in out["text"]
    assert out["text"].count("[X]") >= 3
