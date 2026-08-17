"""Query intent analysis, anchor detection, and score-bonus helpers for the Dify adapter.

Mechanically extracted from `app.api.v1.integrations_dify`; do not import that
module from here (see package docstring).
"""

import hashlib
import re
from difflib import SequenceMatcher
from typing import Any

from fastapi import Request

from app.api.v1.dify_support.common import (
    _CJK_RE,
    _DEFAULT_RESPONSE_HINT_ANSWER_PREFIX,
    _EXACT_PRIMARY_ALIAS_MATCH_BONUS,
    _EXPLICIT_QUESTION_FORM_MARKERS,
    _FUZZY_METADATA_ANCHOR_KEYS,
    _MAX_HINT_VALUE_CHARS,
    _MAX_QA_HINT_VALUE_CHARS,
    _METADATA_ANCHOR_KEYS,
    _MIN_REGION_ANCHOR_OVERLAP_CHARS,
    _MIN_REGIONAL_QUESTION_OVERLAP_CHARS,
    _MIN_SPECIFIC_INTENT_CHARS,
    _MIXED_INTENT_LIST_SPLIT_RE,
    _MIXED_INTENT_QUERY_MARKERS,
    _MIXED_INTENT_SUBJECT_TRAILING_INSTRUCTION_RE,
    _PUBLIC_METADATA_VIEW_KEYS,
    _QUESTION_ANCHOR_NEAR_MATCH_MIN_CHARS,
    _QUESTION_ANCHOR_NEAR_MATCH_MIN_RATIO,
    _QUESTION_ANCHOR_QUERY_MARKERS,
    _QUESTION_ANCHOR_SHORT_QUERY_MAX_CHARS,
    _QUESTION_ANCHOR_SHORT_QUERY_MIN_CHARS,
    _QUOTED_ANCHOR_RE,
    _REGION_ANCHOR_KEYS,
    _SERVICE_ANCHOR_ADMIN_MARKERS,
    _SERVICE_ANCHOR_QUERY_TRAILING_CHARS,
    _SOURCE_RECORD_ID_KEYS,
    _SOURCE_RECORD_SCOPE_KEYS,
    _iter_record_metadata_layers,
    _metadata_terms,
    _normalize_match_term,
)
from app.core.config import settings


def _request_client_ip(request: Request) -> str:
    forwarded_for = str(request.headers.get("x-forwarded-for") or "").strip()
    if forwarded_for:
        first = forwarded_for.split(",", 1)[0].strip()
        if first:
            return first
    return str(getattr(getattr(request, "client", None), "host", "") or "").strip()


def _diagnostic_value_hash(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:16]


def _diagnostic_query_hash(query: str) -> str:
    return _diagnostic_value_hash(query)


def _is_cjk_char(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def _contains_cjk(value: str) -> bool:
    return any(_is_cjk_char(char) for char in str(value or ""))


def _is_anchor_word_char(char: str) -> bool:
    return (char.isascii() and char.isalnum()) or _is_cjk_char(char)


def _iter_anchor_word_segments(value: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    for char in str(value or ""):
        if _is_anchor_word_char(char):
            current.append(char)
            continue
        if current:
            segments.append("".join(current))
            current = []
    if current:
        segments.append("".join(current))
    return segments


def _strip_trailing_service_anchor_admin(value: str, *, admin_aliases: tuple[str, ...]) -> str:
    text = str(value or "").strip()
    for marker in _SERVICE_ANCHOR_ADMIN_MARKERS:
        for alias in admin_aliases:
            suffix = f"{marker}{alias}"
            if text.endswith(suffix):
                return text[: -len(suffix)].strip()
    return text


def _rstrip_service_anchor_query_noise(value: str) -> str:
    return str(value or "").rstrip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS).strip()


def _clamp_hint_value(value: str, *, limit: int = _MAX_HINT_VALUE_CHARS) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _field_line_parts(line: str) -> tuple[str, str] | None:
    text = str(line or "").strip()
    if not text:
        return None
    colon_positions = [index for index in (text.find("："), text.find(":")) if index >= 0]
    if not colon_positions:
        return None
    split_at = min(colon_positions)
    label = text[:split_at].strip()
    value = text[split_at + 1 :].strip()
    if not label or not value or len(label) > 20:
        return None
    return label, value


def _response_hint_string_list(
    response_hints: dict[str, Any], key: str, *, default: tuple[str, ...] = ()
) -> tuple[str, ...]:
    raw = response_hints.get(key) if isinstance(response_hints, dict) else None
    if raw is None:
        return default
    if not isinstance(raw, list | tuple | set):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def _response_hint_text(response_hints: dict[str, Any], key: str, *, default: str) -> str:
    value = response_hints.get(key) if isinstance(response_hints, dict) else None
    text = str(value or "").strip()
    return text or default


def _response_hint_dict(response_hints: dict[str, Any], key: str) -> dict[str, Any]:
    raw = response_hints.get(key) if isinstance(response_hints, dict) else None
    return dict(raw) if isinstance(raw, dict) else {}


def _response_hint_dict_list(response_hints: dict[str, Any], key: str) -> tuple[dict[str, Any], ...]:
    raw = response_hints.get(key) if isinstance(response_hints, dict) else None
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(dict(item) for item in raw if isinstance(item, dict))


def _response_hint_groups(response_hints: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    raw_groups = response_hints.get("groups") if isinstance(response_hints, dict) else None
    if not isinstance(raw_groups, list):
        return ()
    return tuple(dict(group) for group in raw_groups if isinstance(group, dict))


def _structured_fields_from_content(content: str, *, response_hints: dict[str, Any]) -> dict[str, str]:
    labels = set(_response_hint_string_list(response_hints, "structured_labels"))
    if not labels:
        return {}
    fields: dict[str, str] = {}
    for line in str(content or "").splitlines():
        parts = _field_line_parts(line)
        if parts is None:
            continue
        label, value = parts
        if label not in labels or label in fields:
            continue
        answer_labels = set(_response_hint_string_list(response_hints, "answer_labels"))
        limit = _MAX_QA_HINT_VALUE_CHARS if label in answer_labels else _MAX_HINT_VALUE_CHARS
        fields[label] = _clamp_hint_value(value, limit=limit)
    return fields


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


def _near_question_anchor_match(query_term: str, candidate: str) -> bool:
    if (
        len(query_term) < _QUESTION_ANCHOR_NEAR_MATCH_MIN_CHARS
        or len(candidate) < _QUESTION_ANCHOR_NEAR_MATCH_MIN_CHARS
    ):
        return False
    ratio = SequenceMatcher(a=query_term, b=candidate, autojunk=False).ratio()
    return ratio >= _QUESTION_ANCHOR_NEAR_MATCH_MIN_RATIO


def _cjk_bigrams(value: str) -> set[str]:
    text = "".join(char for char in str(value or "") if _CJK_RE.match(char))
    if len(text) < 2:
        return set()
    return {text[index : index + 2] for index in range(0, len(text) - 1)}


def _cjk_bigram_overlap_count(left: str, right: str) -> int:
    return len(_cjk_bigrams(left) & _cjk_bigrams(right))


def _cjk_bigram_overlap_ratio(left: str, right: str) -> float:
    left_bigrams = _cjk_bigrams(left)
    right_bigrams = _cjk_bigrams(right)
    if not left_bigrams or not right_bigrams:
        return 0.0
    return len(left_bigrams & right_bigrams) / max(1, min(len(left_bigrams), len(right_bigrams)))


def _query_is_short_question_anchor_candidate(query: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> bool:
    if not policy_plugin_refs:
        return False
    normalized = _normalize_match_term(query)
    return _QUESTION_ANCHOR_SHORT_QUERY_MIN_CHARS <= len(normalized) <= _QUESTION_ANCHOR_SHORT_QUERY_MAX_CHARS


def _query_has_mixed_intent(query: str) -> bool:
    text = str(query or "").strip()
    if not text:
        return False
    if any(marker in text for marker in _MIXED_INTENT_QUERY_MARKERS):
        return True
    return len(_mixed_intent_segment_parts(text)) >= 2 and bool(re.search(r"[？?。.]?$", text))


def _query_has_explicit_question_form(query: str) -> bool:
    text = str(query or "").strip()
    return bool(text) and any(marker in text for marker in _EXPLICIT_QUESTION_FORM_MARKERS)


def _query_has_quoted_anchor_candidate(query: str) -> bool:
    text = str(query or "").strip()
    if not text:
        return False
    for match in _QUOTED_ANCHOR_RE.finditer(text):
        if len(_normalize_match_term(_quoted_anchor_match_text(match))) >= 4:
            return True
    return False


def _quoted_anchor_match_text(match: re.Match[str]) -> str:
    for group in match.groups():
        text = str(group or "").strip()
        if text:
            return text
    return ""


def _quoted_query_anchor_display_terms(query: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for match in _QUOTED_ANCHOR_RE.finditer(str(query or "")):
        text = match.group(0).strip()
        normalized = _normalize_match_term(_quoted_anchor_match_text(match))
        if len(normalized) >= 4 and normalized not in seen:
            seen.add(normalized)
            out.append(text)
    return tuple(out)


def _quoted_query_anchor_terms(query: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for match in _QUOTED_ANCHOR_RE.finditer(str(query or "")):
        normalized = _normalize_match_term(_quoted_anchor_match_text(match))
        if len(normalized) >= 4 and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return tuple(out)


def _strip_mixed_intent_noise(value: str, *, terms: tuple[str, ...]) -> str:
    text = str(value or "").strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
    previous = None
    while previous != text:
        previous = text
        for term in sorted(terms, key=len, reverse=True):
            if text.startswith(term):
                text = text[len(term) :].strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
                break
    return text


def _strip_mixed_intent_subject_instruction_tail(value: str) -> str:
    text = str(value or "").strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
    previous = None
    while previous != text:
        previous = text
        text = _MIXED_INTENT_SUBJECT_TRAILING_INSTRUCTION_RE.sub("", text).strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
    return text


def _record_policy_slot_coverage_text(record: dict[str, Any]) -> str:
    parts: list[str] = [str(record.get("title") or ""), str(record.get("content") or "")]
    for metadata in _iter_record_metadata_layers(record):
        for value in metadata.values():
            parts.extend(str(term or "") for term in _metadata_terms(value))
    return _normalize_match_term("\n".join(part for part in parts if part))


def _mixed_intent_segment_parts(segment: str) -> tuple[str, ...]:
    text = str(segment or "").strip()
    if not text:
        return ()
    return tuple(part.strip() for part in _MIXED_INTENT_LIST_SPLIT_RE.split(text) if part.strip())


def _question_marker_overlap_bonus(query_term: str, candidate: str) -> float:
    query_has_marker = False
    for marker in _QUESTION_ANCHOR_QUERY_MARKERS:
        normalized_marker = _normalize_match_term(marker)
        if not normalized_marker:
            continue
        query_has_marker = query_has_marker or normalized_marker in query_term
        if normalized_marker in query_term and normalized_marker in candidate:
            return 0.08
    if not query_has_marker and any(
        normalized_marker and normalized_marker in candidate
        for normalized_marker in (_normalize_match_term(marker) for marker in _QUESTION_ANCHOR_QUERY_MARKERS)
    ):
        return 0.08
    return 0.0


def _record_region_terms(record: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for metadata in _iter_record_metadata_layers(record):
        for key in _REGION_ANCHOR_KEYS:
            for term in _metadata_terms(metadata.get(key)):
                normalized = _normalize_match_term(term)
                if len(normalized) < 2 or normalized in seen:
                    continue
                seen.add(normalized)
                out.append(normalized)
    return out


def _record_has_query_region_anchor(record: dict[str, Any], *, query_term: str) -> bool:
    if not query_term:
        return False
    for region in _record_region_terms(record):
        if region in query_term:
            return True
        if _longest_common_substring_length(region, query_term) >= _MIN_REGION_ANCHOR_OVERLAP_CHARS:
            return True
    return False


def _response_hint_candidate_terms(
    fields: dict[str, str],
    metadata: dict[str, Any],
    *,
    group: dict[str, Any],
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    gate = _response_hint_dict(group, "query_gate")
    for label in _response_hint_string_list(gate, "content_labels"):
        for value in _metadata_terms(fields.get(label)):
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
    for layer in [metadata, *[metadata.get(key) for key in _PUBLIC_METADATA_VIEW_KEYS]]:
        if not isinstance(layer, dict):
            continue
        for key in _response_hint_string_list(gate, "metadata"):
            for value in _metadata_terms(layer.get(key)):
                if value in seen:
                    continue
                seen.add(value)
                out.append(value)
    return out


def _response_hint_group_matches_query(
    fields: dict[str, str],
    metadata: dict[str, Any],
    *,
    group: dict[str, Any],
    query: str,
) -> bool:
    gate = _response_hint_dict(group, "query_gate")
    if not gate:
        return True
    query_term = _normalize_match_term(query)
    if not query_term:
        return True
    min_chars = max(1, int(gate.get("min_chars") or 4))
    min_common_chars = max(0, int(gate.get("min_common_chars") or 0))
    for candidate in _response_hint_candidate_terms(fields, metadata, group=group):
        term = _normalize_match_term(candidate)
        if len(term) >= min_chars and (term in query_term or query_term in term):
            return True
        if min_common_chars and min(len(term), len(query_term)) >= min_common_chars:
            if _longest_common_substring_length(query_term, term) >= min_common_chars:
                return True
    return False


def _response_hint_group_has_required_fields(fields: dict[str, str], *, group: dict[str, Any]) -> bool:
    required = _response_hint_string_list(group, "required_any_labels")
    if not required:
        return False
    return any(label in fields for label in required)


def _matching_response_hint_group(
    fields: dict[str, str],
    metadata: dict[str, Any],
    *,
    response_hints: dict[str, Any],
    query: str = "",
) -> dict[str, Any] | None:
    for group in _response_hint_groups(response_hints):
        if not _response_hint_group_has_required_fields(fields, group=group):
            continue
        if not _response_hint_group_matches_query(fields, metadata, group=group, query=query):
            continue
        return group
    return None


def _answer_hints_from_fields(
    fields: dict[str, str],
    metadata: dict[str, Any],
    *,
    response_hints: dict[str, Any],
    query: str = "",
) -> list[str]:
    group = _matching_response_hint_group(fields, metadata, response_hints=response_hints, query=query)
    if group is not None:
        labels = _response_hint_string_list(group, "hint_labels")
        bits = [f"{label}：{fields[label]}" for label in labels if fields.get(label)]
        question = str(query or "").strip()
        question_label = str(group.get("question_from_query_label") or "").strip()
        answer_label = str(group.get("answer_label") or "").strip()
        if question and question_label and answer_label and bits:
            return [f"{question_label}：{question}", f"{answer_label}：{'；'.join(bits)}"]
        return bits
    return [f"{label}：{value}" for label, value in fields.items()]


def _find_numbered_marker(
    text: str,
    number: int,
    *,
    start: int,
    named_markers: dict[str, Any] | None = None,
) -> tuple[int, str]:
    markers = [
        f"{number}.",
        f"{number}、",
        f"{number}．",
        f"{number})",
        f"{number}）",
        f"({number})",
        f"（{number}）",
    ]
    named_marker = str((named_markers or {}).get(str(number)) or "").strip()
    if named_marker:
        markers.append(named_marker)
    best_index = -1
    best_marker = ""
    for marker in markers:
        index = text.find(marker, start)
        if index < 0:
            continue
        if best_index < 0 or index < best_index:
            best_index = index
            best_marker = marker
    return best_index, best_marker


def _extract_numbered_option_terms(
    text: str,
    *,
    max_terms: int = 4,
    named_markers: dict[str, Any] | None = None,
) -> list[str]:
    normalized = " ".join(str(text or "").split())
    named_marker_values = {
        str(value or "").strip() for value in (named_markers or {}).values() if str(value or "").strip()
    }
    terms: list[str] = []
    cursor = 0
    for number in range(1, max_terms + 1):
        marker_index, marker = _find_numbered_marker(normalized, number, start=cursor, named_markers=named_markers)
        if marker_index < 0:
            break
        start = marker_index + len(marker)
        while start < len(normalized) and (normalized[start].isspace() or normalized[start] in "，、,:："):
            start += 1
        end = start
        stop_chars = "（(：:；;。"
        if marker in named_marker_values:
            stop_chars += "，,"
        while end < len(normalized) and normalized[end] not in stop_chars:
            end += 1
        term = normalized[start:end].strip()
        if 2 <= len(term) <= 40:
            terms.append(term)
        cursor = end
    return terms


def _enumerated_answer_hints(content: str, *, query: str = "", response_hints: dict[str, Any]) -> list[str]:
    enumeration = _response_hint_dict(response_hints, "enumeration")
    if enumeration.get("enabled") is not True:
        return []
    text = str(content or "").strip()
    if not text:
        return []
    named_markers = _response_hint_dict(enumeration, "named_markers")
    first_marker_index, marker = _find_numbered_marker(" ".join(text.split()), 1, start=0, named_markers=named_markers)
    if first_marker_index < 0:
        return []
    prefix = " ".join(text.split())[:first_marker_index][-90:]
    query_text = str(query or "").strip()
    intro_terms = _response_hint_string_list(enumeration, "intro_terms")
    query_terms = _response_hint_string_list(enumeration, "query_terms")
    if not intro_terms:
        return []
    if not any(term in prefix for term in intro_terms) and not any(marker.startswith(term) for term in intro_terms):
        return []
    if query_text and query_terms and not any(term in query_text for term in query_terms):
        return []
    max_terms = max(1, int(enumeration.get("max_terms") or 4))
    terms = _extract_numbered_option_terms(text, max_terms=max_terms, named_markers=named_markers)
    if len(terms) < 2:
        return []
    separator = str(enumeration.get("term_separator") or ", ")
    terms_text = separator.join(terms)
    template = str(enumeration.get("message_template") or "Preserve these option names: {terms}")
    message = template.format(terms=terms_text)
    message_prefix = str(enumeration.get("prefix") or "").strip()
    return [f"{message_prefix}：{message}" if message_prefix else message]


def _content_starts_with_response_hint(content: str, *, response_hints: dict[str, Any]) -> bool:
    prefixes = list(_response_hint_string_list(response_hints, "existing_hint_prefixes"))
    answer_prefix = _response_hint_text(
        response_hints,
        "answer_prefix",
        default=_DEFAULT_RESPONSE_HINT_ANSWER_PREFIX,
    )
    if answer_prefix:
        prefixes.append(answer_prefix)
    normalized = str(content or "").lstrip()
    return any(normalized.startswith(prefix) for prefix in prefixes if prefix)


def _is_specific_intent_term(term: str) -> bool:
    text = str(term or "").strip()
    return len(text) >= _MIN_SPECIFIC_INTENT_CHARS


def _record_metadata_anchor_bonus(record: dict[str, Any], *, query: str) -> float:
    query_term = _normalize_match_term(query)
    if len(query_term) < 4:
        return 0.0
    best = 0.0
    has_query_region = _record_has_query_region_anchor(record, query_term=query_term)
    for metadata in _iter_record_metadata_layers(record):
        for key in _METADATA_ANCHOR_KEYS:
            for term in _metadata_terms(metadata.get(key)):
                candidate = _normalize_match_term(term)
                best = max(
                    best,
                    _metadata_term_anchor_bonus(
                        key=key,
                        candidate=candidate,
                        query_term=query_term,
                        has_query_region=has_query_region,
                    ),
                )
    if best > 0 and has_query_region:
        best += 0.02
    return best


def _metadata_term_anchor_bonus(
    *,
    key: str,
    candidate: str,
    query_term: str,
    has_query_region: bool,
) -> float:
    if len(candidate) < 4:
        return 0.0
    if candidate == query_term:
        return 0.14
    if candidate in query_term or query_term in candidate:
        return 0.1 if key in _FUZZY_METADATA_ANCHOR_KEYS else 0.08
    if key in _FUZZY_METADATA_ANCHOR_KEYS and _cjk_bigram_overlap_count(query_term, candidate) >= 2:
        return 0.1
    if key == "question" and has_query_region:
        overlap = _longest_common_substring_length(query_term, candidate)
        if overlap >= _MIN_REGIONAL_QUESTION_OVERLAP_CHARS:
            return 0.12
    return 0.0


def _record_plugin_ref(record: dict[str, Any], *, fallback_plugin_refs: tuple[str, ...] = ()) -> str:
    for metadata in _iter_record_metadata_layers(record):
        for key in ("chunk_python_plugin", "governance_python_plugin"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
    for fallback in fallback_plugin_refs or ():
        value = str(fallback or "").strip()
        if value:
            return value
    return ""


def _dify_external_reranker_enabled() -> bool:
    return bool(getattr(settings, "ENABLE_RERANKER", False)) and bool(
        getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_RERANKER_ENABLED", True)
    )


def _record_needs_final_rerank(record: dict[str, Any]) -> bool:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return not bool(record.get("reranker_provider") or metadata.get("reranker_provider"))


def _record_final_rerank_candidate_id(record: dict[str, Any], *, index: int, used: set[str]) -> str:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    candidates = [
        _record_source_identity_key(record),
        str(metadata.get("chunk_id") or "").strip(),
        str(metadata.get("document_id") or "").strip(),
        str(record.get("title") or "").strip(),
    ]
    base = next((item for item in candidates if item), "")
    if not base:
        payload = f"{record.get('title') or ''}\n{record.get('content') or ''}"
        base = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]
    candidate_id = base
    suffix = 1
    while candidate_id in used:
        suffix += 1
        candidate_id = f"{base}#{suffix}"
    used.add(candidate_id)
    return candidate_id or f"idx:{index}"


def _record_exact_primary_alias_bonus(record: dict[str, Any], *, query: str) -> float:
    query_term = _normalize_match_term(query)
    if len(query_term) < 3:
        return 0.0
    for metadata in _iter_record_metadata_layers(record):
        for term in _metadata_terms(metadata.get("primary_alias")):
            if _normalize_match_term(term) == query_term:
                return _EXACT_PRIMARY_ALIAS_MATCH_BONUS
    return 0.0


def _record_source_identity_key(record: dict[str, Any]) -> str:
    for metadata in _iter_record_metadata_layers(record):
        identity = metadata.get("_record_identity")
        if isinstance(identity, dict):
            key = str(identity.get("key") or "").strip()
            if key:
                return key

    for metadata in _iter_record_metadata_layers(record):
        source_record_id = ""
        for key in _SOURCE_RECORD_ID_KEYS:
            source_record_id = str(metadata.get(key) or "").strip()
            if source_record_id:
                break
        if not source_record_id:
            continue
        scope_parts: list[str] = []
        for key in _SOURCE_RECORD_SCOPE_KEYS:
            value = str(metadata.get(key) or "").strip()
            if value:
                scope_parts.append(f"{key}={value}")
        scope = "|".join(scope_parts)
        return f"{scope}|source_record_id={source_record_id}" if scope else f"source_record_id={source_record_id}"
    return ""
