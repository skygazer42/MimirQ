
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.http_client import get_http_client_pool
from app.core.openai_compat import normalize_openai_compatible_base_url

logger = logging.getLogger("mimirq.claim_nli")

_LABEL_RE = re.compile(r"\b(entailment|contradiction|neutral)\b", flags=re.IGNORECASE)


def normalize_claim_nli_provider(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"", "none", "off", "false", "0", "disabled"}:
        return "none"
    if raw in {"openai", "openai-compatible", "openai_compatible"}:
        return "openai_compatible"
    return raw


def describe_claim_nli_provider(provider: str | None, *, enabled: bool | None = None) -> dict[str, Any]:
    normalized = normalize_claim_nli_provider(provider)
    enabled_flag = bool(enabled) if enabled is not None else bool(
        getattr(settings, "RAG_CLAIM_NLI_VERIFIER_ENABLED", False)
    )
    if not enabled_flag or normalized == "none":
        return {"provider": "none", "tier": "disabled", "enabled": False}
    if normalized == "openai_compatible":
        return {"provider": "openai_compatible", "tier": "experimental", "enabled": True}
    return {"provider": normalized, "tier": "experimental", "enabled": enabled_flag}


@dataclass(frozen=True)
class ClaimNLIVerificationResult:
    available: bool
    supported: bool | None
    label: str | None
    provider_status: dict[str, Any]
    diagnostics: dict[str, Any]


def _extract_label(content: str) -> tuple[str | None, str | None]:
    raw = str(content or "").strip()
    if not raw:
        return None, None
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        label = str(parsed.get("label") or "").strip().lower() or None
        reason = str(parsed.get("reason") or "").strip() or None
        if label in {"entailment", "contradiction", "neutral"}:
            return label, reason

    match = _LABEL_RE.search(raw)
    if match:
        return str(match.group(1) or "").strip().lower(), raw[:240]
    return None, raw[:240]


def verify_claim_with_nli(
    claim: str,
    evidence: str,
    *,
    enabled: bool | None = None,
    provider: str | None = None,
    model_name: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
    timeout_sec: float | None = None,
) -> ClaimNLIVerificationResult:
    enabled_flag = bool(enabled) if enabled is not None else bool(
        getattr(settings, "RAG_CLAIM_NLI_VERIFIER_ENABLED", False)
    )
    provider_norm = normalize_claim_nli_provider(
        provider if provider is not None else getattr(settings, "RAG_CLAIM_NLI_VERIFIER_PROVIDER", "none")
    )
    provider_status = describe_claim_nli_provider(provider_norm, enabled=enabled_flag)

    if not enabled_flag or provider_norm == "none":
        return ClaimNLIVerificationResult(
            available=False,
            supported=None,
            label=None,
            provider_status=provider_status,
            diagnostics={"reason_code": "nli_disabled"},
        )
    if provider_norm != "openai_compatible":
        return ClaimNLIVerificationResult(
            available=False,
            supported=None,
            label=None,
            provider_status=provider_status,
            diagnostics={"reason_code": "nli_provider_unsupported"},
        )

    resolved_model = str(
        model_name
        or getattr(settings, "RAG_CLAIM_NLI_VERIFIER_MODEL", "")
        or getattr(settings, "LLM_MODEL", "")
        or ""
    ).strip()
    resolved_api_key = str(
        api_key
        or getattr(settings, "RAG_CLAIM_NLI_VERIFIER_API_KEY", "")
        or getattr(settings, "LLM_API_KEY", "")
        or ""
    ).strip()
    resolved_api_base = normalize_openai_compatible_base_url(
        api_base
        or getattr(settings, "RAG_CLAIM_NLI_VERIFIER_API_BASE", "")
        or getattr(settings, "LLM_API_BASE", "")
        or ""
    )
    resolved_timeout = float(
        timeout_sec
        if timeout_sec is not None
        else getattr(settings, "RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC", 8) or 8
    )

    if not resolved_model or not resolved_api_key or not resolved_api_base:
        return ClaimNLIVerificationResult(
            available=False,
            supported=None,
            label=None,
            provider_status=provider_status,
            diagnostics={"reason_code": "nli_missing_configuration"},
        )

    client = get_http_client_pool().get_external_sync_client()
    url = f"{resolved_api_base.rstrip('/')}/chat/completions"
    payload = {
        "model": resolved_model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict NLI classifier. "
                    "Return JSON only with keys label and reason. "
                    "label must be one of entailment, contradiction, neutral."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Claim:\n"
                    f"{str(claim or '').strip()}\n\n"
                    "Evidence:\n"
                    f"{str(evidence or '').strip()}\n"
                ),
            },
        ],
    }

    try:
        response = client.post(
            url,
            headers={
                "Authorization": f"Bearer {resolved_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=resolved_timeout,
        )
        response.raise_for_status()
        body = response.json() if response.content else {}
        choices = body.get("choices") if isinstance(body, dict) else None
        content = ""
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else {}
            if isinstance(message, dict):
                content = str(message.get("content") or "")
        label, reason = _extract_label(content)
    except Exception as exc:  # noqa: BLE001
        logger.debug("claim NLI request failed: %s", str(exc)[:200])
        return ClaimNLIVerificationResult(
            available=False,
            supported=None,
            label=None,
            provider_status=provider_status,
            diagnostics={"reason_code": "nli_request_failed", "error": str(exc)[:200]},
        )

    if label not in {"entailment", "contradiction", "neutral"}:
        return ClaimNLIVerificationResult(
            available=False,
            supported=None,
            label=label,
            provider_status=provider_status,
            diagnostics={"reason_code": "nli_invalid_response", "reason": reason},
        )

    return ClaimNLIVerificationResult(
        available=True,
        supported=(label == "entailment"),
        label=label,
        provider_status={**provider_status, "model_name": resolved_model},
        diagnostics={"reason_code": f"nli_{label}", "reason": reason},
    )


__all__ = [
    "ClaimNLIVerificationResult",
    "describe_claim_nli_provider",
    "normalize_claim_nli_provider",
    "verify_claim_with_nli",
]
