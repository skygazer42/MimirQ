"""
Query intent router -> retrieval presets.

Design goals:
- Deterministic (no LLM calls).
- Low-cardinality + PII-safe metadata (no raw query text in outputs).
- Bounded (small objects; short reason codes).

This is used to automatically pick retrieval presets/profiles and toggles
based on the query "shape" (faq/howto/api/log) when enabled.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.rag.core.text import normalize_retrieval_mode

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


def _bounded_reason_codes(reasons: List[str], *, max_items: int = 6) -> List[str]:
    out: List[str] = []
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


def classify_query_intent(query: str) -> Tuple[str, List[str]]:
    """
    Classify a query into one of:
    - log | api | howto | faq | general

    Returns: (intent, reason_codes)
    """
    q = (query or "").strip()
    if not q:
        return "general", ["empty"]

    reasons: List[str] = []

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


def _apply_profile_contract(*, profile: str, top_k: int, score_threshold: float) -> Tuple[int, float]:
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
    return int(top_k or 0), float(score_threshold or 0.0)


def route_retrieval_preset(
    *,
    query: str,
    retrieval_mode: str,
    retrieval_profile: Optional[str],
    top_k: int,
    score_threshold: float,
    enable_reranker: bool,
    enable_weight_rerank: bool,
    enable_multi_query: Optional[bool],
    enable_query_alias_expansion: Optional[bool],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Return (overrides, meta) for intent-based retrieval routing.

    `overrides` is a dict with only the keys that should change.
    `meta` is PII-safe and bounded (no raw query).
    """
    intent, reasons = classify_query_intent(query)

    overrides: Dict[str, Any] = {}

    mode_norm = normalize_retrieval_mode(retrieval_mode or "hybrid")
    profile_norm = str(retrieval_profile or "").strip().lower() or None

    if intent in {"log", "api"}:
        # Prefer keyword retrieval for error/log/API-shaped queries.
        if mode_norm in {"auto", "hybrid", "keyword"}:
            overrides["retrieval_mode"] = "keyword"
        # Recall-first: we want exact-ish hits and avoid similarity threshold false negatives.
        if not profile_norm:
            overrides["retrieval_profile"] = "recall20"
        # Cost and stability: rerankers and weight rerank are not helpful for stack traces.
        if bool(enable_reranker):
            overrides["enable_reranker"] = False
        if bool(enable_weight_rerank):
            overrides["enable_weight_rerank"] = False
        # LLM expansions tend to hallucinate; disable when possible.
        if enable_multi_query is None or bool(enable_multi_query):
            overrides["enable_multi_query"] = False
        if enable_query_alias_expansion is None or bool(enable_query_alias_expansion):
            overrides["enable_query_alias_expansion"] = False

    elif intent in {"faq", "howto"}:
        # For recall in product/docs style queries, prefer recall50 by default.
        if not profile_norm:
            overrides["retrieval_profile"] = "recall50"

    # Apply top_k/threshold contract when we changed (or already had) a supported profile.
    profile_effective = str(overrides.get("retrieval_profile") or profile_norm or "").strip().lower()
    if profile_effective in {"recall20", "recall50", "coverage80"}:
        top_k2, thr2 = _apply_profile_contract(
            profile=profile_effective,
            top_k=int(overrides.get("top_k") or top_k),
            score_threshold=float(overrides.get("score_threshold") or score_threshold),
        )
        if int(top_k2) != int(top_k):
            overrides["top_k"] = int(top_k2)
        # Use <= to keep it stable even if caller already set 0.0.
        if float(thr2) != float(score_threshold):
            overrides["score_threshold"] = float(thr2)

    meta = {
        "enabled": True,
        "used": bool(overrides),
        "intent": intent,
        "reasons": reasons,
        "overrides": sorted(list(overrides.keys())),
    }
    return overrides, meta

