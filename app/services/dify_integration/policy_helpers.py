
from collections.abc import Callable
from typing import Any


def knowledge_mapping_plugin_refs(mapping: Any) -> tuple[str, ...]:
    if not isinstance(mapping, dict):
        return ()
    raw_refs = mapping.get("plugin_refs") or mapping.get("pipeline_plugin_refs") or mapping.get("plugin_ref")
    refs = raw_refs if isinstance(raw_refs, list | tuple | set) else [raw_refs]
    out: list[str] = []
    seen: set[str] = set()
    for raw in refs:
        ref = str(raw or "").strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        out.append(ref)
    return tuple(out)


def retrieval_policy_filter_fields_for_plugin_refs(
    plugin_refs: tuple[str, ...],
    *,
    policy_resolver: Callable[[str], dict[str, Any]],
) -> set[str] | None:
    if not plugin_refs:
        return None
    out: set[str] = set()
    for plugin_ref in plugin_refs:
        policy = policy_resolver(plugin_ref)
        raw_fields = policy.get("filter_fields") if isinstance(policy, dict) else None
        if not isinstance(raw_fields, list | tuple | set):
            continue
        for raw in raw_fields:
            field_name = str(raw or "").strip()
            if field_name:
                out.add(field_name)
    return out


def retrieval_policy_fallback_multiplier_for_plugin_refs(
    plugin_refs: tuple[str, ...],
    *,
    policy_resolver: Callable[[str], dict[str, Any]],
    fallback_multiplier_resolver: Callable[[dict[str, Any]], int],
) -> int:
    multiplier = 1
    for plugin_ref in plugin_refs:
        multiplier = max(multiplier, fallback_multiplier_resolver(policy_resolver(plugin_ref)))
    return multiplier


def response_hints_for_record(
    record: dict[str, Any],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
    record_plugin_ref: Callable[[dict[str, Any], tuple[str, ...]], str],
    policy_resolver: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    plugin_ref = record_plugin_ref(record, policy_plugin_refs)
    if not plugin_ref:
        return {}
    policy = policy_resolver(plugin_ref)
    raw = policy.get("response_hints") if isinstance(policy, dict) else None
    return dict(raw) if isinstance(raw, dict) else {}


def response_hints_for_metadata(
    metadata: dict[str, Any],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
    response_hints_for_record: Callable[[dict[str, Any], tuple[str, ...]], dict[str, Any]],
) -> dict[str, Any]:
    return response_hints_for_record({"metadata": metadata}, policy_plugin_refs)


def policy_string_terms_for_policy_refs(
    policy_plugin_refs: tuple[str, ...],
    key: str,
    *,
    policy_resolver: Callable[[str], dict[str, Any]],
    metadata_terms: Callable[[Any], tuple[str, ...] | list[str]],
    normalize_term: Callable[[str], str],
) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = policy_resolver(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        for raw_term in metadata_terms(policy.get(key)):
            term = str(raw_term or "").strip()
            normalized = normalize_term(term)
            if not term or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(term)
    return tuple(terms)


def service_anchor_admin_aliases_for_policy_refs(
    policy_plugin_refs: tuple[str, ...],
    *,
    policy_resolver: Callable[[str], dict[str, Any]],
    metadata_terms: Callable[[Any], tuple[str, ...] | list[str]],
    normalize_term: Callable[[str], str],
) -> tuple[str, ...]:
    aliases: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = policy_resolver(plugin_ref)
        for raw_field in policy.get("anchor_fields") or ():
            field = dict(raw_field) if isinstance(raw_field, dict) else {}
            if str(field.get("role") or "").strip() != "administrative_area":
                continue
            raw_aliases = field.get("aliases")
            if not isinstance(raw_aliases, dict):
                continue
            for canonical, values in raw_aliases.items():
                for raw_value in (canonical, *metadata_terms(values)):
                    value = str(raw_value or "").strip()
                    normalized = normalize_term(value)
                    if not value or not normalized or normalized in seen:
                        continue
                    seen.add(normalized)
                    aliases.append(value)
    return tuple(aliases)


def fast_response_field_rules_for_policy_refs(
    policy_plugin_refs: tuple[str, ...],
    *,
    policy_resolver: Callable[[str], dict[str, Any]],
    metadata_terms: Callable[[Any], tuple[str, ...] | list[str]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    rules: list[tuple[str, tuple[str, ...]]] = []
    seen_labels: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = policy_resolver(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        for raw_rule in policy.get("fast_response_field_rules") or ():
            rule = dict(raw_rule) if isinstance(raw_rule, dict) else {}
            label = str(rule.get("label") or "").strip()
            if not label or label in seen_labels:
                continue
            markers = tuple(marker for marker in metadata_terms(rule.get("markers")) if str(marker or "").strip())
            if not markers:
                continue
            seen_labels.add(label)
            rules.append((label, markers))
    return tuple(rules)


def requested_label_prefixes_for_policy_refs(
    policy_plugin_refs: tuple[str, ...],
    *,
    policy_resolver: Callable[[str], dict[str, Any]],
    response_hint_dict_list: Callable[[dict[str, Any], str], list[dict[str, Any]]],
) -> tuple[str, ...]:
    prefixes: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = policy_resolver(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        response_hints = policy.get("response_hints")
        if not isinstance(response_hints, dict):
            continue
        for field_spec in response_hint_dict_list(response_hints, "answer_highlight_metadata_fields"):
            prefix = str(field_spec.get("requested_labels_prefix") or "").strip()
            if not prefix or prefix in seen:
                continue
            seen.add(prefix)
            prefixes.append(prefix)
    return tuple(prefixes)


def resolved_policy_terms_for_plugin_refs(
    policy_plugin_refs: tuple[str, ...],
    *,
    policy_resolver: Callable[[str], dict[str, Any]],
    terms_resolver: Callable[[dict[str, Any]], tuple[str, ...] | list[str]],
    normalize_term: Callable[[str], str] | None = None,
) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = policy_resolver(plugin_ref)
        for raw_term in terms_resolver(policy):
            term = str(raw_term or "").strip()
            normalized = normalize_term(term) if normalize_term is not None else term
            if not term or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(term)
    return tuple(terms)


def mixed_intent_leading_noise_terms_for_policy_refs(
    policy_plugin_refs: tuple[str, ...],
    *,
    default_terms: tuple[str, ...],
    policy_resolver: Callable[[str], dict[str, Any]],
    terms_resolver: Callable[[dict[str, Any]], tuple[str, ...] | list[str]],
    normalize_term: Callable[[str], str],
) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw_term in default_terms:
        term = str(raw_term or "").strip()
        normalized = normalize_term(term)
        if not term or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(term)
    for plugin_ref in policy_plugin_refs or ():
        policy = policy_resolver(plugin_ref)
        for raw_term in terms_resolver(policy):
            term = str(raw_term or "").strip()
            normalized = normalize_term(term)
            if not term or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(term)
    return tuple(terms)


def resolve_knowledge_policy_filter_fields(
    knowledge_id: str,
    *,
    knowledge_map: dict[str, Any],
    knowledge_mapping_plugin_refs: Callable[[Any], tuple[str, ...]],
    retrieval_policy_filter_fields_for_plugin_refs: Callable[[tuple[str, ...]], set[str] | None],
) -> set[str] | None:
    key = str(knowledge_id or "").strip()
    raw_mapping = knowledge_map.get(key)
    return retrieval_policy_filter_fields_for_plugin_refs(knowledge_mapping_plugin_refs(raw_mapping))


def resolve_knowledge_policy_fallback_multiplier(
    knowledge_id: str,
    *,
    knowledge_map: dict[str, Any],
    knowledge_mapping_plugin_refs: Callable[[Any], tuple[str, ...]],
    retrieval_policy_fallback_multiplier_for_plugin_refs: Callable[[tuple[str, ...]], int],
) -> int:
    key = str(knowledge_id or "").strip()
    raw_mapping = knowledge_map.get(key)
    return retrieval_policy_fallback_multiplier_for_plugin_refs(knowledge_mapping_plugin_refs(raw_mapping))


def resolve_knowledge_policy_plugin_refs(
    knowledge_id: str,
    *,
    knowledge_map: dict[str, Any],
    knowledge_mapping_plugin_refs: Callable[[Any], tuple[str, ...]],
) -> tuple[str, ...]:
    key = str(knowledge_id or "").strip()
    raw_mapping = knowledge_map.get(key)
    return knowledge_mapping_plugin_refs(raw_mapping)


def apply_policy_fallback_candidate_multiplier(
    candidate_top_k: int,
    *,
    multiplier: int,
    configured_max: int,
) -> int:
    safe_candidate_top_k = max(1, int(candidate_top_k or 1))
    safe_multiplier = max(1, int(multiplier or 1))
    safe_configured_max = max(safe_candidate_top_k, int(configured_max or 1))
    return min(safe_configured_max, safe_candidate_top_k * safe_multiplier)
