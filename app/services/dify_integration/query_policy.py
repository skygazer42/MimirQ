"""Dify query policy rules and operations."""

from typing import Any

from app.core.config import settings
from app.services.dify_integration import policy_helpers
from app.services.dify_integration.anchor_strength import _query_intent_terms as _query_intent_terms
from app.services.dify_integration.common import (
    _EXACT_QUERY_ANCHOR_FIELDS,
    _METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS,
    _MIXED_INTENT_SPLIT_RE,
)
from app.services.dify_integration.common import _MIN_SPECIFIC_INTENT_CHARS as _MIN_SPECIFIC_INTENT_CHARS
from app.services.dify_integration.common import _QUESTION_ANCHOR_QUERY_MARKERS as _QUESTION_ANCHOR_QUERY_MARKERS
from app.services.dify_integration.common import (
    _SERVICE_ANCHOR_QUERY_TRAILING_CHARS as _SERVICE_ANCHOR_QUERY_TRAILING_CHARS,
)
from app.services.dify_integration.common import _metadata_terms as _metadata_terms
from app.services.dify_integration.common import _normalize_match_term as _normalize_match_term
from app.services.dify_integration.policy_helpers import (
    mixed_intent_leading_noise_terms_for_policy_refs as _mixed_intent_leading_noise_terms_for_policy_refs,
)
from app.services.dify_integration.policy_helpers import (
    mixed_intent_subject_terms_for_policy_refs as _mixed_intent_subject_terms_for_policy_refs,
)
from app.services.dify_integration.policy_helpers import (
    service_anchor_entity_terms_for_policy_refs as _service_anchor_entity_terms_for_policy_refs,
)
from app.services.dify_integration.policy_helpers import (
    service_anchor_priority_terms_for_policy_refs as _service_anchor_priority_terms_for_policy_refs,
)
from app.services.dify_integration.query_terms import (
    _append_metadata_anchor_segment_terms as _append_metadata_anchor_segment_terms,
)
from app.services.dify_integration.query_terms import _append_metadata_anchor_term as _append_metadata_anchor_term
from app.services.dify_integration.query_terms import (
    _metadata_anchor_service_name_query_terms as _metadata_anchor_service_name_query_terms,
)
from app.services.dify_integration.query_terms import (
    _service_anchor_query_noise_variants as _service_anchor_query_noise_variants,
)
from app.services.dify_integration.scoring import _mixed_intent_segment_parts as _mixed_intent_segment_parts
from app.services.dify_integration.scoring import _query_has_explicit_question_form as _query_has_explicit_question_form
from app.services.dify_integration.scoring import _query_has_mixed_intent as _query_has_mixed_intent
from app.services.dify_integration.scoring import (
    _query_has_quoted_anchor_candidate as _query_has_quoted_anchor_candidate,
)
from app.services.dify_integration.scoring import (
    _query_is_short_question_anchor_candidate as _query_is_short_question_anchor_candidate,
)
from app.services.dify_integration.scoring import (
    _quoted_query_anchor_display_terms as _quoted_query_anchor_display_terms,
)
from app.services.dify_integration.scoring import _response_hint_string_list as _response_hint_string_list
from app.services.dify_integration.scoring import _strip_mixed_intent_noise as _strip_mixed_intent_noise
from app.services.dify_integration.scoring import (
    _strip_mixed_intent_subject_instruction_tail as _strip_mixed_intent_subject_instruction_tail,
)


def _question_anchor_intent_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = policy_helpers.retrieval_policy_for_plugin_ref(plugin_ref)
        for raw_term in _response_hint_string_list(policy, "question_intent_terms"):
            term = str(raw_term or "").strip()
            normalized = _normalize_match_term(term)
            if not term or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(term)
    return tuple(terms)


def _query_prefers_question_anchor(query: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> bool:
    text = str(query or "").strip()
    if not text:
        return False
    if any(marker in text for marker in _QUESTION_ANCHOR_QUERY_MARKERS):
        return True
    return bool(
        _query_intent_terms(
            text,
            intent_terms=_question_anchor_intent_terms_for_policy_refs(policy_plugin_refs),
        )
        or _query_is_short_question_anchor_candidate(text, policy_plugin_refs=policy_plugin_refs)
    )


def _query_prefers_service_anchor(query: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> bool:
    query_term = _normalize_match_term(query)
    if len(query_term) < 3:
        return False
    if _query_has_quoted_anchor_candidate(query):
        return True
    for term in _service_anchor_priority_terms_for_policy_refs(policy_plugin_refs):
        normalized = _normalize_match_term(term)
        if len(normalized) < 3:
            continue
        if normalized in query_term:
            return True
    entity_terms = tuple(
        _normalize_match_term(term)
        for term in _service_anchor_entity_terms_for_policy_refs(policy_plugin_refs)
        if _normalize_match_term(term)
    )
    if entity_terms and any(marker in query_term for marker in entity_terms):
        for term in _metadata_anchor_service_name_query_terms(query, policy_plugin_refs=policy_plugin_refs)[:6]:
            if len(_normalize_match_term(term)) >= _MIN_SPECIFIC_INTENT_CHARS:
                return True
    return False


def _query_has_mixed_intent_for_policy(query: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> bool:
    if _query_has_mixed_intent(query):
        return True
    requested_slots = _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
    return len({(field, value) for field, value in requested_slots}) >= 2


def _anchor_binding_fields_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    fields: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = policy_helpers.retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        raw_binding = policy.get("anchor_binding")
        if isinstance(raw_binding, dict) and raw_binding.get("enabled") is True:
            for field in _metadata_terms(raw_binding.get("anchor_fields")):
                normalized = _normalize_match_term(field)
                if normalized and field not in seen:
                    seen.add(field)
                    fields.append(field)
        raw_anchor_fields = policy.get("anchor_fields")
        if isinstance(raw_anchor_fields, list | tuple):
            for raw in raw_anchor_fields:
                raw_dict = dict(raw) if isinstance(raw, dict) else {}
                field = str(raw_dict.get("metadata") or "").strip()
                normalized = _normalize_match_term(field)
                if normalized and field not in seen:
                    seen.add(field)
                    fields.append(field)
    return tuple(fields)


def _exact_query_anchor_fields_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    fields: list[str] = []
    seen: set[str] = set()
    anchor_fields = _anchor_binding_fields_for_policy_refs(policy_plugin_refs) or (
        "service_name",
        "case_title",
        "service_aliases",
    )
    for field in (*_EXACT_QUERY_ANCHOR_FIELDS, *anchor_fields):
        text = str(field or "").strip()
        if text and text not in seen:
            seen.add(text)
            fields.append(text)
    return tuple(fields)


def _policy_slot_intent_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = policy_helpers.retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        for raw_mapping in policy.get("query_expansion_values") or ():
            mapping = dict(raw_mapping) if isinstance(raw_mapping, dict) else {}
            for raw_term in mapping.get("terms") or ():
                term = str(raw_term or "").strip()
                normalized = _normalize_match_term(term)
                if len(normalized) < 3 or normalized in seen:
                    continue
                seen.add(normalized)
                terms.append(term)
    return tuple(terms)


def _metadata_anchor_preflight_block_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = policy_helpers.retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        for raw_term in _response_hint_string_list(policy, "metadata_anchor_preflight_block_terms"):
            term = str(raw_term or "").strip()
            normalized = _normalize_match_term(term)
            if not term or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(term)
    return tuple(terms)


def _query_blocks_metadata_anchor_preflight(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    query_term = _normalize_match_term(query)
    if not query_term:
        return False
    return any(
        (normalized := _normalize_match_term(term)) and normalized in query_term
        for term in _metadata_anchor_preflight_block_terms_for_policy_refs(policy_plugin_refs)
    )


def _requested_policy_slot_values_for_query(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for _field, value in _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs):
        normalized_value = _normalize_match_term(value)
        if not value or not normalized_value or normalized_value in seen:
            continue
        seen.add(normalized_value)
        values.append(value)
    return tuple(values)


def _requested_policy_slot_specs_for_query(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[tuple[str, str], ...]:
    query_term = _normalize_match_term(query)
    if len(query_term) < 3:
        return ()
    specs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = policy_helpers.retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        for raw_mapping in policy.get("query_expansion_values") or ():
            mapping = dict(raw_mapping) if isinstance(raw_mapping, dict) else {}
            field = str(mapping.get("metadata") or "").strip()
            if not field:
                continue
            raw_values = mapping.get("values") if isinstance(mapping.get("values"), list | tuple | set) else None
            slot_values = raw_values or [mapping.get("value")]
            terms = tuple(_metadata_terms(mapping.get("terms")))
            if not terms:
                continue
            if not any((normalized := _normalize_match_term(term)) and normalized in query_term for term in terms):
                continue
            for raw_value in slot_values:
                value = str(raw_value or "").strip()
                normalized_value = _normalize_match_term(value)
                key = f"{field}\0{normalized_value}"
                if not value or not normalized_value or key in seen:
                    continue
                seen.add(key)
                specs.append((field, value))
    return tuple(specs)


def _query_has_policy_slot_intent(query: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> bool:
    query_term = _normalize_match_term(query)
    if len(query_term) < 3:
        return False
    for term in _policy_slot_intent_terms_for_policy_refs(policy_plugin_refs):
        normalized = _normalize_match_term(term)
        if len(normalized) >= 3 and normalized in query_term:
            return True
    return False


def _query_allows_metadata_anchor_preflight(
    query: str,
    *,
    query_prefers_question_anchor: bool,
    query_prefers_service_anchor: bool,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    if _query_blocks_metadata_anchor_preflight(query, policy_plugin_refs=policy_plugin_refs):
        return False
    if _query_has_mixed_intent_for_policy(query, policy_plugin_refs=policy_plugin_refs):
        if (
            query_prefers_service_anchor
            and not _query_has_quoted_anchor_candidate(query)
            and any(
                marker in str(query or "")
                for marker in ("合并回答", "一并回答", "一起回答", "分别回答", "分开回答", "请合并", "请分别")
            )
        ):
            return False
        return bool(
            query_prefers_service_anchor
            or (
                _query_has_quoted_anchor_candidate(query)
                and _query_has_policy_slot_intent(query, policy_plugin_refs=policy_plugin_refs)
            )
        )
    if (
        query_prefers_question_anchor
        and not query_prefers_service_anchor
        and _query_has_policy_slot_intent(query, policy_plugin_refs=policy_plugin_refs)
    ):
        return False
    return bool(query_prefers_question_anchor or query_prefers_service_anchor)


def _metadata_anchor_should_query_question_first(
    query: str,
    *,
    query_prefers_question_anchor: bool,
    query_prefers_service_anchor: bool,
    prefer_question_anchor_first: bool,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    if not query_prefers_question_anchor:
        return False
    if query_prefers_service_anchor and _query_has_quoted_anchor_candidate(query):
        return False
    if query_prefers_service_anchor and _requested_policy_slot_specs_for_query(
        query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return True
    return bool(
        prefer_question_anchor_first or not query_prefers_service_anchor or _query_has_explicit_question_form(query)
    )


def _mixed_intent_subject_anchor(segment: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> str:
    text = _strip_mixed_intent_noise(
        segment,
        terms=_mixed_intent_leading_noise_terms_for_policy_refs(policy_plugin_refs),
    )
    if not text:
        return ""
    best_index = len(text)
    intent_markers = _mixed_intent_subject_terms_for_policy_refs(policy_plugin_refs)
    for marker in sorted((str(item or "").strip() for item in intent_markers), key=len, reverse=True):
        if not marker:
            continue
        index = text.find(marker)
        if index >= 0:
            best_index = min(best_index, index)
    anchor = _strip_mixed_intent_subject_instruction_tail(text[:best_index])
    if any(marker in anchor for marker in ("/", "线上", "线下")):
        return ""
    return anchor if len(_normalize_match_term(anchor)) >= 3 else ""


def _clean_mixed_intent_query_segment(segment: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> str:
    return _strip_mixed_intent_noise(
        segment,
        terms=_mixed_intent_leading_noise_terms_for_policy_refs(policy_plugin_refs),
    )


def _mixed_intent_retrieval_queries(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    text = str(query or "").strip()
    if not _query_has_mixed_intent_for_policy(text, policy_plugin_refs=policy_plugin_refs):
        return ()

    max_queries = max(
        1,
        min(
            5,
            (settings.DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_MAX_SUBQUERIES or 4),
        ),
    )
    out: list[str] = []
    seen: set[str] = {_normalize_match_term(text)}
    quoted_subject_anchor = next(iter(_quoted_query_anchor_display_terms(text)), "")
    subject_anchor = quoted_subject_anchor
    for raw_segment in _MIXED_INTENT_SPLIT_RE.split(text):
        subject_anchor = _append_mixed_intent_queries_for_segment_parts(
            raw_segment,
            out,
            seen=seen,
            max_queries=max_queries,
            subject_anchor=subject_anchor,
            quoted_subject_anchor=quoted_subject_anchor,
            policy_plugin_refs=policy_plugin_refs,
        )
        if len(out) >= max_queries:
            break
    for fallback_query in _mixed_intent_policy_slot_queries_from_inferred_subject(
        text,
        policy_plugin_refs=policy_plugin_refs,
    ):
        if _append_unique_mixed_intent_query(out, seen, fallback_query, max_queries=max_queries):
            break
    return tuple(out)


def _append_mixed_intent_queries_for_segment_parts(
    raw_segment: str,
    out: list[str],
    *,
    seen: set[str],
    max_queries: int,
    subject_anchor: str,
    quoted_subject_anchor: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> str:
    parts = _mixed_intent_segment_parts(raw_segment)
    for raw_part in parts:
        subject_anchor, candidates = _mixed_intent_segment_candidates(
            raw_part,
            subject_anchor=subject_anchor,
            quoted_subject_anchor=quoted_subject_anchor,
            policy_plugin_refs=policy_plugin_refs,
        )
        for candidate in candidates:
            if _append_unique_mixed_intent_query(out, seen, candidate, max_queries=max_queries):
                return subject_anchor
        if len(out) >= max_queries:
            return subject_anchor
        segment = _clean_mixed_intent_query_segment(raw_part, policy_plugin_refs=policy_plugin_refs)
        if (
            not out
            and len(parts) == 1
            and _append_first_inferred_subject_query(
                out,
                seen=seen,
                query=segment,
                max_queries=max_queries,
                policy_plugin_refs=policy_plugin_refs,
            )
        ):
            return subject_anchor
        for expanded_candidate in _mixed_intent_policy_slot_queries(
            segment=segment,
            subject_anchor=subject_anchor,
            policy_plugin_refs=policy_plugin_refs,
        ):
            if _append_unique_mixed_intent_query(
                out,
                seen,
                expanded_candidate,
                max_queries=max_queries,
            ):
                return subject_anchor
    return subject_anchor


def _append_first_inferred_subject_query(
    out: list[str],
    *,
    seen: set[str],
    query: str,
    max_queries: int,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    for fallback_query in _mixed_intent_policy_slot_queries_from_inferred_subject(
        query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return _append_unique_mixed_intent_query(out, seen, fallback_query, max_queries=max_queries)
    return False


def _append_unique_mixed_intent_query(
    out: list[str],
    seen: set[str],
    candidate: str,
    *,
    max_queries: int,
) -> bool:
    normalized = _normalize_match_term(candidate)
    if len(normalized) < 4 or normalized in seen:
        return False
    seen.add(normalized)
    out.append(candidate)
    return len(out) >= max_queries


def _mixed_intent_segment_candidates(
    raw_part: str,
    *,
    subject_anchor: str,
    quoted_subject_anchor: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, tuple[str, ...]]:
    segment = _clean_mixed_intent_query_segment(raw_part, policy_plugin_refs=policy_plugin_refs)
    normalized_segment = _normalize_match_term(segment)
    segment_has_intent_marker = _mixed_intent_segment_has_intent_marker(
        segment,
        policy_plugin_refs=policy_plugin_refs,
    )
    if len(normalized_segment) < 3 and not (subject_anchor and segment_has_intent_marker):
        return subject_anchor, ()
    segment_anchor = _mixed_intent_subject_anchor(segment, policy_plugin_refs=policy_plugin_refs)
    if segment_anchor and not quoted_subject_anchor:
        next_subject_anchor = segment_anchor
        return (
            next_subject_anchor,
            (segment,) if segment_has_intent_marker else (),
        )
    if subject_anchor and not segment_has_intent_marker:
        return subject_anchor, ()
    candidate = f"{subject_anchor}{segment}" if subject_anchor else segment
    return subject_anchor, (candidate,)


def _mixed_intent_policy_slot_queries_from_inferred_subject(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    requested_slots = _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
    if len({(field, value) for field, value in requested_slots}) < 2:
        return ()
    subject = _infer_mixed_intent_subject_anchor(query, policy_plugin_refs=policy_plugin_refs)
    if len(_normalize_match_term(subject)) < 3:
        return ()

    out: list[str] = []
    seen_values: set[tuple[str, str]] = set()
    for field, value in requested_slots:
        key = (field, value)
        if key in seen_values:
            continue
        seen_values.add(key)
        term = _policy_slot_canonical_query_term(field=field, value=value, policy_plugin_refs=policy_plugin_refs)
        if not term:
            continue
        out.append(f"{subject}{term}")
    return tuple(out)


def _infer_mixed_intent_subject_anchor(query: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> str:
    quoted_subject = next(iter(_quoted_query_anchor_display_terms(query)), "")
    if quoted_subject:
        return quoted_subject
    direct_subject = _mixed_intent_subject_anchor(query, policy_plugin_refs=policy_plugin_refs)
    if direct_subject:
        return direct_subject
    parts = _mixed_intent_segment_parts(query)
    for part in reversed(parts):
        cleaned = _clean_mixed_intent_query_segment(part, policy_plugin_refs=policy_plugin_refs)
        if not _mixed_intent_segment_has_intent_marker(cleaned, policy_plugin_refs=policy_plugin_refs):
            normalized = _normalize_match_term(cleaned)
            if len(normalized) >= 3:
                return cleaned.strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
    return ""


def _policy_slot_canonical_query_term(
    *,
    field: str,
    value: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> str:
    normalized_field = str(field or "").strip()
    normalized_value = _normalize_match_term(value)
    if not normalized_field or not normalized_value:
        return ""
    for plugin_ref in policy_plugin_refs or ():
        policy = policy_helpers.retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        mappings = [
            dict(raw_mapping)
            for raw_mapping in policy.get("query_expansion_values") or ()
            if isinstance(raw_mapping, dict)
        ]
        mappings.sort(key=lambda mapping: 1 if isinstance(mapping.get("values"), list | tuple | set) else 0)
        for mapping in mappings:
            if str(mapping.get("metadata") or "").strip() != normalized_field:
                continue
            raw_values = mapping.get("values") if isinstance(mapping.get("values"), list | tuple | set) else None
            values = raw_values or [mapping.get("value")]
            if normalized_value not in {_normalize_match_term(item) for item in values}:
                continue
            terms = tuple(_metadata_terms(mapping.get("terms")))
            return next((term for term in terms if len(_normalize_match_term(term)) >= 2), "")
    return str(value or "").strip()


def _policy_slot_query_terms(
    *,
    field: str,
    value: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    normalized_field = str(field or "").strip()
    normalized_value = _normalize_match_term(value)
    if not normalized_field or not normalized_value:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = policy_helpers.retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        for raw_mapping in policy.get("query_expansion_values") or ():
            mapping = dict(raw_mapping) if isinstance(raw_mapping, dict) else {}
            if str(mapping.get("metadata") or "").strip() != normalized_field:
                continue
            raw_values = mapping.get("values") if isinstance(mapping.get("values"), list | tuple | set) else None
            values = raw_values or [mapping.get("value")]
            if normalized_value not in {_normalize_match_term(item) for item in values}:
                continue
            for raw_term in (*_metadata_terms(mapping.get("terms")), value):
                term = str(raw_term or "").strip()
                normalized = _normalize_match_term(term)
                if len(normalized) < 2 or normalized in seen:
                    continue
                seen.add(normalized)
                out.append(term)
    return tuple(out)


def _mixed_intent_policy_slot_queries(
    *,
    segment: str,
    subject_anchor: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    segment_term = _normalize_match_term(segment)
    subject = str(subject_anchor or "").strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
    if len(segment_term) < 3 or len(_normalize_match_term(subject)) < 3:
        return ()

    out: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = policy_helpers.retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        mappings = [dict(item) for item in policy.get("query_expansion_values") or () if isinstance(item, dict)]
        canonical_terms_by_value = _policy_slot_canonical_terms_by_value(mappings)
        for mapping in mappings:
            mapping_terms = tuple(_metadata_terms(mapping.get("terms")))
            if not any(
                (normalized := _normalize_match_term(term)) and normalized in segment_term for term in mapping_terms
            ):
                continue
            _append_mixed_intent_policy_slot_queries(
                out,
                seen=seen,
                subject=subject,
                segment_term=segment_term,
                mapping=mapping,
                canonical_terms_by_value=canonical_terms_by_value,
            )
    return tuple(out)


def _policy_slot_canonical_terms_by_value(mappings: list[dict[str, Any]]) -> dict[str, list[str]]:
    canonical_terms: dict[str, list[str]] = {}
    for mapping in mappings:
        if "values" in mapping:
            continue
        value = str(mapping.get("value") or "").strip()
        if value:
            canonical_terms.setdefault(value, []).extend(_metadata_terms(mapping.get("terms")))
    return canonical_terms


def _append_mixed_intent_policy_slot_queries(
    out: list[str],
    *,
    seen: set[str],
    subject: str,
    segment_term: str,
    mapping: dict[str, Any],
    canonical_terms_by_value: dict[str, list[str]],
) -> None:
    raw_values = mapping.get("values") if isinstance(mapping.get("values"), list | tuple | set) else None
    for raw_value in raw_values or [mapping.get("value")]:
        value = str(raw_value or "").strip()
        if not value:
            continue
        canonical_terms = canonical_terms_by_value.get(value, [])
        if any((normalized := _normalize_match_term(term)) and normalized in segment_term for term in canonical_terms):
            continue
        canonical_term = next(
            (
                term
                for term in canonical_terms
                if (normalized := _normalize_match_term(term)) and normalized not in segment_term
            ),
            "",
        )
        normalized_canonical = _normalize_match_term(canonical_term)
        if len(normalized_canonical) < 2 or normalized_canonical in seen:
            continue
        seen.add(normalized_canonical)
        out.append(f"{subject}{canonical_term}")


def _mixed_intent_segment_has_intent_marker(segment: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> bool:
    text = str(segment or "").strip()
    if not text:
        return False
    markers = _mixed_intent_subject_terms_for_policy_refs(policy_plugin_refs)
    if not markers:
        return True
    return any(marker and marker in text for marker in markers)


def _metadata_anchor_title_query_terms(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[str]:
    cleaned_variants = _service_anchor_query_noise_variants(
        query,
        policy_plugin_refs=policy_plugin_refs,
    )
    if not cleaned_variants:
        return []

    terms: list[str] = []
    seen: set[str] = set()

    for cleaned in cleaned_variants:
        _append_metadata_anchor_term(
            terms,
            seen,
            cleaned,
            min_chars=3,
            cjk_min_chars=3,
        )
    _append_metadata_anchor_segment_terms(
        terms,
        seen=seen,
        cleaned_variants=cleaned_variants,
        sizes=(8, 6, 4, 3),
        limit=_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS,
        min_chars=3,
        cjk_min_chars=3,
    )
    return terms[:_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS]
