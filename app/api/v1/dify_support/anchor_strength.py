"""Exact-anchor, composite-record, and question-anchor strength helpers for the Dify adapter.

Mechanically extracted from `app.api.v1.integrations_dify`; do not import that
module from here (see package docstring).
"""

from typing import Any

from app.api.v1.dify_support.common import (
    _QUESTION_ANCHOR_INTENT_GROUPS,
    _QUESTION_ANCHOR_SUBJECT_NOISE_TERMS,
    _iter_record_metadata_layers,
    _metadata_terms,
    _normalize_match_term,
)
from app.core.config import settings


def _record_section_type_values(record: dict[str, Any]) -> tuple[str, ...]:
    return _record_slot_field_values(record, "section_type")


def _record_slot_field_values(record: dict[str, Any], field: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    field_name = str(field or "").strip()
    if not field_name:
        return ()
    for metadata in _iter_record_metadata_layers(record):
        for value in _metadata_terms(metadata.get(field_name)):
            text = str(value or "").strip()
            normalized = _normalize_match_term(text)
            if not text or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            out.append(text)
    if field_name == "section_type":
        for metadata in _iter_record_metadata_layers(record):
            for value in _metadata_terms(metadata.get("section")):
                text = str(value or "").strip()
                normalized = _normalize_match_term(text)
                if not text or not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                out.append(text)
    return tuple(out)


def _record_matches_requested_slot(record: dict[str, Any], requested_slot_specs: tuple[tuple[str, str], ...]) -> bool:
    if not requested_slot_specs:
        return False
    for field, value in requested_slot_specs:
        requested_value = _normalize_match_term(value)
        if not field or not requested_value:
            continue
        record_values = {_normalize_match_term(item) for item in _record_slot_field_values(record, field)}
        record_values.discard("")
        if requested_value in record_values:
            return True
    return False


def _record_has_any_requested_slot_field(
    record: dict[str, Any],
    requested_slot_specs: tuple[tuple[str, str], ...],
) -> bool:
    fields = tuple(dict.fromkeys(field for field, _value in requested_slot_specs if str(field or "").strip()))
    return any(_record_slot_field_values(record, field) for field in fields)


def _record_is_full_answer_chunk(record: dict[str, Any]) -> bool:
    for metadata in _iter_record_metadata_layers(record):
        chunk_kind = str(metadata.get("chunk_kind") or "").strip().lower()
        answer_kind = str(metadata.get("answer_kind") or "").strip().lower()
        if answer_kind in {"full_record", "record_full"}:
            return True
        if chunk_kind in {"full_record", "record_full"}:
            return True
        if chunk_kind.endswith("_full") or chunk_kind.endswith("_record_full"):
            return True
    return False


def _record_is_composite_exact_anchor_answer(record: dict[str, Any]) -> bool:
    return any(
        bool(metadata.get("dify_composite_exact_anchor_slots"))
        for metadata in _iter_record_metadata_layers(record)
    )


def _composite_stitched_section_text(records: list[dict[str, Any]]) -> str:
    section_texts = [
        text
        for text in (_composite_section_text(record) for record in records or [])
        if text
    ]
    if not section_texts:
        return ""
    return "合并章节原文：\n" + "\n".join(section_texts)


def _composite_section_text(record: dict[str, Any]) -> str:
    content = str(record.get("content") or "").strip()
    if not content:
        return ""
    source_text = content.split("原始证据：", 1)[-1].strip() if "原始证据：" in content else content
    lines = [line.strip() for line in source_text.splitlines() if line.strip()]
    if not lines:
        return ""
    for index, line in enumerate(lines):
        if not line.startswith("章节："):
            continue
        label = line.split("：", 1)[1].strip() or line
        body = lines[index + 1 :]
        return "\n".join([label, *body]).strip()
    return "\n".join(lines).strip()


def _ordered_section_sibling_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sequence_key(record: dict[str, Any]) -> tuple[str, str, int, int, int, float]:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        source_record_id = str(metadata.get("source_record_id") or "").strip()
        section_type = str(metadata.get("section_type") or "").strip()
        return (
            source_record_id,
            section_type,
            _safe_int(metadata.get("source_chunk_index"), default=1_000_000),
            _safe_int(metadata.get("chunk_part_index"), default=1_000_000),
            _safe_int(metadata.get("chunk_index"), default=1_000_000),
            -float(record.get("score") or 0.0),
        )

    return sorted(records, key=sequence_key)


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _query_intent_terms(query: str, *, intent_terms: tuple[str, ...]) -> tuple[str, ...]:
    query_term = _normalize_match_term(query)
    if not query_term:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for term in intent_terms:
        normalized = _normalize_match_term(term)
        if normalized and normalized in query_term and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return tuple(out)


def _question_anchor_intent_groups(text: str) -> set[str]:
    normalized = _normalize_match_term(text)
    if not normalized:
        return set()
    groups: set[str] = set()
    for group, terms in _QUESTION_ANCHOR_INTENT_GROUPS:
        if any((term_text := _normalize_match_term(term)) and term_text in normalized for term in terms):
            groups.add(group)
    return groups


def _record_question_anchor_has_intent_conflict(
    record: dict[str, Any],
    *,
    query: str,
    anchor_fields: tuple[str, ...],
) -> bool:
    query_groups = _question_anchor_intent_groups(query)
    if not query_groups:
        return False
    matching_groups: set[str] = set()
    for metadata in _iter_record_metadata_layers(record):
        for field in anchor_fields:
            for anchor_value in _metadata_terms(metadata.get(field)):
                candidate_groups = _question_anchor_intent_groups(anchor_value)
                if candidate_groups:
                    matching_groups.update(candidate_groups)
    return bool(matching_groups and not query_groups.intersection(matching_groups))


def _question_anchor_subject_text(value: str, *, intent_terms: tuple[str, ...]) -> str:
    text = _normalize_match_term(value)
    if not text:
        return ""
    noise_terms = [
        *(_normalize_match_term(term) for term in intent_terms),
        *(_normalize_match_term(term) for term in _QUESTION_ANCHOR_SUBJECT_NOISE_TERMS),
    ]
    for term in sorted((term for term in noise_terms if term), key=len, reverse=True):
        text = text.replace(term, "")
    return text


def _dify_kg_bool(name: str, default: bool) -> bool:
    return bool(getattr(settings, name, default))


def _dify_kg_int(name: str, default: int, *, minimum: int = 0, maximum: int = 50) -> int:
    try:
        value = int(getattr(settings, name, default) or 0)
    except (TypeError, ValueError):
        value = int(default)
    return max(int(minimum), min(int(maximum), int(value)))


def _dify_kg_float(name: str, default: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        value = float(getattr(settings, name, default) or 0.0)
    except (TypeError, ValueError):
        value = float(default)
    return max(float(minimum), min(float(maximum), float(value)))
