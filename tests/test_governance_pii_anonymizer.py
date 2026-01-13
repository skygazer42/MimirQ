from app.rag.preprocessing.pii_anonymizer import anonymize_pii


def test_anonymize_pii_mask_mode_replaces_common_patterns():
    text = (
        "Email: test@example.com\n"
        "Phone: 13800138000\n"
        "CN ID: 110105199001010010\n"
        "Card: 4111 1111 1111 1111\n"
        "IP: 192.0.2.1\n"
    )
    res = anonymize_pii(text, enabled=True, mode="mask", mask="[X]")
    assert "[X]" in res.text
    assert "test@example.com" not in res.text
    assert "13800138000" not in res.text
    assert "110105199001010010" not in res.text
    assert "4111 1111 1111 1111" not in res.text
    assert "192.0.2.1" not in res.text
    assert res.hits.get("email", 0) >= 1
    assert res.hits.get("phone", 0) >= 1
    assert res.hits.get("cn_id", 0) >= 1
    assert res.hits.get("credit_card", 0) >= 1
    assert res.hits.get("ip", 0) >= 1


def test_anonymize_pii_token_mode_is_stable_per_value():
    text = "Email test@example.com; again test@example.com."
    res = anonymize_pii(text, enabled=True, mode="token", mask="[REDACTED]")
    assert res.text.count("[PII_EMAIL_1]") == 2
    assert res.hits.get("email") == 2


def test_anonymize_pii_does_not_replace_invalid_credit_card():
    text = "Not a card: 1234 5678 9012 3456"
    res = anonymize_pii(text, enabled=True, mode="mask", mask="[X]")
    assert "1234 5678 9012 3456" in res.text
    assert res.hits.get("credit_card", 0) == 0

