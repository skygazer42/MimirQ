"""
Query intent router -> retrieval presets.

Design goals:
- Deterministic (no LLM calls).
- Low-cardinality + PII-safe metadata (no raw query text in outputs).
- Bounded (small objects; short reason codes).

This is used to automatically pick retrieval presets/profiles and toggles
based on the query "shape" (faq/howto/api/log) when enabled.
"""


import re
from typing import Any

from app.rag.core.retrieval_profiles import PRODUCTION_RETRIEVAL_PROFILE
from app.rag.core.text import normalize_retrieval_mode
from app.rag.policy.intent_router_model import (
    load_intent_router_model,
    normalize_intent_router_model,
    predict_learned_router_hint,
)

_INTENT_ROUTER_POLICY_SCHEMA_V1 = "mimirq.intent_router_policy.v1"
_ADAPTIVE_ROUTER_POLICY_SCHEMA_V1 = "mimirq.adaptive_router_policy.v1"

_INTENT_LOG_RE = re.compile(
    r"(traceback|stack\s*trace|exception|segfault|panic|fatal|caused\s+by|"
    r"\bSIG(?:SEGV|ABRT|BUS)\b|"
    r"\bERROR\b|\bWARN(?:ING)?\b|"
    r"\bNullPointerException\b|\bTypeError\b|\bValueError\b|\bKeyError\b|"
    r"\bAssertionError\b|\bRuntimeError\b|"
    r"^\s*at\s+.+\(.+\)\s*$|"
    r"^\s*File\s+\".+\",\s+line\s+\d+\s*$)",
    flags=re.IGNORECASE | re.MULTILINE,
)

_INTENT_API_RE = re.compile(
    r"(\bGET\b|\bPOST\b|\bPUT\b|\bPATCH\b|\bDELETE\b)\s+/(?:\S+)?|"
    r"\bcurl\b|\bHTTP/\d\.\d\b|\bstatus\s*code\b|\bendpoint\b|"
    r"\bContent-Type\b|\bAuthorization\b|"
    r"application/json|\bJSON\b|\bGraphQL\b|\bgRPC\b",
    flags=re.IGNORECASE,
)

_INTENT_HOWTO_RE = re.compile(
    r"(how\s+to|how\s+do\s+i|steps?\s+to|guide(?:\s+to)?|tutorial|"
    r"如何|怎么|步骤|流程|指南|手把手|排查|定位|修复|解决)",
    flags=re.IGNORECASE,
)

_INTENT_FAQ_RE = re.compile(
    r"(what\s+is|what'?s|meaning\s+of|define|definition|"
    r"是什么|什么是|含义|定义|解释)",
    flags=re.IGNORECASE,
)

_SOCIAL_BOUNDARY_CHARS = "!,.?~。！？、，"
_GREETING_TERMS = {"hi", "hello", "hey", "你好", "您好", "嗨", "哈喽", "早上好", "下午好", "晚上好"}
_THANKS_TERMS = {"thanks", "thank you", "thx", "谢谢", "多谢", "感谢", "辛苦了"}
_SMALLTALK_TERMS = {
    "how are you",
    "who are you",
    "what can you do",
    "在吗",
    "你在吗",
    "你是谁",
    "你能做什么",
    "你会什么",
}

_POLICY_ALLOWED_OVERRIDES = {
    "retrieval_mode",
    "retrieval_profile",
    "top_k",
    "score_threshold",
    "enable_reranker",
    "reranker_provider",
    "reranker_top_n",
    "enable_weight_rerank",
    "enable_multi_query",
    "enable_query_alias_expansion",
    "vector_weight",
    "keyword_weight",
    "mmr_lambda",
}
_INVALID_POLICY_OVERRIDE = object()


def _bounded_reason_codes(reasons: list[str], *, max_items: int = 6) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for r in reasons:
        s = str(r or "").strip().lower()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s[:40])
        if len(out) >= max_items:
            break
    return out


def _normalize_match_terms(raw: Any, *, max_items: int = 8) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        term = " ".join(str(item or "").strip().split())
        if not term:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(term[:40])
        if len(out) >= max_items:
            break
    return out


def _normalize_social_query(query: str) -> str:
    text = " ".join(str(query or "").strip().split()).casefold()
    while text:
        stripped = text.strip(_SOCIAL_BOUNDARY_CHARS).strip()
        if stripped == text:
            break
        text = stripped
    return text


def _matches_social_query(query: str, terms: set[str]) -> bool:
    text = _normalize_social_query(query)
    return bool(text and text in terms)


def _coerce_policy_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return None


def _coerce_policy_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    try:
        iv = int(value) if value is not None else None
    except Exception:
        return None
    if iv is None:
        return None
    return max(minimum, min(maximum, iv))


def _coerce_policy_float(value: Any, *, minimum: float, maximum: float) -> float | None:
    try:
        fv = float(value) if value is not None else None
    except Exception:
        return None
    if fv is None:
        return None
    return max(minimum, min(maximum, fv))


def _normalize_policy_override(name: str, value: Any) -> Any:
    if name == "retrieval_mode":
        mode = normalize_retrieval_mode(value if value is not None else None)
        return mode or _INVALID_POLICY_OVERRIDE
    if name == "retrieval_profile":
        profile = str(value or "").strip().lower()
        allowed = {"recall20", "recall50", "coverage80", PRODUCTION_RETRIEVAL_PROFILE}
        return profile if profile in allowed else _INVALID_POLICY_OVERRIDE
    if name in {"top_k", "reranker_top_n"}:
        normalized = _coerce_policy_int(value, minimum=1, maximum=200)
        return normalized if normalized is not None else _INVALID_POLICY_OVERRIDE
    if name in {"score_threshold", "vector_weight", "keyword_weight", "mmr_lambda"}:
        normalized = _coerce_policy_float(value, minimum=0.0, maximum=1.0)
        return normalized if normalized is not None else _INVALID_POLICY_OVERRIDE
    if name in {
        "enable_reranker",
        "enable_weight_rerank",
        "enable_multi_query",
        "enable_query_alias_expansion",
    }:
        normalized = _coerce_policy_bool(value)
        return normalized if normalized is not None else _INVALID_POLICY_OVERRIDE
    if name == "reranker_provider":
        provider = str(value or "").strip().lower()
        return provider[:40] if provider else _INVALID_POLICY_OVERRIDE
    return _INVALID_POLICY_OVERRIDE


def _sanitize_policy_overrides(raw: Any) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for key, value in payload.items():
        name = str(key or "").strip()
        if not name or name not in _POLICY_ALLOWED_OVERRIDES:
            continue
        normalized = _normalize_policy_override(name, value)
        if normalized is not _INVALID_POLICY_OVERRIDE:
            out[name] = normalized

    return out


def normalize_intent_router_policy(policy: Any) -> dict[str, Any] | None:
    payload = policy if isinstance(policy, dict) else {}
    schema = str(payload.get("schema") or "").strip()
    if schema != _INTENT_ROUTER_POLICY_SCHEMA_V1:
        return None

    rules_raw = payload.get("rules")
    if not isinstance(rules_raw, list):
        return None

    rules: list[dict[str, Any]] = []
    for item in rules_raw[:20]:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("rule_id") or "").strip()[:40]
        if not rule_id:
            continue
        match_any = _normalize_match_terms(item.get("match_any"))
        match_all = _normalize_match_terms(item.get("match_all"))
        if not match_any and not match_all:
            continue
        overrides = _sanitize_policy_overrides(item.get("overrides"))
        if not overrides:
            continue
        rules.append(
            {
                "rule_id": rule_id,
                "match_any": match_any,
                "match_all": match_all,
                "overrides": overrides,
            }
        )

    if not rules:
        return None

    return {"schema": _INTENT_ROUTER_POLICY_SCHEMA_V1, "rules": rules}


def _query_matches_policy_rule(query: str, rule: dict[str, Any]) -> bool:
    q = str(query or "").casefold()
    if not q:
        return False

    match_any = [str(x).casefold() for x in (rule.get("match_any") or []) if str(x or "").strip()]
    match_all = [str(x).casefold() for x in (rule.get("match_all") or []) if str(x or "").strip()]

    any_ok = True if not match_any else any(term in q for term in match_any)
    all_ok = all(term in q for term in match_all)
    return bool(any_ok and all_ok)


def route_intent(query: str) -> dict[str, Any]:
    """Route lightweight no-retrieval intents before retrieval preset logic."""
    q = (query or "").strip()
    if q:
        if _matches_social_query(q, _GREETING_TERMS):
            return {"intent": "greeting", "reasons": ["social:greeting"], "skip_retrieval": True}
        if _matches_social_query(q, _THANKS_TERMS):
            return {"intent": "thanks", "reasons": ["social:thanks"], "skip_retrieval": True}
        if _matches_social_query(q, _SMALLTALK_TERMS):
            return {"intent": "smalltalk", "reasons": ["social:smalltalk"], "skip_retrieval": True}

    intent, reasons = classify_query_intent(query)
    return {"intent": intent, "reasons": reasons, "skip_retrieval": False}


def classify_query_intent(query: str) -> tuple[str, list[str]]:
    """
    Classify a query into one of:
    - log | api | howto | faq | general

    Returns: (intent, reason_codes)
    """
    q = (query or "").strip()
    if not q:
        return "general", ["empty"]

    reasons: list[str] = []

    # "log" is the most specific (should win over "api" when both match).
    if _INTENT_LOG_RE.search(q):
        reasons.append("log:pattern")
        if "\n" in q:
            reasons.append("log:multiline")
        return "log", _bounded_reason_codes(reasons)

    if _INTENT_API_RE.search(q):
        reasons.append("api:pattern")
        if "/" in q:
            reasons.append("api:path")
        return "api", _bounded_reason_codes(reasons)

    if _INTENT_HOWTO_RE.search(q):
        reasons.append("howto:pattern")
        return "howto", _bounded_reason_codes(reasons)

    # FAQ/definition-like queries tend to be short and phrased as "what is ...".
    if _INTENT_FAQ_RE.search(q):
        reasons.append("faq:pattern")
        return "faq", _bounded_reason_codes(reasons)

    # Heuristic: short ASCII-ish queries often benefit from keyword-mode retrieval.
    ascii_non_space = sum(1 for ch in q if ch.isascii() and not ch.isspace())
    if ascii_non_space > 0 and len(q) <= 40:
        reasons.append("general:short_ascii")
    return "general", _bounded_reason_codes(reasons)


def _apply_profile_contract(*, profile: str, top_k: int, score_threshold: float) -> tuple[int, float]:
    """
    Enforce the preset's top_k/threshold contract without relying on ChatRAGConfig validation.
    """
    p = (profile or "").strip().lower()
    if p == "recall20":
        return max(int(top_k or 0), 20), 0.0
    if p == "recall50":
        return max(int(top_k or 0), 50), 0.0
    if p == "coverage80":
        return max(int(top_k or 0), 80), 0.0
    if p == PRODUCTION_RETRIEVAL_PROFILE:
        return max(int(top_k or 0), 20), 0.0
    return int(top_k or 0), float(score_threshold or 0.0)


def _error_shape_overrides(
    *,
    mode: str,
    profile: str | None,
    enable_reranker: bool,
    enable_weight_rerank: bool,
    enable_multi_query: bool | None,
    enable_query_alias_expansion: bool | None,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if mode in {"auto", "hybrid", "keyword"}:
        overrides["retrieval_mode"] = "keyword"
    if not profile:
        overrides["retrieval_profile"] = "recall20"
    if bool(enable_reranker):
        overrides["enable_reranker"] = False
    if bool(enable_weight_rerank):
        overrides["enable_weight_rerank"] = False
    if enable_multi_query is None or bool(enable_multi_query):
        overrides["enable_multi_query"] = False
    if enable_query_alias_expansion is None or bool(enable_query_alias_expansion):
        overrides["enable_query_alias_expansion"] = False
    return overrides


def _deterministic_intent_overrides(
    *,
    intent: str,
    mode: str,
    profile: str | None,
    enable_reranker: bool,
    enable_weight_rerank: bool,
    enable_multi_query: bool | None,
    enable_query_alias_expansion: bool | None,
) -> dict[str, Any]:
    if intent in {"log", "api"}:
        return _error_shape_overrides(
            mode=mode,
            profile=profile,
            enable_reranker=enable_reranker,
            enable_weight_rerank=enable_weight_rerank,
            enable_multi_query=enable_multi_query,
            enable_query_alias_expansion=enable_query_alias_expansion,
        )
    if intent in {"faq", "howto"} and not profile:
        return {"retrieval_profile": "recall50"}
    return {}


def _apply_matching_policy_rules(
    overrides: dict[str, Any],
    *,
    query: str,
    policy: dict[str, Any] | None,
) -> list[str]:
    rule_ids: list[str] = []
    for rule in (policy or {}).get("rules", []):
        if not isinstance(rule, dict) or not _query_matches_policy_rule(query, rule):
            continue
        rule_ids.append(str(rule.get("rule_id") or "")[:40])
        for key, value in dict(rule.get("overrides") or {}).items():
            overrides[str(key)] = value
    return rule_ids


def _resolve_learned_router_model(
    model: dict[str, Any] | None,
    model_path: str | None,
) -> dict[str, Any] | None:
    normalized = normalize_intent_router_model(model)
    if normalized is None and str(model_path or "").strip():
        return load_intent_router_model(model_path)
    return normalized


def _apply_learned_router_hint(
    overrides: dict[str, Any],
    *,
    query: str,
    model: dict[str, Any] | None,
    model_path: str | None,
    confidence_min: float,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "enabled": False,
        "used": False,
        "rule_id": None,
        "confidence": 0.0,
        "confidence_gate": round(float(max(0.0, confidence_min)), 6),
        "applied_overrides": [],
        "skipped_reason": None,
    }
    learned_model = _resolve_learned_router_model(model, model_path)
    if learned_model is None:
        return meta

    meta["enabled"] = True
    hint = predict_learned_router_hint(query=query, model=learned_model)
    confidence = min(1.0, max(0.0, float(hint.get("confidence") or 0.0)))
    meta["confidence"] = round(confidence, 6)
    meta["rule_id"] = str(hint.get("rule_id") or "")[:40] or None
    hint_overrides = _sanitize_policy_overrides(hint.get("overrides"))
    gate = float(meta.get("confidence_gate") or 0.0)
    if confidence < gate:
        meta["skipped_reason"] = "confidence_below_gate"
        return meta
    if not hint_overrides:
        meta["skipped_reason"] = "no_overrides"
        return meta

    applied: list[str] = []
    for key, value in hint_overrides.items():
        if key in overrides:
            continue
        overrides[str(key)] = value
        applied.append(str(key))
    meta["applied_overrides"] = sorted(applied)
    meta["used"] = bool(applied)
    if not applied:
        meta["skipped_reason"] = "conflict_with_deterministic"
    return meta


def _enforce_profile_contract(
    overrides: dict[str, Any],
    *,
    profile: str | None,
    top_k: int,
    score_threshold: float,
) -> None:
    effective = str(overrides.get("retrieval_profile") or profile or "").strip().lower()
    supported = {"recall20", "recall50", "coverage80", PRODUCTION_RETRIEVAL_PROFILE}
    if effective not in supported:
        return
    contracted_top_k, contracted_threshold = _apply_profile_contract(
        profile=effective,
        top_k=int(overrides.get("top_k") or top_k),
        score_threshold=float(overrides.get("score_threshold") or score_threshold),
    )
    if int(contracted_top_k) != int(top_k):
        overrides["top_k"] = int(contracted_top_k)
    if float(contracted_threshold) != float(score_threshold):
        overrides["score_threshold"] = float(contracted_threshold)


def route_retrieval_preset(
    *,
    query: str,
    retrieval_mode: str,
    retrieval_profile: str | None,
    top_k: int,
    score_threshold: float,
    enable_reranker: bool,
    enable_weight_rerank: bool,
    enable_multi_query: bool | None,
    enable_query_alias_expansion: bool | None,
    intent_router_policy: dict[str, Any] | None = None,
    learned_router_model: dict[str, Any] | None = None,
    learned_router_model_path: str | None = None,
    learned_router_confidence_min: float = 0.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Return (overrides, meta) for intent-based retrieval routing.

    `overrides` is a dict with only the keys that should change.
    `meta` is PII-safe and bounded (no raw query).
    """
    intent, reasons = classify_query_intent(query)

    mode_norm = normalize_retrieval_mode(retrieval_mode or "hybrid")
    profile_norm = str(retrieval_profile or "").strip().lower() or None
    overrides = _deterministic_intent_overrides(
        intent=intent,
        mode=mode_norm,
        profile=profile_norm,
        enable_reranker=enable_reranker,
        enable_weight_rerank=enable_weight_rerank,
        enable_multi_query=enable_multi_query,
        enable_query_alias_expansion=enable_query_alias_expansion,
    )
    policy = normalize_intent_router_policy(intent_router_policy)
    policy_rule_ids = _apply_matching_policy_rules(overrides, query=query, policy=policy)
    learned_meta = _apply_learned_router_hint(
        overrides,
        query=query,
        model=learned_router_model,
        model_path=learned_router_model_path,
        confidence_min=learned_router_confidence_min,
    )
    _enforce_profile_contract(
        overrides,
        profile=profile_norm,
        top_k=top_k,
        score_threshold=score_threshold,
    )

    meta = {
        "enabled": True,
        "used": bool(overrides),
        "intent": intent,
        "reasons": reasons,
        "policy_used": bool(policy_rule_ids),
        "policy_rule_ids": policy_rule_ids,
        "learned_router": learned_meta,
        "overrides": sorted(overrides.keys()),
    }
    return overrides, meta


def _normalize_bucket_terms(raw: Any, *, allowed: set[str], max_items: int = 8) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        s = str(item or "").strip().lower()
        if not s or s not in allowed or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= max_items:
            break
    return out


def _normalize_adaptive_conditions(raw: Any) -> dict[str, Any]:
    when = raw if isinstance(raw, dict) else {}
    conditions: dict[str, Any] = {}
    intent_in = _normalize_bucket_terms(
        when.get("intent_in"),
        allowed={"log", "api", "howto", "faq", "general"},
        max_items=8,
    )
    mode_in = _normalize_bucket_terms(
        when.get("retrieval_mode_in"),
        allowed={"auto", "hybrid", "vector", "keyword", "mmr"},
        max_items=8,
    )
    len_bucket_in = _normalize_bucket_terms(
        when.get("query_len_bucket_in"),
        allowed={"short", "medium", "long"},
        max_items=8,
    )
    contains_any = _normalize_match_terms(when.get("contains_any"), max_items=10)
    has_quotes = _coerce_policy_bool(when.get("has_quotes"))
    has_digits = _coerce_policy_bool(when.get("has_digits"))
    if intent_in:
        conditions["intent_in"] = intent_in
    if mode_in:
        conditions["retrieval_mode_in"] = mode_in
    if len_bucket_in:
        conditions["query_len_bucket_in"] = len_bucket_in
    if contains_any:
        conditions["contains_any"] = contains_any
    if has_quotes is not None:
        conditions["has_quotes"] = bool(has_quotes)
    if has_digits is not None:
        conditions["has_digits"] = bool(has_digits)
    return conditions


def _normalize_adaptive_rule(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    rule_id = str(raw.get("rule_id") or "").strip()[:40]
    if not rule_id:
        return None
    conditions = _normalize_adaptive_conditions(raw.get("when"))
    if not conditions:
        return None
    overrides = _sanitize_policy_overrides(raw.get("overrides"))
    if not overrides:
        return None
    return {"rule_id": rule_id, "when": conditions, "overrides": overrides}


def normalize_adaptive_router_policy(policy: Any) -> dict[str, Any] | None:
    payload = policy if isinstance(policy, dict) else {}
    schema = str(payload.get("schema") or "").strip()
    if schema != _ADAPTIVE_ROUTER_POLICY_SCHEMA_V1:
        return None

    rules_raw = payload.get("rules")
    if not isinstance(rules_raw, list):
        return None

    rules: list[dict[str, Any]] = []
    for item in rules_raw[:30]:
        rule = _normalize_adaptive_rule(item)
        if rule is not None:
            rules.append(rule)

    if not rules:
        return None

    return {"schema": _ADAPTIVE_ROUTER_POLICY_SCHEMA_V1, "rules": rules}


def _query_len_bucket(query: str) -> str:
    q = str(query or "")
    n = len(q)
    if n <= 40:
        return "short"
    if n <= 120:
        return "medium"
    return "long"


def _adaptive_rule_matches(
    *,
    query: str,
    intent: str,
    retrieval_mode: str,
    len_bucket: str,
    rule: dict[str, Any],
) -> bool:
    when = rule.get("when")
    when = when if isinstance(when, dict) else {}

    intent_in = [str(v) for v in (when.get("intent_in") or []) if str(v).strip()]
    if intent_in and str(intent or "").strip().lower() not in {v.lower() for v in intent_in}:
        return False

    mode_in = [str(v) for v in (when.get("retrieval_mode_in") or []) if str(v).strip()]
    if mode_in and str(retrieval_mode or "").strip().lower() not in {v.lower() for v in mode_in}:
        return False

    bucket_in = [str(v) for v in (when.get("query_len_bucket_in") or []) if str(v).strip()]
    if bucket_in and str(len_bucket or "").strip().lower() not in {v.lower() for v in bucket_in}:
        return False

    contains_any = [str(v) for v in (when.get("contains_any") or []) if str(v).strip()]
    if contains_any:
        q_fold = str(query or "").casefold()
        if not any(str(token).casefold() in q_fold for token in contains_any):
            return False

    has_quotes = when.get("has_quotes")
    if has_quotes is not None:
        q = str(query or "")
        query_has_quotes = any(ch in q for ch in ("'", '"', "“", "”", "‘", "’", "`"))
        if bool(query_has_quotes) != bool(has_quotes):
            return False

    has_digits = when.get("has_digits")
    if has_digits is not None:
        query_has_digits = any(ch.isdigit() for ch in str(query or ""))
        if bool(query_has_digits) != bool(has_digits):
            return False

    return True


def route_adaptive_retrieval_overrides(
    *,
    query: str,
    retrieval_mode: str,
    intent_meta: dict[str, Any] | None = None,
    adaptive_router_policy: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Evaluate optional adaptive routing policy and return (overrides, meta).

    The policy uses only low-cardinality signals and never returns raw query text.
    """
    policy = normalize_adaptive_router_policy(adaptive_router_policy)
    if policy is None:
        return {}, {"enabled": False, "used": False}

    intent = str(((intent_meta or {}).get("intent")) or "").strip().lower()
    if not intent:
        intent, _ = classify_query_intent(query)
    mode_norm = normalize_retrieval_mode(retrieval_mode or "hybrid")
    len_bucket = _query_len_bucket(query)

    matched_rule_ids: list[str] = []
    overrides: dict[str, Any] = {}
    for rule in (policy.get("rules") or []):
        if not isinstance(rule, dict):
            continue
        if not _adaptive_rule_matches(
            query=query,
            intent=intent,
            retrieval_mode=mode_norm,
            len_bucket=len_bucket,
            rule=rule,
        ):
            continue
        rid = str(rule.get("rule_id") or "").strip()[:40]
        if rid:
            matched_rule_ids.append(rid)
        for key, value in dict(rule.get("overrides") or {}).items():
            overrides[str(key)] = value

    meta = {
        "enabled": True,
        "used": bool(overrides),
        "rule_count": int(len(list(policy.get("rules") or []))),
        "matched_rule_ids": matched_rule_ids[:8],
        "signals": {
            "intent": str(intent or "general"),
            "retrieval_mode": str(mode_norm or "hybrid"),
            "query_len_bucket": str(len_bucket),
            "has_quotes": bool(any(ch in str(query or "") for ch in ("'", '"', "“", "”", "‘", "’", "`"))),
            "has_digits": bool(any(ch.isdigit() for ch in str(query or ""))),
        },
        "overrides": sorted(overrides.keys()),
    }
    return overrides, meta


__all__ = [
    "_ADAPTIVE_ROUTER_POLICY_SCHEMA_V1",
    "_INTENT_ROUTER_POLICY_SCHEMA_V1",
    "classify_query_intent",
    "route_intent",
    "normalize_adaptive_router_policy",
    "normalize_intent_router_policy",
    "route_adaptive_retrieval_overrides",
    "route_retrieval_preset",
]
