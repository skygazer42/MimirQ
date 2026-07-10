
from typing import Any

from app.rag.preprocessing.pii_anonymizer import anonymize_pii
from app.rag.preprocessing.secrets import redact_secrets


def _normalize_mode(raw: Any, *, allowed: set[str], default: str) -> str:
    mode = str(raw or "").strip().lower()
    return mode if mode in allowed else default


def redact_ocr_text(
    text: str,
    *,
    pii_anonymize: bool,
    pii_mode: str = "mask",
    pii_mask: str = "[REDACTED]",
    secrets_redact: bool = False,
    secrets_mode: str = "mask",
    secrets_mask: str = "[SECRET]",
) -> tuple[str, dict[str, int], dict[str, int]]:
    """
    Apply governance-style redactions to OCR-derived text.

    Policy-driven:
    - controlled by the caller (typically pipeline_effective.governance_* flags)

    Returns:
      (redacted_text, pii_hits, secrets_hits)
    """
    s = str(text or "")
    if not s:
        return s, {}, {}

    pii_mode_norm = _normalize_mode(pii_mode, allowed={"mask", "token"}, default="mask")
    secrets_mode_norm = _normalize_mode(secrets_mode, allowed={"mask", "token"}, default="mask")

    pii_res = anonymize_pii(s, enabled=bool(pii_anonymize), mode=pii_mode_norm, mask=str(pii_mask or "[REDACTED]"))
    sec_res = redact_secrets(
        pii_res.text,
        enabled=bool(secrets_redact),
        mode=secrets_mode_norm,
        mask=str(secrets_mask or "[SECRET]"),
    )
    return sec_res.text, dict(pii_res.hits or {}), dict(sec_res.hits or {})


__all__ = ["redact_ocr_text"]

