from app.core.config import settings
from app.rag.safety.output_guard import OutputGuard


def test_output_guard_accepts_zero_thresholds(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OUTPUT_GUARD_MODE", "block")
    monkeypatch.setattr(settings, "OUTPUT_GUARD_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr(settings, "OUTPUT_GUARD_WARN_THRESHOLD", 0.0)

    assert OutputGuard._resolve_action(score=0.0, matched_rules=["test_rule"]) == "block"
