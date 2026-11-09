"""Dify record ranking rules and operations."""

import time
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.reranker.factory import get_reranker
from app.rag.reranker.types import RerankCandidate, RerankResult
from app.rag.retrieval.planner import retrieval_policy_query_terms
from app.rag.retrieval.plugin_policy import (
    record_retrieval_policy_anchor_binding_scores,
    record_retrieval_policy_bonus,
    records_retrieval_policy_diagnostics,
)
from app.services.dify_integration import answer_hints, policy_helpers, query_policy
from app.services.dify_integration.anchor_strength import (
    _composite_stitched_section_text as _composite_stitched_section_text,
)
from app.services.dify_integration.anchor_strength import (
    _ordered_section_sibling_records as _ordered_section_sibling_records,
)
from app.services.dify_integration.anchor_strength import _query_intent_terms as _query_intent_terms
from app.services.dify_integration.anchor_strength import _question_anchor_subject_text as _question_anchor_subject_text
from app.services.dify_integration.anchor_strength import (
    _record_is_composite_exact_anchor_answer as _record_is_composite_exact_anchor_answer,
)
from app.services.dify_integration.anchor_strength import _record_is_full_answer_chunk as _record_is_full_answer_chunk
from app.services.dify_integration.anchor_strength import (
    _record_matches_requested_slot as _record_matches_requested_slot,
)
from app.services.dify_integration.anchor_strength import (
    _record_question_anchor_has_intent_conflict as _record_question_anchor_has_intent_conflict,
)
from app.services.dify_integration.anchor_strength import _record_slot_field_values as _record_slot_field_values
from app.services.dify_integration.common import (
    _ANCHOR_ONLY_QA_RECORD_PENALTY,
    _ANSWERFUL_RECORD_BONUS,
    _EXACT_QUERY_ANCHOR_FIELDS,
    _INTENT_MATCH_BONUS,
    _INTENT_MATCH_BONUS_MAX,
    _MIN_QUERY_INTENT_SUBJECT_OVERLAP_CHARS,
    _QUESTION_ANCHOR_BIGRAM_MIN_OVERLAP,
    _QUESTION_ANCHOR_BIGRAM_MIN_RATIO,
    _QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH,
    _QUESTION_INTENT_MATCH_BONUS,
    _RETRIEVAL_INTENT_KEYS,
)
from app.services.dify_integration.common import _MAX_QA_HINT_VALUE_CHARS as _MAX_QA_HINT_VALUE_CHARS
from app.services.dify_integration.common import _clamp_score as _clamp_score
from app.services.dify_integration.common import _first_nonempty_str as _first_nonempty_str
from app.services.dify_integration.common import _iter_record_metadata_layers as _iter_record_metadata_layers
from app.services.dify_integration.common import _metadata_terms as _metadata_terms
from app.services.dify_integration.common import _normalize_match_term as _normalize_match_term
from app.services.dify_integration.compaction import _record_url_evidence_bonus as _record_url_evidence_bonus
from app.services.dify_integration.policy_helpers import (
    question_anchor_generic_subject_terms_for_policy_refs as _question_anchor_generic_subject_terms_for_policy_refs,
)
from app.services.dify_integration.policy_helpers import record_plugin_ref as _record_plugin_ref
from app.services.dify_integration.policy_helpers import response_hints_for_record as _response_hints_for_record
from app.services.dify_integration.query_terms import (
    _query_has_specific_service_anchor_candidate as _query_has_specific_service_anchor_candidate,
)
from app.services.dify_integration.records import _record_dedupe_key as _record_dedupe_key
from app.services.dify_integration.scoring import _cjk_bigram_overlap_count as _cjk_bigram_overlap_count
from app.services.dify_integration.scoring import _cjk_bigram_overlap_ratio as _cjk_bigram_overlap_ratio
from app.services.dify_integration.scoring import (
    _content_starts_with_response_hint as _content_starts_with_response_hint,
)
from app.services.dify_integration.scoring import _dify_external_reranker_enabled as _dify_external_reranker_enabled
from app.services.dify_integration.scoring import _is_specific_intent_term as _is_specific_intent_term
from app.services.dify_integration.scoring import _longest_common_substring_length as _longest_common_substring_length
from app.services.dify_integration.scoring import _matching_response_hint_group as _matching_response_hint_group
from app.services.dify_integration.scoring import _near_question_anchor_match as _near_question_anchor_match
from app.services.dify_integration.scoring import (
    _query_has_quoted_anchor_candidate as _query_has_quoted_anchor_candidate,
)
from app.services.dify_integration.scoring import _question_marker_overlap_bonus as _question_marker_overlap_bonus
from app.services.dify_integration.scoring import _quoted_query_anchor_terms as _quoted_query_anchor_terms
from app.services.dify_integration.scoring import _record_exact_primary_alias_bonus as _record_exact_primary_alias_bonus
from app.services.dify_integration.scoring import _record_final_rerank_candidate_id as _record_final_rerank_candidate_id
from app.services.dify_integration.scoring import _record_metadata_anchor_bonus as _record_metadata_anchor_bonus
from app.services.dify_integration.scoring import _record_needs_final_rerank as _record_needs_final_rerank
from app.services.dify_integration.scoring import _record_policy_slot_coverage_text as _record_policy_slot_coverage_text
from app.services.dify_integration.scoring import _response_hint_string_list as _response_hint_string_list
from app.services.dify_integration.scoring import _structured_fields_from_content as _structured_fields_from_content
from app.services.rag_runtime_limiter import run_blocking_retrieval_call

logger = get_logger(__name__)


def _record_matches_quoted_query_anchor(record: dict[str, Any], *, query: str) -> bool:
    return _record_matches_quoted_query_anchor_for_policy(record, query=query)


def _record_matches_quoted_query_anchor_for_policy(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    anchors = _quoted_query_anchor_terms(query)
    if not anchors:
        return True
    values: list[str] = [record['content'], record['title']]
    anchor_fields = query_policy._exact_query_anchor_fields_for_policy_refs(policy_plugin_refs)
    for metadata in _iter_record_metadata_layers(record):
        for field in anchor_fields:
            values.extend(_metadata_terms(metadata.get(field)))
    normalized_values = [_normalize_match_term(value) for value in values if value]
    return any(anchor in value or value in anchor for anchor in anchors for value in normalized_values if value)


def _record_covers_requested_policy_slots(
    record: dict[str, Any],
    requested_slot_specs: tuple[tuple[str, str], ...],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    requested_norms = tuple(
        dict.fromkeys(
            (field, _normalize_match_term(value))
            for field, value in requested_slot_specs
            if field and _normalize_match_term(value)
        )
    )
    if not requested_norms:
        return True
    record_text = _record_policy_slot_coverage_text(record)
    for field, normalized_value in requested_norms:
        value = next(
            (
                raw_value
                for raw_field, raw_value in requested_slot_specs
                if raw_field == field and _normalize_match_term(raw_value) == normalized_value
            ),
            "",
        )
        if _record_matches_requested_slot(record, ((field, value),)):
            continue
        terms = query_policy._policy_slot_query_terms(field=field, value=value, policy_plugin_refs=policy_plugin_refs)
        if not any((normalized := _normalize_match_term(term)) and normalized in record_text for term in terms):
            return False
    return True


def _filter_records_by_mixed_intent_subject_anchor(
    records: list[dict[str, Any]],
    *,
    subquery: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    subject_anchor = query_policy._mixed_intent_subject_anchor(subquery, policy_plugin_refs=policy_plugin_refs)
    normalized_anchor = _normalize_match_term(subject_anchor)
    if len(normalized_anchor) < 3:
        return records
    anchored: list[dict[str, Any]] = []
    for record in records or []:
        for metadata in _iter_record_metadata_layers(record):
            values: list[str] = []
            for key in query_policy._exact_query_anchor_fields_for_policy_refs(policy_plugin_refs):
                values.extend(_metadata_terms(metadata.get(key)))
            if any(normalized_anchor in _normalize_match_term(value) for value in values):
                anchored.append(record)
                break
    return anchored or records


def _record_retrieval_intents(
    record: dict[str, Any],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    metadata_layers = _iter_record_metadata_layers(record)
    for metadata in metadata_layers:
        for key in _RETRIEVAL_INTENT_KEYS:
            for term in _metadata_terms(metadata.get(key)):
                if term in seen:
                    continue
                seen.add(term)
                out.append(term)
    plugin_ref = _record_plugin_ref(record, fallback_plugin_refs=policy_plugin_refs)
    policy = policy_helpers.retrieval_policy_for_plugin_ref(plugin_ref)
    for term in retrieval_policy_query_terms(policy, metadata_layers=metadata_layers):
        if term in seen:
            continue
        seen.add(term)
        out.append(term)
    return out


def _record_intent_bonus(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    query_text = query.casefold()
    if not query_text:
        return 0.0
    matches = 0
    for term in _record_retrieval_intents(record, policy_plugin_refs=policy_plugin_refs):
        if not _is_specific_intent_term(term):
            continue
        folded = term.casefold()
        if folded and (folded in query_text or query_text in folded):
            matches += 1
    return min(_INTENT_MATCH_BONUS * matches, _INTENT_MATCH_BONUS_MAX)


def _record_mixed_intent_subquery_bonus(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    if not query_policy._query_has_mixed_intent_for_policy(query, policy_plugin_refs=policy_plugin_refs):
        return 0.0
    query_term = _normalize_match_term(query)
    best = 0.0
    for metadata in _iter_record_metadata_layers(record):
        subquery = _first_nonempty_str(metadata.get("dify_mixed_intent_subquery"))
        if not subquery:
            continue
        subquery_term = _normalize_match_term(subquery)
        if not subquery_term or subquery_term == query_term:
            continue
        question_bonus = _record_question_intent_bonus(
            record,
            query=subquery,
            policy_plugin_refs=policy_plugin_refs,
        )
        subquery_bonus = (
            0.1
            + _record_metadata_anchor_bonus(record, query=subquery)
            + _record_intent_bonus(record, query=subquery, policy_plugin_refs=policy_plugin_refs)
            + question_bonus
        )
        subquery_cap = 1.4 if question_bonus > 0 else 0.24
        best = max(
            best,
            min(subquery_bonus, subquery_cap),
        )
    return min(best, 1.4)


def _records_retrieval_policy_diagnostics(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    return records_retrieval_policy_diagnostics(
        records,
        query=query,
        plugin_ref_for_record=lambda record: _record_plugin_ref(record, fallback_plugin_refs=policy_plugin_refs),
        metadata_layers_for_record=_iter_record_metadata_layers,
        policy_resolver=policy_helpers.retrieval_policy_for_plugin_ref,
    )


def _record_rank_score(record: dict[str, Any], *, query: str, policy_plugin_refs: tuple[str, ...] = ()) -> float:
    return (
        float(record.get("score") or 0.0)
        + _record_metadata_anchor_bonus(record, query=query)
        + _record_intent_bonus(record, query=query, policy_plugin_refs=policy_plugin_refs)
        + _record_exact_primary_alias_bonus(record, query=query)
        + _record_url_evidence_bonus(record, query=query)
        + _record_question_intent_bonus(record, query=query, policy_plugin_refs=policy_plugin_refs)
        + _record_answerfulness_score(record, policy_plugin_refs=policy_plugin_refs)
        + _record_mixed_intent_subquery_bonus(record, query=query, policy_plugin_refs=policy_plugin_refs)
        + record_retrieval_policy_bonus(
            record,
            query=query,
            plugin_ref_for_record=lambda candidate: _record_plugin_ref(
                candidate, fallback_plugin_refs=policy_plugin_refs
            ),
            metadata_layers_for_record=_iter_record_metadata_layers,
            policy_resolver=policy_helpers.retrieval_policy_for_plugin_ref,
        )
    )


def _strong_question_anchor_records(
    records: list[dict[str, Any]], *, query: str, policy_plugin_refs: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    return [
        record
        for record in records or []
        if _record_has_strong_question_anchor(record, query=query, policy_plugin_refs=policy_plugin_refs)
        and _record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs)
    ]


def _sort_records_for_query(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> None:
    anchor_binding_scores = record_retrieval_policy_anchor_binding_scores(
        records,
        query=query,
        plugin_ref_for_record=lambda item: _record_plugin_ref(item, fallback_plugin_refs=policy_plugin_refs),
        metadata_layers_for_record=_iter_record_metadata_layers,
        policy_resolver=policy_helpers.retrieval_policy_for_plugin_ref,
    )
    exact_anchor_scores = _record_exact_anchor_protection_scores(
        records,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    records.sort(
        key=lambda item: (
            _record_rank_score(item, query=query, policy_plugin_refs=policy_plugin_refs)
            + anchor_binding_scores.get(id(item), 0.0)
            + exact_anchor_scores.get(id(item), 0.0)
        ),
        reverse=True,
    )


def _record_exact_anchor_protection_scores(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[int, float]:
    if not records:
        return {}
    if _strong_question_anchor_records(records, query=query, policy_plugin_refs=policy_plugin_refs):
        return {}
    exact_anchor_records = [
        record
        for record in records
        if _record_exact_query_anchor_terms(record, query=query, policy_plugin_refs=policy_plugin_refs)
        and _record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs)
    ]
    if not exact_anchor_records:
        return {}
    return {id(record): 1.2 for record in exact_anchor_records}


def _record_final_rerank_text(
    record: dict[str, Any],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> str:
    parts: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        text = _first_nonempty_str(value)
        if not text or text in seen:
            return
        seen.add(text)
        parts.append(text)

    add(record.get("title"))
    add(record.get("content"))
    metadata_fields = (
        *_EXACT_QUERY_ANCHOR_FIELDS,
        "answer",
        "summary",
        *query_policy._anchor_binding_fields_for_policy_refs(policy_plugin_refs),
    )
    for metadata in _iter_record_metadata_layers(record):
        for field in metadata_fields:
            for value in _metadata_terms(metadata.get(field)):
                add(value)
    return "\n".join(parts)


async def _final_rerank_records_for_query(
    records: list[dict[str, Any]],
    *,
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    provider = _final_rerank_provider(records)
    if provider is None:
        return records
    candidates, id_to_record, candidate_count = _final_rerank_candidates(
        records,
        top_k=top_k,
        policy_plugin_refs=policy_plugin_refs,
    )

    if len(candidates) <= 1:
        return records

    try:
        reranker = get_reranker(provider)
        start = time.perf_counter()
        result = await run_blocking_retrieval_call(
            reranker.rerank,
            query,
            candidates,
            top_n=len(candidates),
            tenant_id=None,
            query_type=None,
        )
        elapsed_sec = result.elapsed_sec if result.elapsed_sec is not None else time.perf_counter() - start
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dify external final reranker failed (%s): %s", provider, exc)
        return records

    ordered = _ordered_final_rerank_records(
        candidates,
        id_to_record=id_to_record,
        provider=provider,
        result=result,
        elapsed_sec=elapsed_sec,
    )
    if not ordered:
        return records
    reranked_records = ordered + records[candidate_count:]
    _sort_records_for_query(reranked_records, query=query, policy_plugin_refs=policy_plugin_refs)
    return reranked_records


def _final_rerank_provider(records: list[dict[str, Any]]) -> str | None:
    if len(records or []) <= 1:
        return None
    if not any(_record_needs_final_rerank(record) for record in records):
        return None
    if not _dify_external_reranker_enabled():
        return None
    provider = (settings.RERANKER_PROVIDER or "llm").strip().lower()
    return None if provider in {"none", "off", "false", "0"} else provider


def _final_rerank_candidate_count(record_count: int, top_k: int) -> int:
    try:
        configured_top_n = int(settings.RERANKER_TOP_N or top_k)
    except (TypeError, ValueError):
        configured_top_n = int(top_k or 1)
    return min(record_count, max(1, int(top_k or 1), configured_top_n))


def _final_rerank_candidates(
    records: list[dict[str, Any]],
    *,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[list[RerankCandidate], dict[str, dict[str, Any]], int]:
    candidate_count = _final_rerank_candidate_count(len(records), top_k)
    used_ids: set[str] = set()
    id_to_record: dict[str, dict[str, Any]] = {}
    candidates: list[RerankCandidate] = []
    for index, record in enumerate(records[:candidate_count]):
        text = _record_final_rerank_text(record, policy_plugin_refs=policy_plugin_refs)
        if not text:
            continue
        candidate_id = _record_final_rerank_candidate_id(record, index=index, used=used_ids)
        metadata = dict(record.get("metadata") if isinstance(record.get("metadata"), dict) else {})
        metadata["score"] = float(record.get("score") or 0.0)
        metadata["title"] = record['title']
        candidates.append(RerankCandidate(id=candidate_id, text=text, metadata=metadata))
        id_to_record[candidate_id] = record
    return candidates, id_to_record, candidate_count


def _ordered_final_rerank_records(
    candidates: list[RerankCandidate],
    *,
    id_to_record: dict[str, dict[str, Any]],
    provider: str,
    result: RerankResult,
    elapsed_sec: float,
) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    consumed: set[str] = set()
    rerank_provider = result.provider or provider
    for candidate_id in result.ordered_ids:
        record = id_to_record.get(str(candidate_id))
        if record is None or candidate_id in consumed:
            continue
        consumed.add(str(candidate_id))
        ordered.append(
            _final_rerank_record_with_metadata(
                record,
                candidate_id=str(candidate_id),
                rerank_provider=rerank_provider,
                result=result,
                elapsed_sec=elapsed_sec,
            )
        )
    for candidate in candidates:
        if candidate.id in consumed:
            continue
        record = id_to_record.get(candidate.id)
        if record is not None:
            ordered.append(record)
    return ordered


def _final_rerank_record_with_metadata(
    record: dict[str, Any],
    *,
    candidate_id: str,
    rerank_provider: str,
    result: RerankResult,
    elapsed_sec: float,
) -> dict[str, Any]:
    next_record = dict(record)
    metadata = dict(next_record.get("metadata") if isinstance(next_record.get("metadata"), dict) else {})
    metadata["reranker_provider"] = rerank_provider
    metadata["rerank_elapsed_sec"] = round(float(elapsed_sec or 0.0), 3)
    metadata["rerank_model_used"] = result.model_used
    metadata["dify_final_rerank"] = True
    if candidate_id in result.score_map:
        rerank_score = _clamp_score(result.score_map[candidate_id])
        metadata["rerank_score"] = rerank_score
        next_record["score"] = rerank_score
    next_record["metadata"] = metadata
    return next_record


def _record_exact_query_anchor_terms(
    record: dict[str, Any],
    *,
    query: str,
    anchor_fields: tuple[str, ...] | None = None,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    query_term = _normalize_match_term(query)
    if len(query_term) < 4:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    effective_anchor_fields = anchor_fields or query_policy._exact_query_anchor_fields_for_policy_refs(
        policy_plugin_refs
    )
    for metadata in _iter_record_metadata_layers(record):
        for field in effective_anchor_fields:
            for term in _metadata_terms(metadata.get(field)):
                normalized = _normalize_match_term(term)
                if len(normalized) < 4 or normalized in seen:
                    continue
                if normalized in query_term:
                    seen.add(normalized)
                    out.append(normalized)
    return tuple(out)


def _record_content_is_answerful(
    record: dict[str, Any],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    content = record['content'].strip()
    return bool(content) and _record_has_answer_evidence(
        record,
        content=content,
        policy_plugin_refs=policy_plugin_refs,
    )


def _record_answerfulness_score(record: dict[str, Any], *, policy_plugin_refs: tuple[str, ...] = ()) -> float:
    answerful_record_bonus = _ANSWERFUL_RECORD_BONUS
    anchor_only_qa_record_penalty = _ANCHOR_ONLY_QA_RECORD_PENALTY
    content = record['content'].strip()
    if not content:
        return 0.0
    if _record_has_answer_evidence(record, content=content, policy_plugin_refs=policy_plugin_refs):
        return answerful_record_bonus
    if _record_is_anchor_only_qa(record, content=content, policy_plugin_refs=policy_plugin_refs):
        return -anchor_only_qa_record_penalty
    return 0.0


def _records_have_exact_anchor_full_answer(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    requested_slots = query_policy._requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
    quoted_anchor_query = _query_has_quoted_anchor_candidate(query)
    for record in records or []:
        if not _record_exact_query_anchor_terms(record, query=query, policy_plugin_refs=policy_plugin_refs):
            continue
        if _record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs):
            if requested_slots and not (
                quoted_anchor_query
                or _record_is_full_answer_chunk(record)
                or _record_is_composite_exact_anchor_answer(record)
            ):
                continue
            return True
    return False


def _composite_record_for_exact_anchor_slots(
    records: list[dict[str, Any]],
    *,
    query: str,
    requested_slot_specs: tuple[tuple[str, str], ...],
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    groups = _exact_anchor_slot_record_groups(
        records,
        query=query,
        requested_slot_specs=requested_slot_specs,
        policy_plugin_refs=policy_plugin_refs,
    )
    best_records, best_covered = _best_exact_anchor_slot_group_records(
        groups,
        requested_slot_specs=requested_slot_specs,
    )
    if len(best_records) < 2:
        return None

    first = best_records[0]
    metadata = dict(first.get("metadata") if isinstance(first.get("metadata"), dict) else {})
    metadata.update(
        _composite_exact_anchor_slot_metadata(
            best_records,
            requested_slot_specs=requested_slot_specs,
            best_covered=best_covered,
        )
    )
    score = min(1.0, max((float(record.get("score") or 0.0) for record in best_records), default=0.0) + 0.01)
    return {
        "content": _composite_exact_anchor_slot_content(best_records),
        "score": score,
        "title": str(first.get("title") or "composite-anchor-evidence"),
        "metadata": metadata,
    }


def _exact_anchor_slot_record_groups(
    records: list[dict[str, Any]],
    *,
    query: str,
    requested_slot_specs: tuple[tuple[str, str], ...],
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if not _record_matches_requested_slot(record, requested_slot_specs):
            continue
        for anchor in _record_exact_query_anchor_terms(
            record,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        ):
            groups.setdefault(anchor, []).append(record)
    return groups


def _requested_slot_norms(
    requested_slot_specs: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (field, _normalize_match_term(value))
        for field, value in requested_slot_specs
        if field and _normalize_match_term(value)
    )


def _best_exact_anchor_slot_group_records(
    groups: dict[str, list[dict[str, Any]]],
    *,
    requested_slot_specs: tuple[tuple[str, str], ...],
) -> tuple[list[dict[str, Any]], set[tuple[str, str]]]:
    best_records: list[dict[str, Any]] = []
    best_covered: set[tuple[str, str]] = set()
    for candidates in groups.values():
        selected, covered = _selected_exact_anchor_slot_group_records(
            candidates,
            requested_norms=_requested_slot_norms(requested_slot_specs),
        )
        if len(covered) > len(best_covered):
            best_records = selected
            best_covered = covered
    return best_records, best_covered


def _selected_exact_anchor_slot_group_records(
    candidates: list[dict[str, Any]],
    *,
    requested_norms: tuple[tuple[str, str], ...],
) -> tuple[list[dict[str, Any]], set[tuple[str, str]]]:
    selected: list[dict[str, Any]] = []
    covered: set[tuple[str, str]] = set()
    seen_records: set[int] = set()
    for requested_field, requested_norm in requested_norms:
        requested_key = (requested_field, requested_norm)
        if not requested_norm or requested_key in covered:
            continue
        matching_records = [
            record
            for record in candidates
            if requested_norm
            in {_normalize_match_term(value) for value in _record_slot_field_values(record, requested_field)}
            and id(record) not in seen_records
        ]
        if not matching_records:
            continue
        for record in _ordered_section_sibling_records(matching_records):
            if id(record) in seen_records:
                continue
            selected.append(record)
            seen_records.add(id(record))
        covered.add(requested_key)
    return selected, covered


def _composite_exact_anchor_slot_metadata(
    records: list[dict[str, Any]],
    *,
    requested_slot_specs: tuple[tuple[str, str], ...],
    best_covered: set[tuple[str, str]],
) -> dict[str, Any]:
    source_chunk_ids: list[str] = []
    source_document_ids: list[str] = []
    for record in records:
        record_metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        chunk_id = _first_nonempty_str(record_metadata.get("chunk_id"))
        document_id = _first_nonempty_str(record_metadata.get("document_id"))
        if chunk_id and chunk_id not in source_chunk_ids:
            source_chunk_ids.append(chunk_id)
        if document_id and document_id not in source_document_ids:
            source_document_ids.append(document_id)
    covered_specs = [
        {"metadata": field, "value": value}
        for field, value in requested_slot_specs
        if (field, _normalize_match_term(value)) in best_covered
    ]
    metadata = {
        "dify_composite_exact_anchor_slots": True,
        "dify_composite_slot_specs": covered_specs,
        "dify_composite_source_chunk_ids": source_chunk_ids,
        "dify_composite_source_document_ids": source_document_ids,
    }
    section_types = [spec["value"] for spec in covered_specs if spec["metadata"] == "section_type"]
    if section_types:
        metadata["section_type"] = "composite"
        metadata["dify_composite_section_types"] = section_types
    return metadata


def _composite_exact_anchor_slot_content(records: list[dict[str, Any]]) -> str:
    content_parts = [
        part
        for part in (
            _composite_stitched_section_text(records),
            "\n\n".join(record['content'].strip() for record in records if record.get("content")),
        )
        if part
    ]
    return "\n\n".join(content_parts)


def _record_has_answer_evidence(
    record: dict[str, Any],
    *,
    content: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    response_hints = _response_hints_for_record(record, policy_plugin_refs=policy_plugin_refs)
    fields = _structured_fields_from_content(content, response_hints=response_hints)
    answer_labels = _response_hint_string_list(response_hints, "answer_labels")
    if answer_labels and any(fields.get(label) for label in answer_labels):
        return True
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    if _matching_response_hint_group(fields, metadata, response_hints=response_hints) is not None:
        return True
    answer_keywords = _response_hint_string_list(response_hints, "answer_keywords")
    if _content_starts_with_response_hint(content, response_hints=response_hints) and (
        not answer_keywords or any(keyword in content[:_MAX_QA_HINT_VALUE_CHARS] for keyword in answer_keywords)
    ):
        return True

    raw_metadata = record.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    if answer_hints._metadata_answer_highlights(metadata, response_hints=response_hints):
        return True
    return False


def _record_is_anchor_only_qa(
    record: dict[str, Any],
    *,
    content: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    response_hints = _response_hints_for_record(record, policy_plugin_refs=policy_plugin_refs)
    normalized = content.strip()
    answer_labels = _response_hint_string_list(response_hints, "answer_labels")
    answer_keywords = _response_hint_string_list(response_hints, "answer_keywords")
    if any(label and label in normalized for label in (*answer_labels, *answer_keywords)):
        return False
    chunk_kinds = set(_response_hint_string_list(response_hints, "anchor_only_chunk_kinds"))
    if not chunk_kinds:
        return False
    is_qa_record = any(
        _first_nonempty_str(metadata.get("chunk_kind")) in chunk_kinds
        for metadata in _iter_record_metadata_layers(record)
    )
    if not is_qa_record:
        return False
    markers = _response_hint_string_list(response_hints, "anchor_only_markers")
    return any(marker and marker in normalized for marker in markers)


def _record_question_intent_terms(
    record: dict[str, Any], *, policy_plugin_refs: tuple[str, ...] = ()
) -> tuple[str, ...]:
    plugin_ref = _record_plugin_ref(record, fallback_plugin_refs=policy_plugin_refs)
    if not plugin_ref:
        return ()
    policy = policy_helpers.retrieval_policy_for_plugin_ref(plugin_ref)
    return _response_hint_string_list(policy, "question_intent_terms")


def _record_question_anchor_bonus_value(
    record: dict[str, Any],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    plugin_ref = _record_plugin_ref(record, fallback_plugin_refs=policy_plugin_refs)
    if not plugin_ref:
        return _QUESTION_INTENT_MATCH_BONUS
    policy = policy_helpers.retrieval_policy_for_plugin_ref(plugin_ref)
    try:
        value = float(policy.get("question_anchor_bonus"))
    except (TypeError, ValueError):
        return _QUESTION_INTENT_MATCH_BONUS
    return max(0.0, min(2.0, value))


def _record_question_anchor_lacks_specific_query_subject(
    record: dict[str, Any],
    *,
    query: str,
    anchor_fields: tuple[str, ...],
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    if not query_policy._requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs):
        return False
    generic_terms = {
        _normalize_match_term(term)
        for term in _question_anchor_generic_subject_terms_for_policy_refs(policy_plugin_refs)
    }
    query_subject_terms: list[str] = []
    seen_terms: set[str] = set()
    for term in query_policy._metadata_anchor_title_query_terms(query, policy_plugin_refs=policy_plugin_refs):
        normalized = _normalize_match_term(term)
        if len(normalized) < 4 or normalized in seen_terms or normalized in generic_terms:
            continue
        seen_terms.add(normalized)
        query_subject_terms.append(normalized)
    if not query_subject_terms:
        return False

    record_subject_parts: list[str] = []
    for metadata in _iter_record_metadata_layers(record):
        for field in anchor_fields:
            record_subject_parts.extend(_normalize_match_term(value) for value in _metadata_terms(metadata.get(field)))
    record_subject = "\n".join(part for part in record_subject_parts if part)
    if not record_subject:
        return False
    return not any(term in record_subject for term in query_subject_terms)


def _record_question_intent_bonus(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    primary_anchor_fields = ("question", "primary_alias")
    if (
        _record_question_anchor_strength(
            record,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
            anchor_fields=primary_anchor_fields,
        )
        >= _QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH
        and not _record_question_anchor_has_intent_conflict(
            record,
            query=query,
            anchor_fields=primary_anchor_fields,
        )
        and not _record_question_anchor_lacks_specific_query_subject(
            record,
            query=query,
            anchor_fields=primary_anchor_fields,
            policy_plugin_refs=policy_plugin_refs,
        )
    ):
        return _record_question_anchor_bonus_value(record, policy_plugin_refs=policy_plugin_refs)
    if query_policy._requested_policy_slot_specs_for_query(
        query, policy_plugin_refs=policy_plugin_refs
    ) or _query_intent_terms(
        query,
        intent_terms=_record_question_intent_terms(record, policy_plugin_refs=policy_plugin_refs),
    ):
        return 0.0
    alias_anchor_fields = ("aliases",)
    if (
        _record_question_anchor_strength(
            record,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
            anchor_fields=alias_anchor_fields,
        )
        >= _QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH
        and not _record_question_anchor_has_intent_conflict(
            record,
            query=query,
            anchor_fields=alias_anchor_fields,
        )
        and not _record_question_anchor_lacks_specific_query_subject(
            record,
            query=query,
            anchor_fields=alias_anchor_fields,
            policy_plugin_refs=policy_plugin_refs,
        )
    ):
        return _record_question_anchor_bonus_value(record, policy_plugin_refs=policy_plugin_refs)
    return 0.0


def _record_question_anchor_strength(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
    anchor_fields: tuple[str, ...] = ("question", "primary_alias", "aliases"),
) -> float:
    query_term = _normalize_match_term(query)
    if len(query_term) < 4:
        return 0.0
    intent_terms = _query_intent_terms(
        query,
        intent_terms=_record_question_intent_terms(record, policy_plugin_refs=policy_plugin_refs),
    )
    best = 0.0
    for metadata in _iter_record_metadata_layers(record):
        for field in anchor_fields:
            for anchor_value in _metadata_terms(metadata.get(field)):
                best = max(
                    best,
                    _question_anchor_candidate_strength(
                        query_term,
                        anchor_value,
                        field=field,
                        intent_terms=intent_terms,
                    ),
                )
    return best


def _question_anchor_candidate_strength(
    query_term: str,
    anchor_value: Any,
    *,
    field: str,
    intent_terms: tuple[str, ...],
) -> float:
    candidate = _normalize_match_term(anchor_value)
    if len(candidate) < 3:
        return 0.0
    if candidate == query_term or candidate in query_term or query_term in candidate:
        return 1.0
    if _near_question_anchor_match(query_term, candidate):
        return 0.9
    lcs = _longest_common_substring_length(query_term, candidate)
    lcs_ratio = lcs / max(1, min(len(query_term), len(candidate)))
    if field == "aliases" and lcs >= 6 and lcs_ratio >= 0.68:
        return 0.86
    overlap_count = _cjk_bigram_overlap_count(query_term, candidate)
    overlap_ratio = _cjk_bigram_overlap_ratio(query_term, candidate)
    if overlap_count >= _QUESTION_ANCHOR_BIGRAM_MIN_OVERLAP and overlap_ratio >= _QUESTION_ANCHOR_BIGRAM_MIN_RATIO:
        marker_bonus = _question_marker_overlap_bonus(query_term, candidate)
        strength = 0.66 + min(0.09, overlap_ratio * 0.09) + min(0.07, lcs_ratio * 0.07) + marker_bonus
        if overlap_count >= 8 and overlap_ratio >= 0.7:
            strength = max(strength, 0.82)
        return min(0.96, strength)
    if intent_terms and any(term in candidate for term in intent_terms):
        overlap = _longest_common_substring_length(
            _question_anchor_subject_text(query_term, intent_terms=intent_terms),
            _question_anchor_subject_text(candidate, intent_terms=intent_terms),
        )
        if overlap >= _MIN_QUERY_INTENT_SUBJECT_OVERLAP_CHARS:
            return 0.8
    return 0.0


def _record_has_strong_question_anchor(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    return bool(
        _record_question_anchor_strength(
            record,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        >= _QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH
        and not _record_question_anchor_has_intent_conflict(
            record,
            query=query,
            anchor_fields=("question", "primary_alias"),
        )
    )


def _records_can_skip_kg_on_demand(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    if query_policy._query_prefers_service_anchor(query, policy_plugin_refs=policy_plugin_refs):
        return _records_have_confident_metadata_anchor(
            records,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        ) or _records_meet_primary_scope(
            records,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
    if query_policy._query_prefers_question_anchor(
        query, policy_plugin_refs=policy_plugin_refs
    ) and not query_policy._query_prefers_service_anchor(
        query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return _records_have_strong_question_anchor(
            records,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
    return _records_have_confident_metadata_anchor(
        records,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )


def _dedupe_records(
    records: list[dict[str, Any]], *, query: str, policy_plugin_refs: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[str | None, str | None, str], dict[str, Any]] = {}
    for record in records:
        key = _record_dedupe_key(record)
        if not any(key):
            continue
        current = best_by_key.get(key)
        if current is None or _record_rank_score(
            record, query=query, policy_plugin_refs=policy_plugin_refs
        ) > _record_rank_score(current, query=query, policy_plugin_refs=policy_plugin_refs):
            best_by_key[key] = record
    return list(best_by_key.values())


def _records_meet_primary_scope(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    min_records = max(1, (settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS or 1))
    if len(records) < min_records:
        return False
    min_top_score = float(settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE or 0.0)
    if min_top_score <= 0:
        return True
    top_score = max(
        (_record_rank_score(record, query=query, policy_plugin_refs=policy_plugin_refs) for record in records),
        default=0.0,
    )
    return top_score >= min_top_score


def _records_have_strong_question_anchor(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    return any(
        _record_has_strong_question_anchor(
            record,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        and _record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs)
        for record in records or []
    )


def _records_have_confident_metadata_anchor(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    for record in records or []:
        if _record_metadata_anchor_bonus(record, query=query) >= 0.1:
            return True
        if not _record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs):
            continue
        if _record_has_strong_question_anchor(
            record,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        ):
            return True
    return False


def _records_can_skip_metadata_anchor_fallback(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    if _query_has_specific_service_anchor_candidate(query, policy_plugin_refs=policy_plugin_refs):
        return any(
            _record_exact_query_anchor_terms(record, query=query, policy_plugin_refs=policy_plugin_refs)
            and _records_have_confident_metadata_anchor([record], query=query, policy_plugin_refs=policy_plugin_refs)
            for record in records or []
        )
    if query_policy._query_prefers_question_anchor(
        query, policy_plugin_refs=policy_plugin_refs
    ) and not query_policy._query_prefers_service_anchor(
        query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return _records_have_strong_question_anchor(
            records,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
    return _records_have_confident_metadata_anchor(
        records,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
