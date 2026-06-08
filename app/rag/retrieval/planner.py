from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class DatasetRouteHint:
    terms: tuple[str, ...] = ()
    dataset_ids: tuple[UUID, ...] = ()
    mode: str = "prepend"


@dataclass(frozen=True)
class DatasetScopePlan:
    dataset_ids: tuple[UUID, ...]
    primary_dataset_ids: tuple[UUID, ...]
    expansion_dataset_ids: tuple[UUID, ...]
    base_dataset_ids: tuple[UUID, ...]
    matched_dataset_ids: tuple[UUID, ...]
    matched_terms: tuple[str, ...]
    strict_scope: bool
    route_count: int
    matched_route_count: int
    included_hint_dataset_count: int


def safe_positive_int(value: Any, *, default: int, minimum: int = 1, maximum: int = 200) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        out = int(default)
    return max(int(minimum), min(int(maximum), int(out)))


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
    query_text = str(query or "").strip().casefold()
    if not query_text:
        return False
    raw_terms: tuple[str, ...] | list[str] | set[str]
    raw_terms = (terms,) if isinstance(terms, str) or terms is None else terms
    for raw in raw_terms:
        term = str(raw or "").strip().casefold()
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
        text = str(item or "").strip()
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
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def retrieval_policy_query_terms(
    retrieval_policy: dict[str, Any] | None,
    *,
    metadata_layers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return ()
    fields = _policy_string_list(retrieval_policy.get("query_expansion_fields"))
    out: list[str] = []
    seen: set[str] = set()
    for layer in metadata_layers or ():
        meta = _as_dict(layer)
        if not meta:
            continue
        for field in fields:
            for term in _metadata_terms(_metadata_value(meta, field)):
                if term in seen:
                    continue
                seen.add(term)
                out.append(term)
        for mapping in _policy_value_query_term_mappings(retrieval_policy.get("query_expansion_values")):
            field = mapping["metadata"]
            actual_values = {_normalize_policy_match_text(value) for value in _metadata_terms(_metadata_value(meta, field))}
            if not actual_values or not actual_values.intersection(mapping["values"]):
                continue
            for term in mapping["terms"]:
                if term in seen:
                    continue
                seen.add(term)
                out.append(term)
    return tuple(out)


def _policy_value_query_term_mappings(raw_mappings: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw_mappings, list):
        return ()
    out: list[dict[str, Any]] = []
    for raw in raw_mappings:
        mapping = _as_dict(raw)
        field = str(mapping.get("metadata") or "").strip()
        if not field:
            continue
        raw_values = mapping.get("values") if "values" in mapping else mapping.get("value")
        values = frozenset(
            normalized
            for value in _metadata_terms(raw_values)
            if (normalized := _normalize_policy_match_text(value))
        )
        terms = _metadata_terms(mapping.get("terms"))
        if values and terms:
            out.append({"metadata": field, "values": values, "terms": terms})
    return tuple(out)


def _normalize_policy_match_text(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return "".join(char for char in text if char.isalnum())


def _longest_common_substring_length(left: str, right: str) -> int:
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    best = 0
    for left_char in left:
        current = [0] * (len(right) + 1)
        for index, right_char in enumerate(right, start=1):
            if left_char != right_char:
                continue
            current[index] = previous[index - 1] + 1
            best = max(best, current[index])
        previous = current
    return best


def _policy_value_fuzzy_overlaps_query(query_text: str, value_text: str) -> bool:
    if not query_text or not value_text:
        return False
    if value_text in query_text or query_text in value_text:
        return True
    shortest = min(len(query_text), len(value_text))
    if shortest < 4:
        return False
    overlap = _longest_common_substring_length(query_text, value_text)
    return overlap >= 4 and (overlap / shortest) >= 0.72


def _policy_value_matches_query(query: str, value: str, *, match_mode: str) -> bool:
    query_text = _normalize_policy_match_text(query)
    value_text = _normalize_policy_match_text(value)
    if not query_text or not value_text:
        return False
    if match_mode == "exact":
        return query_text == value_text
    if match_mode == "fuzzy_overlap":
        return _policy_value_fuzzy_overlaps_query(query_text, value_text)
    if match_mode == "overlap":
        return value_text in query_text or query_text in value_text
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
        boost = _as_dict(raw)
        field = str(boost.get("metadata") or "").strip()
        if not field:
            continue
        weight = _policy_weight(boost.get("weight"), default=1.0)
        match_mode = str(boost.get("match") or "contains").strip()
        if match_mode not in {"exact", "contains", "overlap", "fuzzy_overlap"}:
            match_mode = "contains"
        matched = False
        for layer in metadata_layers or ():
            meta = _as_dict(layer)
            for term in _metadata_terms(_metadata_value(meta, field)):
                if _policy_value_matches_query(query, term, match_mode=match_mode):
                    matched = True
                    break
            if matched:
                break
        if matched:
            score += float(base_bonus) * weight
    return min(float(max_bonus), score)


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
        field = str(anchor.get("metadata") or "").strip()
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


def _policy_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        out = float(value if value is not None else default)
    except (TypeError, ValueError):
        out = float(default)
    return max(float(minimum), min(float(maximum), float(out)))


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


def _record_meta(record: dict[str, Any]) -> dict[str, Any]:
    meta = record.get("metadata") if isinstance(record, dict) else {}
    return meta if isinstance(meta, dict) else {}


def _record_value(record: dict[str, Any], key: str) -> Any:
    if isinstance(record, dict) and key in record:
        return record.get(key)
    return _record_meta(record).get(key)


def _record_text(record: dict[str, Any], key: str) -> str:
    return str(_record_value(record, key) or "").strip()


def _record_float(record: dict[str, Any], key: str) -> float:
    try:
        return float(_record_value(record, key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _record_bool(record: dict[str, Any], key: str) -> bool:
    value = _record_value(record, key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _record_has_kg_path(record: dict[str, Any]) -> bool:
    path = _record_value(record, "kg_path")
    if isinstance(path, list | tuple) and path:
        return True
    provenance = _record_value(record, "kg_path_provenance")
    return isinstance(provenance, dict) and bool(provenance)


def _record_role(record: dict[str, Any]) -> str:
    return _record_text(record, "retrieval_role").lower() or "main"


def _is_kg_hint_record(record: dict[str, Any]) -> bool:
    role = _record_role(record)
    if role in {"kg", "kgq"}:
        return True
    return any(
        (
            _record_float(record, "kg_pagerank") > 0,
            _record_float(record, "kg_shared_events") > 0,
            _record_float(record, "kg_path_length") > 0,
            _record_bool(record, "kg_evidence_anchored"),
            _record_has_kg_path(record),
        )
    )


def _matches_expected_record_scope(
    record: dict[str, Any],
    *,
    expected_chunk_ids: set[str],
    expected_document_ids: set[str],
    expected_metadata: dict[str, Any],
    metadata_view_keys: tuple[str, ...],
) -> bool:
    chunk_id = _record_text(record, "chunk_id")
    document_id = _record_text(record, "document_id")
    if expected_chunk_ids and chunk_id in expected_chunk_ids:
        return True
    if expected_document_ids and document_id in expected_document_ids:
        return True
    return bool(expected_metadata and _record_metadata_matches(record, expected_metadata, metadata_view_keys))


def _record_metadata_layers(record: dict[str, Any], metadata_view_keys: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    meta = _record_meta(record)
    layers = [meta]
    for key in metadata_view_keys:
        nested = meta.get(key)
        if isinstance(nested, dict):
            layers.append(nested)
    return tuple(layers)


def _metadata_expected_value_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, list | tuple | set):
        return actual in expected
    return actual == expected


def _record_metadata_matches(
    record: dict[str, Any],
    expected_metadata: dict[str, Any],
    metadata_view_keys: tuple[str, ...],
) -> bool:
    if not expected_metadata:
        return False
    for layer in _record_metadata_layers(record, metadata_view_keys):
        if all(_metadata_expected_value_matches(layer.get(key), expected) for key, expected in expected_metadata.items()):
            return True
    return False


def summarize_kg_hint_diagnostics(
    records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    expected_chunk_ids: list[str] | tuple[str, ...] | set[str] = (),
    expected_document_ids: list[str] | tuple[str, ...] | set[str] = (),
    expected_metadata: dict[str, Any] | None = None,
    metadata_view_keys: list[str] | tuple[str, ...] | set[str] = (),
) -> dict[str, Any]:
    """Summarize optional KG retrieval hints without changing ranking behavior."""

    expected_chunks = {str(item or "").strip() for item in expected_chunk_ids or () if str(item or "").strip()}
    expected_documents = {
        str(item or "").strip() for item in expected_document_ids or () if str(item or "").strip()
    }
    expected_meta = dict(expected_metadata) if isinstance(expected_metadata, dict) else {}
    view_keys = tuple(str(item or "").strip() for item in metadata_view_keys or () if str(item or "").strip())
    noise_evaluated = bool(expected_chunks or expected_documents or expected_meta)

    role_counts: dict[str, int] = {}
    kg_candidate_count = 0
    query_expansion_count = 0
    entity_anchor_count = 0
    relation_neighbor_count = 0
    boosted_count = 0
    noise_count = 0

    for record in records or ():
        if not isinstance(record, dict):
            continue
        role = _record_role(record)
        role_counts[role] = role_counts.get(role, 0) + 1

        if not _is_kg_hint_record(record):
            continue
        kg_candidate_count += 1

        if role == "kgq":
            query_expansion_count += 1
        if _record_bool(record, "kg_evidence_anchored"):
            entity_anchor_count += 1
        if _record_float(record, "kg_shared_events") > 0 or _record_float(record, "kg_path_length") > 0:
            relation_neighbor_count += 1
        if _record_float(record, "kg_pagerank") > 0 or _record_float(record, "kg_shared_events") > 0:
            boosted_count += 1
        if noise_evaluated and not _matches_expected_record_scope(
            record,
            expected_chunk_ids=expected_chunks,
            expected_document_ids=expected_documents,
            expected_metadata=expected_meta,
            metadata_view_keys=view_keys,
        ):
            noise_count += 1

    return {
        "schema": "mimirq.kg_hint_diagnostics.v1",
        "record_count": sum(role_counts.values()),
        "retrieval_role_counts": role_counts,
        "kg_candidate_count": kg_candidate_count,
        "kg_query_expansion_record_count": query_expansion_count,
        "kg_entity_anchor_record_count": entity_anchor_count,
        "kg_relation_neighbor_record_count": relation_neighbor_count,
        "kg_boosted_record_count": boosted_count,
        "kg_noise_evaluated": noise_evaluated,
        "kg_noise_record_count": noise_count if noise_evaluated else 0,
        "kg_noise_rate": (noise_count / kg_candidate_count) if noise_evaluated and kg_candidate_count else None,
    }


def normalize_route_mode(value: Any) -> str:
    mode = str(value or "prepend").strip().lower()
    if mode in {"replace", "override"}:
        return "replace"
    if mode in {"append", "extend"}:
        return "append"
    return "prepend"


def _dedupe_dataset_ids(dataset_ids: list[UUID] | tuple[UUID, ...]) -> tuple[UUID, ...]:
    seen: set[UUID] = set()
    out: list[UUID] = []
    for dataset_id in dataset_ids:
        if dataset_id in seen:
            continue
        seen.add(dataset_id)
        out.append(dataset_id)
    return tuple(out)


def _hint_dataset_ids(route_hints: list[DatasetRouteHint] | tuple[DatasetRouteHint, ...]) -> tuple[UUID, ...]:
    out: list[UUID] = []
    for route in route_hints:
        out.extend(route.dataset_ids)
    return _dedupe_dataset_ids(out)


def _without_dataset_ids(dataset_ids: tuple[UUID, ...], excluded: tuple[UUID, ...]) -> tuple[UUID, ...]:
    excluded_set = set(excluded)
    return tuple(dataset_id for dataset_id in dataset_ids if dataset_id not in excluded_set)


def _matched_terms(route: DatasetRouteHint, query: str) -> tuple[str, ...]:
    query_text = str(query or "").strip().casefold()
    if not query_text:
        return ()
    out: list[str] = []
    for raw in route.terms:
        term = str(raw or "").strip()
        if term and term.casefold() in query_text:
            out.append(term)
    return tuple(out)


def plan_dataset_scope(
    *,
    base_dataset_ids: list[UUID] | tuple[UUID, ...],
    route_hints: list[DatasetRouteHint] | tuple[DatasetRouteHint, ...] = (),
    query: str,
    strict_routes: bool = False,
    include_unmatched_hint_datasets: bool = True,
    matched_replace_routes_as_primary_scope: bool = False,
) -> DatasetScopePlan:
    base_ids = _dedupe_dataset_ids(tuple(base_dataset_ids or ()))
    hints = tuple(route_hints or ())
    current: tuple[UUID, ...] = base_ids
    matched_dataset_ids: list[UUID] = []
    matched_replace_dataset_ids: list[UUID] = []
    matched_terms: list[str] = []
    matched_route_count = 0
    strict_scope = False

    hint_ids = _hint_dataset_ids(hints)
    if not strict_routes and include_unmatched_hint_datasets:
        current = _dedupe_dataset_ids([*current, *hint_ids])

    for route in hints:
        terms = _matched_terms(route, query)
        if not terms:
            continue
        route_dataset_ids = _dedupe_dataset_ids(route.dataset_ids)
        if not route_dataset_ids:
            continue
        matched_route_count += 1
        matched_dataset_ids.extend(route_dataset_ids)
        matched_terms.extend(terms)
        mode = normalize_route_mode(route.mode)
        if mode == "replace":
            matched_replace_dataset_ids.extend(route_dataset_ids)
        if strict_routes and mode == "replace":
            current = route_dataset_ids
            strict_scope = True
        elif mode == "append":
            current = _dedupe_dataset_ids([*current, *route_dataset_ids])
        else:
            current = _dedupe_dataset_ids([*route_dataset_ids, *current])

    matched_ids = _dedupe_dataset_ids(matched_dataset_ids)
    matched_replace_ids = _dedupe_dataset_ids(matched_replace_dataset_ids)
    if strict_scope:
        primary_ids = current
        expansion_ids: tuple[UUID, ...] = ()
    elif matched_replace_routes_as_primary_scope and matched_replace_ids:
        primary_ids = matched_replace_ids
        expansion_ids = _without_dataset_ids(current, primary_ids)
    elif matched_ids:
        primary_ids = current
        expansion_ids = ()
    elif hint_ids and not strict_routes and include_unmatched_hint_datasets:
        primary_ids = current
        expansion_ids = ()
    elif base_ids:
        primary_ids = base_ids
        expansion_ids = _without_dataset_ids(current, primary_ids)
    else:
        primary_ids = current
        expansion_ids = ()

    return DatasetScopePlan(
        dataset_ids=current,
        primary_dataset_ids=primary_ids,
        expansion_dataset_ids=expansion_ids,
        base_dataset_ids=base_ids,
        matched_dataset_ids=matched_ids,
        matched_terms=tuple(dict.fromkeys(matched_terms)),
        strict_scope=strict_scope,
        route_count=len(hints),
        matched_route_count=matched_route_count,
        included_hint_dataset_count=len(hint_ids),
    )


__all__ = [
    "DatasetRouteHint",
    "DatasetScopePlan",
    "compact_high_confidence_items",
    "normalize_route_mode",
    "plan_dataset_scope",
    "query_terms_match",
    "retrieval_policy_anchor_mismatch_penalty",
    "retrieval_policy_boost_score",
    "retrieval_policy_fallback_multiplier",
    "retrieval_policy_query_terms",
    "retrieval_policy_rerank_feature_score",
    "retrieval_policy_response_compaction",
    "retrieval_policy_value_intent_mismatch_penalty",
    "resolve_internal_candidate_top_k",
    "safe_positive_int",
    "summarize_kg_hint_diagnostics",
]
