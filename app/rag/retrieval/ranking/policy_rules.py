"""Interpret plugin retrieval policies and apply pure candidate budget and compaction rules."""

from typing import Any

from app.types.document_metadata import metadata_text


def safe_positive_int(value: Any, *, default: int, minimum: int = 1, maximum: int = 200) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        out = int(default)
    return max(int(minimum), min(int(maximum), out))


def resolve_internal_candidate_top_k(
    requested_top_k: int,
    *,
    minimum: int = 20,
    multiplier: int = 4,
    maximum: int = 50,
) -> int:
    requested = safe_positive_int(requested_top_k, default=1)
    min_candidates = safe_positive_int(minimum, default=20)
    overfetch_multiplier = safe_positive_int(multiplier, default=4, maximum=20)
    max_candidates = safe_positive_int(maximum, default=50)
    max_candidates = max(requested, max_candidates)
    desired = max(requested, min_candidates, requested * overfetch_multiplier)
    return min(max_candidates, desired)


def compact_high_confidence_items(
    items: list[Any] | tuple[Any, ...],
    *,
    scores: list[float] | tuple[float, ...],
    top_k: int,
    enabled: bool = True,
    min_top_score: float = 0.8,
    relative_score_floor: float = 0.65,
    min_items: int = 1,
) -> tuple[Any, ...]:
    limited_items = tuple(items or ())[: safe_positive_int(top_k, default=1)]
    if not limited_items:
        return ()
    if not enabled:
        return limited_items

    normalized_scores: list[float] = []
    for index in range(len(limited_items)):
        try:
            normalized_scores.append(float(scores[index]))
        except (IndexError, TypeError, ValueError):
            normalized_scores.append(0.0)

    top_score = normalized_scores[0]
    safe_min_items = min(len(limited_items), safe_positive_int(min_items, default=1))
    if top_score < float(min_top_score or 0.0):
        return limited_items

    floor = max(0.0, min(1.0, float(relative_score_floor or 0.0)))
    score_floor = top_score * floor
    kept = [item for item, score in zip(limited_items, normalized_scores, strict=False) if score >= score_floor]
    if len(kept) < safe_min_items:
        kept = list(limited_items[:safe_min_items])
    return tuple(kept)


def query_terms_match(query: str, terms: tuple[str, ...] | list[str] | set[str] | str | None) -> bool:
    query_text = query.strip().casefold()
    if not query_text:
        return False
    raw_terms: tuple[str, ...] | list[str] | set[str]
    raw_terms = (terms,) if isinstance(terms, str) or terms is None else terms
    for raw in raw_terms:
        if raw is None:
            continue
        term = str(raw).strip().casefold()
        if term and term in query_text:
            return True
    return False


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _policy_string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple | set):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def _metadata_value(meta: dict[str, Any], key: str) -> Any:
    if key in meta:
        return meta.get(key)
    if "." not in key:
        return meta.get(key)
    cur: Any = meta
    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _metadata_terms(value: Any) -> tuple[str, ...]:
    raw_items = value if isinstance(value, list | tuple | set) else [value]
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        if raw is None:
            continue
        text = str(raw).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def _append_unique_text(out: list[str], seen: set[str], value: Any) -> None:
    if value is None:
        return
    text = str(value).strip()
    if not text or text in seen:
        return
    seen.add(text)
    out.append(text)


def _append_policy_mapping_terms(
    out: list[str],
    seen: set[str],
    *,
    meta: dict[str, Any],
    mappings: tuple[dict[str, Any], ...],
) -> None:
    for mapping in mappings:
        field = mapping["metadata"]
        actual_values = {_normalize_policy_match_text(value) for value in _metadata_terms(_metadata_value(meta, field))}
        if not actual_values or not actual_values.intersection(mapping["values"]):
            continue
        for term in mapping["terms"]:
            _append_unique_text(out, seen, term)


def _iter_policy_query_terms(
    metadata_layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    fields: tuple[str, ...],
    mappings: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for layer in metadata_layers or ():
        meta = _as_dict(layer)
        if not meta:
            continue
        for field in fields:
            for term in _metadata_terms(_metadata_value(meta, field)):
                _append_unique_text(out, seen, term)
        _append_policy_mapping_terms(out, seen, meta=meta, mappings=mappings)
    return tuple(out)


def retrieval_policy_query_terms(
    retrieval_policy: dict[str, Any] | None,
    *,
    metadata_layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return ()
    fields = _policy_string_list(retrieval_policy.get("query_expansion_fields"))
    mappings = _policy_value_query_term_mappings(retrieval_policy.get("query_expansion_values"))
    return _iter_policy_query_terms(metadata_layers, fields=fields, mappings=mappings)


def retrieval_policy_service_anchor_noise_terms(retrieval_policy: dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return ()
    return _policy_string_list(retrieval_policy.get("service_anchor_noise_terms"))


def retrieval_policy_service_anchor_priority_terms(retrieval_policy: dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return ()
    return _policy_string_list(retrieval_policy.get("service_anchor_priority_terms"))


def retrieval_policy_mixed_intent_leading_noise_terms(retrieval_policy: dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return ()
    return _policy_string_list(retrieval_policy.get("mixed_intent_leading_noise_terms"))


def retrieval_policy_mixed_intent_subject_terms(retrieval_policy: dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for raw_term in (
        *(_policy_string_list(retrieval_policy.get("mixed_intent_subject_terms"))),
        *(_policy_string_list(retrieval_policy.get("service_anchor_noise_terms"))),
        *(_policy_string_list(retrieval_policy.get("question_intent_terms"))),
    ):
        term = raw_term.strip()
        normalized = _normalize_policy_match_text(term)
        if not term or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(term)
    return tuple(out)


def retrieval_policy_service_anchor_query_rewrite_terms(
    retrieval_policy: dict[str, Any] | None,
    *,
    query: str,
) -> tuple[str, ...]:
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return ()
    query_text = _normalize_policy_match_text(query)
    if not query_text:
        return ()
    raw_rules = retrieval_policy.get("service_anchor_query_rewrites")
    if not isinstance(raw_rules, list):
        return ()

    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_rules:
        rewrite_terms = _policy_rule_rewrite_terms(raw)
        if not rewrite_terms or not _policy_rule_matches_query(raw, query_text):
            continue
        for term in rewrite_terms:
            text = term.strip()
            normalized = _normalize_policy_match_text(text)
            if not text or normalized in seen:
                continue
            seen.add(normalized)
            out.append(text)
    return tuple(out)


def _policy_rule_rewrite_terms(raw_rule: Any) -> tuple[str, ...]:
    rule = _as_dict(raw_rule)
    return _metadata_terms(rule.get("terms") or rule.get("rewrite_terms"))


def _policy_rule_matches_query(raw_rule: Any, query_text: str) -> bool:
    rule = _as_dict(raw_rule)
    when_terms = _metadata_terms(rule.get("when_terms") or rule.get("when"))
    normalized_when = tuple(term for term in (_normalize_policy_match_text(term) for term in when_terms) if term)
    if not normalized_when:
        return False
    match_mode = str(rule.get("match") or "all").strip().lower()
    return (
        any(term in query_text for term in normalized_when)
        if match_mode == "any"
        else all(term in query_text for term in normalized_when)
    )


def _policy_value_query_term_mappings(raw_mappings: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw_mappings, list):
        return ()
    out: list[dict[str, Any]] = []
    for raw in raw_mappings:
        mapping = _as_dict(raw)
        field = metadata_text(mapping, "metadata")
        if not field:
            continue
        raw_values = mapping.get("values") if "values" in mapping else mapping.get("value")
        values = frozenset(
            normalized for value in _metadata_terms(raw_values) if (normalized := _normalize_policy_match_text(value))
        )
        terms = _metadata_terms(mapping.get("terms"))
        if values and terms:
            out.append({"metadata": field, "values": values, "terms": terms})
    return tuple(out)


def _normalize_policy_match_text(value: str) -> str:
    text = value.strip().casefold()
    return "".join(char for char in text if char.isalnum())


def _policy_value_fuzzy_overlaps_query(query_text: str, value_text: str) -> bool:
    if not query_text or not value_text:
        return False
    if value_text in query_text or query_text in value_text:
        return True
    shortest = min(len(query_text), len(value_text))
    if shortest < 4:
        return False
    required = max(4, (72 * shortest + 99) // 100)
    shorter, longer = (query_text, value_text) if len(query_text) <= len(value_text) else (value_text, query_text)
    return any(shorter[start : start + required] in longer for start in range(len(shorter) - required + 1))


def _policy_value_matches_query(query: str, value: str, *, match_mode: str) -> bool:
    query_text = _normalize_policy_match_text(query)
    value_text = _normalize_policy_match_text(value)
    if not query_text or not value_text:
        return False
    if match_mode == "exact":
        return query_text == value_text
    if match_mode == "fuzzy_overlap":
        return _policy_value_fuzzy_overlaps_query(query_text, value_text)
    return value_text in query_text or query_text in value_text


def _policy_weight(value: Any, *, default: float = 1.0, maximum: float = 10.0) -> float:
    try:
        weight = float(value if value is not None else default)
    except (TypeError, ValueError):
        weight = float(default)
    return max(0.0, min(float(maximum), weight))


def retrieval_policy_boost_score(
    retrieval_policy: dict[str, Any] | None,
    *,
    metadata_layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    query: str,
    base_bonus: float = 0.04,
    max_bonus: float = 0.24,
) -> float:
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return 0.0
    raw_boosts = retrieval_policy.get("boost_fields")
    if not isinstance(raw_boosts, list) or not raw_boosts:
        return 0.0

    score = 0.0
    for raw in raw_boosts:
        score += _policy_boost_bonus(raw, metadata_layers=metadata_layers, query=query, base_bonus=base_bonus)
    return min(float(max_bonus), score)


def _policy_boost_bonus(
    raw_boost: Any,
    *,
    metadata_layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    query: str,
    base_bonus: float,
) -> float:
    boost = _as_dict(raw_boost)
    field = metadata_text(boost, "metadata")
    if not field:
        return 0.0
    match_mode = _policy_boost_match_mode(boost.get("match"))
    if not _policy_metadata_matches_query(metadata_layers, field=field, query=query, match_mode=match_mode):
        return 0.0
    weight = _policy_weight(boost.get("weight"), default=1.0)
    return float(base_bonus) * weight


def _policy_boost_match_mode(value: Any) -> str:
    match_mode = str(value or "contains").strip()
    return match_mode if match_mode in {"exact", "contains", "overlap", "fuzzy_overlap"} else "contains"


def _policy_metadata_matches_query(
    metadata_layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    field: str,
    query: str,
    match_mode: str,
) -> bool:
    for layer in metadata_layers or ():
        meta = _as_dict(layer)
        for term in _metadata_terms(_metadata_value(meta, field)):
            if _policy_value_matches_query(query, term, match_mode=match_mode):
                return True
    return False


def _policy_anchor_aliases(raw_aliases: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw_aliases, dict):
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for raw_canonical, raw_values in raw_aliases.items():
        canonical = _normalize_policy_match_text(raw_canonical)
        if not canonical:
            continue
        values = _metadata_terms(raw_values)
        terms = [canonical, *[_normalize_policy_match_text(value) for value in values]]
        clean_terms = tuple(dict.fromkeys(term for term in terms if term))
        if clean_terms:
            out[canonical] = clean_terms
    return out


def _policy_query_anchor_keys(query: str, aliases: dict[str, tuple[str, ...]]) -> set[str]:
    query_text = _normalize_policy_match_text(query)
    if not query_text:
        return set()
    return {
        canonical
        for canonical, terms in aliases.items()
        if any(len(term) >= 2 and (term in query_text or query_text in term) for term in terms)
    }


def _policy_record_anchor_keys(
    metadata_layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    field: str,
    aliases: dict[str, tuple[str, ...]],
) -> set[str]:
    out: set[str] = set()
    for layer in metadata_layers or ():
        meta = _as_dict(layer)
        for value in _metadata_terms(_metadata_value(meta, field)):
            term = _normalize_policy_match_text(value)
            if not term:
                continue
            matched = False
            for canonical, alias_terms in aliases.items():
                if any(alias == term or (len(alias) >= 2 and alias in term) for alias in alias_terms):
                    out.add(canonical)
                    matched = True
            if not matched:
                out.add(term)
    return out


def retrieval_policy_anchor_mismatch_penalty(
    retrieval_policy: dict[str, Any] | None,
    *,
    metadata_layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    query: str,
    base_penalty: float = 0.08,
    max_penalty: float = 0.24,
) -> float:
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return 0.0
    raw_anchors = retrieval_policy.get("anchor_fields")
    if not isinstance(raw_anchors, list) or not raw_anchors:
        return 0.0

    penalty = 0.0
    for raw in raw_anchors:
        anchor = _as_dict(raw)
        field = metadata_text(anchor, "metadata")
        if not field:
            continue
        aliases = _policy_anchor_aliases(anchor.get("aliases"))
        query_keys = _policy_query_anchor_keys(query, aliases)
        if not query_keys:
            continue
        record_keys = _policy_record_anchor_keys(metadata_layers, field=field, aliases=aliases)
        if record_keys and not record_keys.intersection(query_keys):
            penalty += float(base_penalty) * _policy_weight(anchor.get("weight"), default=1.0)
    return min(float(max_penalty), penalty)


def retrieval_policy_value_intent_mismatch_penalty(
    retrieval_policy: dict[str, Any] | None,
    *,
    metadata_layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    query: str,
    base_penalty: float = 0.08,
    max_penalty: float = 0.24,
) -> float:
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return 0.0
    query_text = _normalize_policy_match_text(query)
    if not query_text:
        return 0.0

    query_values_by_field: dict[str, set[str]] = {}
    for mapping in _policy_value_query_term_mappings(retrieval_policy.get("query_expansion_values")):
        if any(
            _policy_value_fuzzy_overlaps_query(query_text, _normalize_policy_match_text(term))
            for term in mapping["terms"]
        ):
            query_values_by_field.setdefault(mapping["metadata"], set()).update(mapping["values"])
    if not query_values_by_field:
        return 0.0

    penalty = 0.0
    for field, query_values in query_values_by_field.items():
        actual_values: set[str] = set()
        for layer in metadata_layers or ():
            meta = _as_dict(layer)
            actual_values.update(
                normalized
                for value in _metadata_terms(_metadata_value(meta, field))
                if (normalized := _normalize_policy_match_text(value))
            )
        if actual_values and not actual_values.intersection(query_values):
            penalty += float(base_penalty)
    return min(float(max_penalty), penalty)


def retrieval_policy_rerank_feature_score(
    retrieval_policy: dict[str, Any] | None,
    *,
    metadata_layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    query: str,
    base_bonus: float = 0.06,
    max_bonus: float = 0.18,
) -> float:
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return 0.0
    fields = _policy_string_list(retrieval_policy.get("rerank_features"))
    if not fields:
        return 0.0

    query_text = _normalize_policy_match_text(query)
    if not query_text:
        return 0.0

    matches = 0
    for layer in metadata_layers or ():
        meta = _as_dict(layer)
        if not meta:
            continue
        for field in fields:
            for term in _metadata_terms(_metadata_value(meta, field)):
                if _policy_value_matches_query(query_text, term, match_mode="fuzzy_overlap"):
                    matches += 1
                    break
    return min(float(max_bonus), float(base_bonus) * matches)


def retrieval_policy_fallback_multiplier(
    retrieval_policy: dict[str, Any] | None,
    *,
    default: int = 1,
    maximum: int = 10,
) -> int:
    safe_default = safe_positive_int(default, default=1, maximum=maximum)
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return safe_default
    fallback = _as_dict(retrieval_policy.get("fallback"))
    if fallback.get("enabled") is not True:
        return safe_default
    return safe_positive_int(
        fallback.get("expand_top_k_multiplier"),
        default=safe_default,
        minimum=1,
        maximum=maximum,
    )


def _policy_float(value: Any, *, default: float, minimum: float = 0.0, maximum: float = 2.0) -> float:
    try:
        out = float(value if value is not None else default)
    except (TypeError, ValueError):
        out = float(default)
    return max(float(minimum), min(float(maximum), out))


def retrieval_policy_response_compaction(retrieval_policy: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return {"enabled": False}
    raw = _as_dict(retrieval_policy.get("response_compaction"))
    if raw.get("enabled") is not True:
        return {"enabled": False}
    return {
        "enabled": True,
        "min_top_score": _policy_float(raw.get("min_top_score"), default=0.8, minimum=0.0, maximum=2.0),
        "relative_score_floor": _policy_float(
            raw.get("relative_score_floor"),
            default=0.65,
            minimum=0.0,
            maximum=1.0,
        ),
        "min_records": safe_positive_int(raw.get("min_records"), default=1, minimum=1, maximum=20),
    }


__all__ = [
    "compact_high_confidence_items",
    "query_terms_match",
    "resolve_internal_candidate_top_k",
    "retrieval_policy_anchor_mismatch_penalty",
    "retrieval_policy_boost_score",
    "retrieval_policy_fallback_multiplier",
    "retrieval_policy_mixed_intent_leading_noise_terms",
    "retrieval_policy_mixed_intent_subject_terms",
    "retrieval_policy_query_terms",
    "retrieval_policy_rerank_feature_score",
    "retrieval_policy_response_compaction",
    "retrieval_policy_service_anchor_noise_terms",
    "retrieval_policy_service_anchor_priority_terms",
    "retrieval_policy_service_anchor_query_rewrite_terms",
    "retrieval_policy_value_intent_mismatch_penalty",
    "safe_positive_int",
]
