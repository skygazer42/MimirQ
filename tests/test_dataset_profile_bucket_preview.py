from __future__ import annotations


def test_dataset_profile_bucket_preview_scrubs_pii_and_secrets() -> None:
    from app.services.dataset_profile_service import _safe_preview

    text = "Contact: test@example.com\nToken: sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456\n"
    preview, truncated = _safe_preview(text, max_chars=240)

    assert truncated is False
    assert preview is not None
    assert "\n" not in preview  # collapsed
    assert "test@example.com" not in preview
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456" not in preview
    assert "[REDACTED]" in preview
    assert "[SECRET]" in preview


def test_dataset_profile_bucket_preview_marks_truncation() -> None:
    from app.services.dataset_profile_service import _safe_preview

    text = "a" * 5000
    preview, truncated = _safe_preview(text, max_chars=120)

    assert preview is not None
    assert len(preview) <= 120
    assert truncated is True

