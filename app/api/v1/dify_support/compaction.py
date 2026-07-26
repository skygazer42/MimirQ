"""Fast-response record compaction helpers for the Dify adapter.

Mechanically extracted from `app.api.v1.integrations_dify`; do not import that
module from here (see package docstring).
"""

import re
from typing import Any

from app.api.v1.dify_support.common import (
    _FAST_ANSWER_QUERY_STOP_TERMS,
    _URL_EVIDENCE_BONUS,
    _URL_EVIDENCE_BONUS_MAX,
    _URL_EVIDENCE_QUERY_MARKERS,
    _iter_record_metadata_layers,
    _metadata_terms,
    _normalize_match_term,
)
from app.api.v1.dify_support.scoring import (
    _clamp_hint_value,
    _field_line_parts,
    _iter_anchor_word_segments,
    _quoted_query_anchor_terms,
)
from app.core.config import settings


def _query_requests_url_evidence(query: str) -> bool:
    text = str(query or "").casefold()
    if not text:
        return False
    normalized = _normalize_match_term(text)
    return any(marker in text or _normalize_match_term(marker) in normalized for marker in _URL_EVIDENCE_QUERY_MARKERS)


def _record_url_evidence_bonus(record: dict[str, Any], *, query: str = "") -> float:
    if not _query_requests_url_evidence(query):
        return 0.0
    urls = 0
    for metadata in _iter_record_metadata_layers(record):
        urls += len(_metadata_terms(metadata.get("urls")))
    return min(_URL_EVIDENCE_BONUS_MAX, _URL_EVIDENCE_BONUS * urls)


def _dify_fast_candidate_top_k(top_k: int) -> int:
    configured = max(1, int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CANDIDATE_TOP_K_MAX", 3) or 3))
    return max(1, min(max(1, int(top_k or 1)), configured))


def _dify_fast_response_top_k(top_k: int) -> int:
    configured = max(1, int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX", 2) or 2))
    return max(1, min(max(1, int(top_k or 1)), configured))


def _dify_fast_content_max_chars() -> int:
    return max(200, min(10000, int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS", 1400) or 1400)))


def _dify_fast_total_content_max_chars() -> int:
    return max(
        200,
        min(
            50000,
            int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS", 2200) or 2200),
        ),
    )


def _structured_label_values_from_content(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_label = ""
    for segment in re.split(r"\s*\|\s*|\n+", str(content or "")):
        text = segment.strip()
        if not text:
            continue
        parts = _field_line_parts(text)
        if parts is None:
            if current_label and len(fields[current_label]) < _dify_fast_content_max_chars():
                fields[current_label] = f"{fields[current_label]}；{text}"
            continue
        label, value = parts
        current_label = label
        fields.setdefault(label, value)
    return fields


def _fast_answer_query_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        term = str(value or "").strip(" \t\r\n，。；;、：:？?！!（）()“”\"'《》「」")
        normalized = _normalize_match_term(term)
        if len(normalized) < 2 or normalized in seen or normalized in _FAST_ANSWER_QUERY_STOP_TERMS:
            return
        seen.add(normalized)
        terms.append(term)

    for anchor in _quoted_query_anchor_terms(query):
        add(anchor)
    for segment in _iter_anchor_word_segments(query):
        add(segment)
        for suffix in ("怎么申请", "如何申请", "怎么办理", "如何办理", "怎么查", "如何查", "是什么"):
            if segment.endswith(suffix):
                add(segment[: -len(suffix)])
                break
    terms.sort(key=lambda item: len(_normalize_match_term(item)), reverse=True)
    return tuple(terms)


def _fast_answer_snippet_segments(answer: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(answer or "")).strip()
    if not text:
        return []
    return [
        segment.strip()
        for segment in re.split(r"(?<=[。；;！？!?])\s*|\n+|(?<!\d)(?=[1-9][.)）])", text)
        if segment.strip()
    ]


def _compact_fast_answer_value(answer: str, *, query: str, limit: int) -> str:
    text = str(answer or "").strip()
    if len(text) <= limit:
        return text
    normalized_terms = tuple(
        _normalize_match_term(term)
        for term in _fast_answer_query_terms(query)
        if _normalize_match_term(term)
    )
    if not normalized_terms:
        return _clamp_hint_value(text, limit=limit)
    scored: list[tuple[int, int, str]] = []
    for index, segment in enumerate(_fast_answer_snippet_segments(text)):
        normalized_segment = _normalize_match_term(segment)
        matched = {term for term in normalized_terms if term and term in normalized_segment}
        if not matched:
            continue
        scored.append((index, sum(len(term) for term in matched), segment))
    if not scored:
        return _clamp_hint_value(text, limit=limit)
    target_limit = max(240, min(limit, 700))
    selected_indices = {
        index
        for index, _score, _segment in sorted(scored, key=lambda item: (-item[1], item[0]))[:6]
    }
    snippet = "".join(segment for index, _score, segment in scored if index in selected_indices).strip()
    if not snippet:
        return _clamp_hint_value(text, limit=limit)
    return _clamp_hint_value(snippet, limit=target_limit)
