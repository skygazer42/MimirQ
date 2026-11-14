from typing import Any, TypedDict

_MODE_ALIASES = {
    "": "",
    "none": "",
    "off": "",
    "default": "",
    "deterministic": "deterministic_recall",
    "deterministic_recall": "deterministic_recall",
    "must_recall": "must_recall_strict",
    "must_recall_strict": "must_recall_strict",
    "strict": "evidence_strict",
    "strict_visible": "evidence_strict",
    "evidence_strict": "evidence_strict",
    "audit": "audit_trace",
    "audit_trace": "audit_trace",
}

VALID_RETRIEVAL_CONTRACT_MODES = {
    "",
    "deterministic_recall",
    "must_recall_strict",
    "evidence_strict",
    "audit_trace",
}


class _RetrievalContractPolicy(TypedDict):
    mode: str
    deterministic_recall: bool
    must_recall_strict: bool
    hard_fallback_enabled: bool
    hard_fallback_mode: str
    hard_fallback_top_k: int
    force_visible_evidence_only: bool
    require_evidence_spans: bool
    claim_check_required: bool
    enable_partial_miss_second_pass: bool
    must_recall_required_source_key_match: bool
    contract_fail_reason_taxonomy: str


def normalize_retrieval_contract_mode(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().lower()
    return _MODE_ALIASES.get(raw, raw)


def resolve_retrieval_contract_policy(
    *,
    mode: Any,
    requested_top_k: int,
    hard_fallback_enabled_setting: bool,
    hard_fallback_mode_setting: str,
    hard_fallback_top_k_setting: int,
    visible_evidence_only_setting: bool,
    evidence_span_strict_setting: bool,
) -> _RetrievalContractPolicy:
    normalized_mode = normalize_retrieval_contract_mode(mode)
    if normalized_mode not in VALID_RETRIEVAL_CONTRACT_MODES:
        normalized_mode = ""

    deterministic_recall = normalized_mode in {"deterministic_recall", "must_recall_strict"}
    must_recall_strict = normalized_mode == "must_recall_strict"
    evidence_strict = normalized_mode == "evidence_strict"

    hard_fallback_enabled = bool(hard_fallback_enabled_setting)
    hard_fallback_mode = str(hard_fallback_mode_setting or "keyword").strip().lower() or "keyword"
    hard_fallback_top_k = max(1, int(hard_fallback_top_k_setting or 1))
    if deterministic_recall:
        hard_fallback_enabled = True
        hard_fallback_mode = "keyword"
        hard_fallback_top_k = max(hard_fallback_top_k, int(requested_top_k or 0), 20)

    force_visible_evidence_only = bool(visible_evidence_only_setting or evidence_strict)
    require_evidence_spans = bool(evidence_span_strict_setting or evidence_strict or must_recall_strict)

    return {
        "mode": normalized_mode,
        "deterministic_recall": deterministic_recall,
        "must_recall_strict": must_recall_strict,
        "hard_fallback_enabled": hard_fallback_enabled,
        "hard_fallback_mode": hard_fallback_mode,
        "hard_fallback_top_k": hard_fallback_top_k,
        "force_visible_evidence_only": force_visible_evidence_only,
        "require_evidence_spans": require_evidence_spans,
        "claim_check_required": force_visible_evidence_only,
        "enable_partial_miss_second_pass": must_recall_strict,
        "must_recall_required_source_key_match": must_recall_strict,
        "contract_fail_reason_taxonomy": "mimirq.contract_fail_reason.v1",
    }


__all__ = [
    "VALID_RETRIEVAL_CONTRACT_MODES",
    "normalize_retrieval_contract_mode",
    "resolve_retrieval_contract_policy",
]
