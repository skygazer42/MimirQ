from __future__ import annotations

from typing import Any

from app.rag.preprocessing.pii_anonymizer import anonymize_pii, find_pii_matches
from app.rag.preprocessing.secrets import find_secret_matches, redact_secrets


def _mask_pii_value(kind: str, text: str) -> str:
    value = str(text or "")
    if kind == "email" and "@" in value:
        left, right = value.split("@", 1)
        return f"{left[:3]}****@{right}"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}****{value[-2:]}"


def _mask_secret_value(kind: str, text: str) -> str:
    value = str(text or "")
    if kind == "openai_key" and value.startswith("sk-"):
        return "sk-****"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}****{value[-2:]}"


def collect_sensitive_review_samples(
    text: str,
    *,
    pii_context_chars: int = 50,
    secrets_context_chars: int = 50,
    max_pii_samples: int = 10,
    max_secret_samples: int = 10,
) -> dict[str, Any]:
    raw = str(text or "")
    pii_context_chars = max(0, min(int(pii_context_chars or 0), 500))
    secrets_context_chars = max(0, min(int(secrets_context_chars or 0), 500))

    pii_masked = anonymize_pii(raw, enabled=True, mode="mask")
    secrets_masked = redact_secrets(raw, enabled=True, mode="mask")

    samples: list[dict[str, Any]] = []
    for match in find_pii_matches(raw, max_matches=max_pii_samples):
        start = int(match.start)
        end = int(match.end)
        ctx = raw[max(0, start - pii_context_chars) : min(len(raw), end + pii_context_chars)]
        ctx = anonymize_pii(ctx, enabled=True, mode="mask").text
        ctx = redact_secrets(ctx, enabled=True, mode="mask").text
        samples.append(
            {
                "category": "pii",
                "kind": str(match.kind),
                "masked": _mask_pii_value(str(match.kind), str(match.text)),
                "context": ctx,
                "start": start,
                "end": end,
            }
        )

    for match in find_secret_matches(raw, max_matches=max_secret_samples):
        start = int(match.start)
        end = int(match.end)
        ctx = raw[max(0, start - secrets_context_chars) : min(len(raw), end + secrets_context_chars)]
        ctx = anonymize_pii(ctx, enabled=True, mode="mask").text
        ctx = redact_secrets(ctx, enabled=True, mode="mask").text
        samples.append(
            {
                "category": "secret",
                "kind": str(match.kind),
                "masked": _mask_secret_value(str(match.kind), str(match.text)),
                "context": ctx,
                "start": start,
                "end": end,
            }
        )

    return {
        "schema": "mimirq.pre_poc.sensitive_review.v1",
        "pii_hits_total": {str(k): int(v) for k, v in (pii_masked.hits or {}).items()},
        "secrets_hits_total": {str(k): int(v) for k, v in (secrets_masked.hits or {}).items()},
        "samples": samples,
    }


__all__ = ["collect_sensitive_review_samples"]
