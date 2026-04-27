from __future__ import annotations

import re
from typing import Any

from app.rag.policy.intent_router import route_intent
from app.rag.utils.entity_matcher import extract_partition_keys

ROUTER_LAYERS_SCHEMA_V1 = "mimirq.router_layers.v1"

_COMPARE_RE = re.compile(
    r"(?i)\b(compare|vs\.?|versus|difference|different|diff|contrast)\b|"
    r"对比|比较|差异|区别|相比|vs"
)
_MULTI_CLAUSE_RE = re.compile(
    r"(?i)\b(and|then|also|plus)\b|"
    r"以及|并且|同时|然后|另外|此外|；|;"
)


def _bounded_reason_codes(items: list[str], *, max_items: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        text = str(raw or "").strip().lower()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text[:40])
        if len(out) >= max_items:
            break
    return out


def _normalize_partition_keys(raw: Any, *, max_items: int = 8) -> list[str]:
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, (list, tuple, set)):
        values = list(raw)
    else:
        values = []

    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max_items:
            break
    return out


def classify_composite_query(query: str) -> tuple[str, list[str]]:
    q = str(query or "").strip()
    if not q:
        return "single", ["empty_query"]
    if _COMPARE_RE.search(q):
        return "compare", ["compare_pattern"]
    if _MULTI_CLAUSE_RE.search(q):
        return "multi_clause", ["multi_clause_pattern"]
    return "single", ["single_clause"]


def build_router_layers(
    *,
    query: str,
    entity_key: str | None = None,
    partition_keys: list[str] | None = None,
    entity_candidates: list[str] | None = None,
    intent_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    explicit_partition_keys = _normalize_partition_keys(partition_keys)
    explicit_entity_key = str(entity_key or "").strip()

    entity_reason_codes: list[str] = []
    entity_keys: list[str] = []
    if explicit_partition_keys:
        entity_keys = explicit_partition_keys
        entity_reason_codes.append("explicit_partition_keys")
    elif explicit_entity_key:
        entity_keys = [explicit_entity_key]
        entity_reason_codes.append("explicit_entity_key")
    elif entity_candidates:
        entity_keys = extract_partition_keys(query, entity_candidates)
        if entity_keys:
            entity_reason_codes.append("matched_candidates")

    entity_layer = {
        "decision": "partition_keys" if entity_keys else "none",
        "used": bool(entity_keys),
        "partition_keys": list(entity_keys),
        "reason_codes": _bounded_reason_codes(entity_reason_codes),
    }

    intent_payload = dict(intent_meta or {})
    if not str(intent_payload.get("intent") or "").strip():
        intent_payload = route_intent(query)
    intent_layer = {
        "decision": str(intent_payload.get("intent") or "general"),
        "used": bool(intent_payload.get("skip_retrieval") or intent_payload.get("used") or False),
        "reason_codes": _bounded_reason_codes(list(intent_payload.get("reasons") or [])),
        "skip_retrieval": bool(intent_payload.get("skip_retrieval") or False),
    }

    composite_decision, composite_reasons = classify_composite_query(query)
    composite_layer = {
        "decision": composite_decision,
        "used": bool(composite_decision != "single"),
        "reason_codes": _bounded_reason_codes(composite_reasons),
    }

    return {
        "schema": ROUTER_LAYERS_SCHEMA_V1,
        "entity": entity_layer,
        "intent": intent_layer,
        "composite": composite_layer,
    }


__all__ = ["ROUTER_LAYERS_SCHEMA_V1", "build_router_layers", "classify_composite_query"]
