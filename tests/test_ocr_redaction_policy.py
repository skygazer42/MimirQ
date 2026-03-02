from __future__ import annotations


def test_redact_ocr_text_masks_common_pii_when_enabled() -> None:
    from app.parsing.enrich.ocr_redaction import redact_ocr_text

    text = "Email alice@example.com, SSN 123-45-6789, phone +1 (555) 123-4567."
    out, pii_hits, sec_hits = redact_ocr_text(
        text,
        pii_anonymize=True,
        pii_mode="mask",
        pii_mask="[REDACTED]",
        secrets_redact=False,
    )

    assert "[REDACTED]" in out
    assert pii_hits
    assert not sec_hits


def test_redact_ocr_text_noop_when_disabled() -> None:
    from app.parsing.enrich.ocr_redaction import redact_ocr_text

    text = "Email alice@example.com"
    out, pii_hits, sec_hits = redact_ocr_text(
        text,
        pii_anonymize=False,
        secrets_redact=False,
    )
    assert out == text
    assert pii_hits == {}
    assert sec_hits == {}


def test_chunk_asset_stage_wires_policy_redaction() -> None:
    # Contract check: the ingestion pipeline should call redact_ocr_text in ChunkAssetStage.
    from pathlib import Path

    text = Path("app/parsing/processors/processor.py").read_text(encoding="utf-8")
    assert "redact_ocr_text(" in text
    assert "pii_anonymize=" in text

