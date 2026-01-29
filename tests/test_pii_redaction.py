from app.core.config import settings
from app.core.pii_redaction import redact_obj, redact_text
from app.services import metrics_logger


def test_pii_redaction_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "PII_REDACTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "PII_REDACTION_MASK", "[MASK]", raising=False)

    raw = "contact test@example.com sk-aaaaaaaaaaaaaaaaaaaa"
    assert redact_text(raw) == raw
    assert redact_obj({"v": raw}) == {"v": raw}


def test_pii_redaction_enabled_masks_common_patterns(monkeypatch):
    monkeypatch.setattr(settings, "PII_REDACTION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PII_REDACTION_MASK", "[MASK]", raising=False)

    openai_key = "sk-" + ("a" * 20)
    aws_key = "AKIA" + ("A" * 16)
    card = "4111 1111 1111 1111"

    raw = f"email=test@example.com openai={openai_key} aws={aws_key} card={card} bearer=supersecret123"
    out = redact_text(raw)

    assert "test@example.com" not in out
    assert openai_key not in out
    assert aws_key not in out
    assert card not in out
    assert "[MASK]" in out
    assert "bearer=[MASK]" in out

    obj_out = redact_obj({"email": "test@example.com", "nested": {"token": openai_key}})
    assert obj_out["email"] == "[MASK]"
    assert obj_out["nested"]["token"] == "[MASK]"


def test_metrics_logger_maybe_redact_uses_core(monkeypatch):
    monkeypatch.setattr(settings, "PII_REDACTION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PII_REDACTION_MASK", "[MASK]", raising=False)

    record = {"question": "hi test@example.com", "meta": {"api_key": "sk-" + ("b" * 20)}}
    out = metrics_logger._maybe_redact(record)
    assert isinstance(out, dict)
    assert out["question"] != record["question"]
    assert "test@example.com" not in out["question"]
    assert "[MASK]" in out["question"]
    assert out["meta"]["api_key"] == "[MASK]"

