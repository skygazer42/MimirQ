#!/usr/bin/env python3
"""Golden retrieval evaluation for the Changzhou government service plugin.

The evaluator intentionally keeps Dify workflow logic out of scope. It calls
MimirQ's Dify adapter with fixed cases and scores whether the expected source
or chunk appears in the returned records.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.rag.pipeline_plugins.contracts import DISPLAY_METADATA_KEY, EVALUABLE_METADATA_KEY  # noqa: E402
from app.rag.retrieval.planner import summarize_kg_hint_diagnostics  # noqa: E402

DEFAULT_CASES = "plugins/pipelines/changzhou-gov-service-knowledge/golden_eval_cases.json"
QUALITY_GATE_EXIT_CODE = 3
_QUALITY_GATE_METRICS = (
    "hit_at_1",
    "hit_at_3",
    "hit_at_5",
    "mrr",
    "answer_grounding_rate",
    "answer_key_point_recall",
    "retrieval_effective_context_rate",
    "expected_metadata_case_rate",
    "section_expected_metadata_case_rate",
    "required_section_coverage_rate",
    "top_1_expected_metadata_match_rate",
    "top_3_expected_metadata_match_rate",
    "top_5_expected_metadata_match_rate",
    "generated_answer_grounding_rate",
    "generated_answer_key_point_recall",
    "generated_answer_context_supported_rate",
    "generated_answer_policy_clean_rate",
)
_QUALITY_GATE_MAX_METRICS = ("generated_answer_fallback_rate", "retrieval_noise_rate", "kg_noise_rate")
_FALLBACK_ANSWER_MARKERS = (
    "只能答复常州市政务服务领域",
    "超出领域的问题",
    "暂时无法回答",
)
_PUBLIC_METADATA_VIEW_KEYS = (EVALUABLE_METADATA_KEY, DISPLAY_METADATA_KEY)
_GENERATED_ANSWER_FORBIDDEN_PHRASES = (
    "必须按顺序包含以下标题",
    "知识库内容中有",
    "输出此部分内容",
    "暂无相关常见问题QA知识",
)
_QUALITY_PROFILE_THRESHOLDS: dict[str, dict[str, float]] = {
    "changzhou-retrieval": {
        "hit_at_1": 0.95,
        "hit_at_3": 0.98,
        "hit_at_5": 0.98,
        "answer_grounding_rate": 1.0,
        "answer_key_point_recall": 1.0,
        "retrieval_effective_context_rate": 0.9,
        "expected_metadata_case_rate": 1.0,
        "section_expected_metadata_case_rate": 1.0,
        "required_section_coverage_rate": 1.0,
        "top_1_expected_metadata_match_rate": 0.95,
        "top_3_expected_metadata_match_rate": 0.98,
        "top_5_expected_metadata_match_rate": 0.98,
    }
}
_QUALITY_PROFILE_MAXIMUMS: dict[str, dict[str, float]] = {
    "changzhou-retrieval": {
        "retrieval_noise_rate": 0.1,
        "kg_noise_rate": 0.1,
    }
}
_QUALITY_PROFILE_REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "changzhou-retrieval": (
        "01政务服务事项知识",
        "02高效办成一件事",
        "03常州市常见问题",
        "04专题常见问答",
        "05业务部门常见问题",
        "06各区常见问题",
    )
}
QUALITY_PROFILES = tuple(["none", *_QUALITY_PROFILE_THRESHOLDS.keys()])
KG_MODES = ("default", "off", "on")
_COMPARISON_HIGHER_IS_BETTER_METRICS = (
    "hit_at_1",
    "hit_at_3",
    "hit_at_5",
    "mrr",
    "answer_grounding_rate",
    "answer_key_point_recall",
    "retrieval_effective_context_rate",
    "expected_metadata_case_rate",
    "section_expected_metadata_case_rate",
    "required_section_coverage_rate",
    "top_1_expected_metadata_match_rate",
    "top_3_expected_metadata_match_rate",
    "top_5_expected_metadata_match_rate",
    "generated_answer_grounding_rate",
    "generated_answer_key_point_recall",
    "generated_answer_context_supported_rate",
    "generated_answer_policy_clean_rate",
)
_COMPARISON_LOWER_IS_BETTER_METRICS = (
    "retrieval_noise_rate",
    "generated_answer_fallback_rate",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _env_file_values(path: str) -> dict[str, str]:
    env_path = Path(_text(path))
    if not env_path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip().strip('"').strip("'")
    return values


def load_token(explicit_token: str, *, env_file: str = ".env") -> str:
    explicit = _text(explicit_token)
    if explicit:
        return explicit
    env_token = _text(os.getenv("DIFY_EXTERNAL_KNOWLEDGE_API_KEY"))
    if env_token:
        return env_token
    env_tokens = _text(os.getenv("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS"))
    if env_tokens:
        return _text(env_tokens.split(",", 1)[0])
    file_values = _env_file_values(env_file)
    file_token = _text(file_values.get("DIFY_EXTERNAL_KNOWLEDGE_API_KEY"))
    if file_token:
        return file_token
    file_tokens = _text(file_values.get("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS"))
    if file_tokens:
        return _text(file_tokens.split(",", 1)[0])
    return ""


def _normalize_quality_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", _text(value)).lower()
    out: list[str] = []
    for char in text:
        if char.isspace():
            continue
        category = unicodedata.category(char)
        if category.startswith(("P", "S")):
            continue
        out.append(char)
    return "".join(out)


def _quality_point_value(point: str) -> str:
    text = _text(point)
    colon_positions = [index for index in (text.find("："), text.find(":")) if index >= 0]
    if not colon_positions:
        return ""
    split_at = min(colon_positions)
    return text[split_at + 1 :].strip()


def _cjk_char_count(text: str) -> int:
    return sum(1 for char in str(text or "") if "\u4e00" <= char <= "\u9fff")


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


def _quality_point_cjk_fuzzy_in_text(point: str, text: str) -> bool:
    normalized_point = _normalize_quality_text(point)
    normalized_text = _normalize_quality_text(text)
    if len(normalized_point) < 12 or _cjk_char_count(normalized_point) < 8:
        return False
    if not normalized_text:
        return False
    overlap = _longest_common_substring_length(normalized_point, normalized_text)
    return (overlap / max(1, len(normalized_point))) >= 0.74


def _quality_point_in_text(point: str, text: str) -> bool:
    normalized_point = _normalize_quality_text(point)
    normalized_text = _normalize_quality_text(text)
    if normalized_point and normalized_point in normalized_text:
        return True
    normalized_value = _normalize_quality_text(_quality_point_value(point))
    if len(normalized_value) >= 2 and normalized_value in normalized_text:
        return True
    return _quality_point_cjk_fuzzy_in_text(point, text)



def _contains_all(value: Any, expected: list[Any]) -> bool:
    text = _text(value)
    return all(_text(item) in text for item in expected if _text(item))


def _metadata_matches(record_meta: dict[str, Any], expected_meta: dict[str, Any]) -> bool:
    for key, expected in expected_meta.items():
        actual = record_meta.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _metadata_layers(record_meta: dict[str, Any]) -> list[dict[str, Any]]:
    layers = [record_meta]
    for key in _PUBLIC_METADATA_VIEW_KEYS:
        nested = record_meta.get(key)
        if isinstance(nested, dict):
            layers.append(nested)
    return layers


def _metadata_matches_any_layer(record_meta: dict[str, Any], expected_meta: dict[str, Any]) -> bool:
    return any(_metadata_matches(layer, expected_meta) for layer in _metadata_layers(record_meta))


def _expected_metadata(case: dict[str, Any]) -> dict[str, Any]:
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    metadata = expected.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) and metadata else {}


def _expected_string_values(expected: dict[str, Any], *keys: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for key in keys:
        raw = expected.get(key)
        values = raw if isinstance(raw, list | tuple | set) else [raw]
        for value in values:
            text = _text(value)
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
    return tuple(out)


def evaluate_case_scope(case: dict[str, Any]) -> dict[str, Any]:
    expected_meta = _expected_metadata(case)
    section = _text(expected_meta.get("knowledge_section"))
    return {
        "expected_metadata": expected_meta,
        "knowledge_section": section,
        "has_expected_metadata": bool(expected_meta),
        "has_knowledge_section": bool(section),
    }


def evaluate_metadata_quality(case: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    expected_meta = _expected_metadata(case)
    if not expected_meta:
        return {"evaluated": False}

    first_match_rank: int | None = None
    for index, record in enumerate(records or [], 1):
        record_meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        if _metadata_matches_any_layer(record_meta, expected_meta):
            first_match_rank = index
            break

    return {
        "evaluated": True,
        "expected": expected_meta,
        "first_match_rank": first_match_rank,
        "top_1_match": first_match_rank == 1,
        "top_3_match": first_match_rank is not None and first_match_rank <= 3,
        "top_5_match": first_match_rank is not None and first_match_rank <= 5,
    }


def record_matches(record: dict[str, Any], expected: dict[str, Any]) -> bool:
    if not isinstance(record, dict) or not isinstance(expected, dict):
        return False
    title_contains = expected.get("title_contains")
    if isinstance(title_contains, list) and not _contains_all(record.get("title"), title_contains):
        return False
    content_contains = expected.get("content_contains")
    if isinstance(content_contains, list) and not _contains_all(record.get("content"), content_contains):
        return False
    metadata = expected.get("metadata")
    if isinstance(metadata, dict):
        record_meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        if not _metadata_matches_any_layer(record_meta, metadata):
            return False
    return True


def _answer_key_points(case: dict[str, Any]) -> list[str]:
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    raw = expected.get("answer_key_points")
    if not isinstance(raw, list):
        raw = expected.get("answer_contains")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = _text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _answer_key_point_aliases(case: dict[str, Any]) -> dict[str, list[str]]:
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    raw = expected.get("answer_key_point_aliases")
    if not isinstance(raw, dict):
        return {}
    aliases: dict[str, list[str]] = {}
    for point, values in raw.items():
        canonical = _text(point)
        if not canonical:
            continue
        raw_values = values if isinstance(values, list) else [values]
        clean_values: list[str] = []
        seen: set[str] = set()
        for value in raw_values:
            alias = _text(value)
            if not alias or alias in seen:
                continue
            seen.add(alias)
            clean_values.append(alias)
        if clean_values:
            aliases[canonical] = clean_values
    return aliases


def _quality_point_or_alias_in_text(point: str, text: str, aliases: dict[str, list[str]]) -> bool:
    return _quality_point_in_text(point, text) or any(_quality_point_in_text(alias, text) for alias in aliases.get(point, []))


def _case_answer_context_top_k(case: dict[str, Any]) -> int:
    try:
        return max(1, int(case.get("answer_context_top_k") or 3))
    except (TypeError, ValueError):
        return 3


def _case_min_answer_recall(case: dict[str, Any]) -> float:
    try:
        value = float(case.get("min_answer_recall", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, value))


def evaluate_answer_quality(case: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    key_points = _answer_key_points(case)
    aliases = _answer_key_point_aliases(case)
    context_top_k = _case_answer_context_top_k(case)
    context_records = list((records or [])[:context_top_k])
    context = "\n".join(_text(record.get("content")) for record in context_records)
    missing = [point for point in key_points if not _quality_point_or_alias_in_text(point, context, aliases)]
    total = len(key_points)
    matched = total - len(missing)
    recall = (matched / total) if total else 1.0
    evaluated_records = len(context_records) if key_points else 0
    effective_records = (
        sum(
            1
            for record in context_records
            if any(_quality_point_or_alias_in_text(point, _text(record.get("content")), aliases) for point in key_points)
        )
        if key_points
        else 0
    )
    effective_context_rate = (effective_records / evaluated_records) if evaluated_records else 0.0
    return {
        "key_points_total": total,
        "key_points_matched": matched,
        "key_point_recall": recall,
        "grounded": recall >= _case_min_answer_recall(case),
        "missing_key_points": missing,
        "context_top_k": context_top_k,
        "effective_records": effective_records,
        "evaluated_records": evaluated_records,
        "effective_context_rate": effective_context_rate,
        "noise_rate": (1.0 - effective_context_rate) if evaluated_records else 0.0,
    }


def _answer_text(answer_item: dict[str, Any] | None) -> str:
    if not isinstance(answer_item, dict):
        return ""
    for key in ("answer", "text", "content", "result"):
        text = _text(answer_item.get(key))
        if text:
            return text
    return ""


def _is_fallback_answer(answer: str) -> bool:
    text = _text(answer)
    return bool(text) and all(marker in text for marker in _FALLBACK_ANSWER_MARKERS)


def _forbidden_generated_answer_phrases(answer: str) -> list[str]:
    text = _text(answer)
    return [phrase for phrase in _GENERATED_ANSWER_FORBIDDEN_PHRASES if phrase in text]


def evaluate_generated_answer_quality(
    case: dict[str, Any],
    records: list[dict[str, Any]],
    answer_item: dict[str, Any] | None,
) -> dict[str, Any]:
    answer = _answer_text(answer_item)
    if not answer:
        return {"provided": False}
    fallback = _is_fallback_answer(answer)
    forbidden_phrases = _forbidden_generated_answer_phrases(answer)
    policy_clean = not forbidden_phrases
    key_points = _answer_key_points(case)
    aliases = _answer_key_point_aliases(case)
    missing = [point for point in key_points if not _quality_point_or_alias_in_text(point, answer, aliases)]
    total = len(key_points)
    matched = total - len(missing)
    recall = (matched / total) if total else 1.0
    context = "\n".join(_text(record.get("content")) for record in records or [])
    matched_points = [point for point in key_points if point not in missing]
    context_supported = (
        all(_quality_point_or_alias_in_text(point, context, aliases) for point in matched_points)
        if matched_points
        else bool(context or not key_points)
    )
    return {
        "provided": True,
        "fallback": fallback,
        "key_points_total": total,
        "key_points_matched": matched,
        "key_point_recall": recall,
        "grounded": (not fallback) and policy_clean and recall >= _case_min_answer_recall(case),
        "context_supported": context_supported,
        "policy_clean": policy_clean,
        "forbidden_phrases": forbidden_phrases,
        "missing_key_points": missing,
    }


def evaluate_case(
    case: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    generated_answer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    hit_rank: int | None = None
    matched_record: dict[str, Any] | None = None
    for index, record in enumerate(records or [], 1):
        if record_matches(record, expected):
            hit_rank = index
            matched_record = record
            break
    return {
        "id": case.get("id"),
        "query": case.get("query"),
        "knowledge_id": case.get("knowledge_id"),
        "hit_rank": hit_rank,
        "hit_at_1": hit_rank == 1,
        "hit_at_3": hit_rank is not None and hit_rank <= 3,
        "hit_at_5": hit_rank is not None and hit_rank <= 5,
        "matched_record": matched_record,
        "top_titles": [_text(record.get("title")) for record in (records or [])[:5]],
        "case_scope": evaluate_case_scope(case),
        "metadata_quality": evaluate_metadata_quality(case, records),
        "answer_quality": evaluate_answer_quality(case, records),
        "kg_hint_diagnostics": summarize_kg_hint_diagnostics(
            records,
            expected_chunk_ids=_expected_string_values(expected, "chunk_id", "chunk_ids"),
            expected_document_ids=_expected_string_values(expected, "document_id", "document_ids"),
            expected_metadata=_expected_metadata(case),
            metadata_view_keys=_PUBLIC_METADATA_VIEW_KEYS,
        ),
        "generated_answer_quality": evaluate_generated_answer_quality(case, records, generated_answer),
    }


def summarize_results(results: list[dict[str, Any]], *, required_sections: tuple[str, ...] = ()) -> dict[str, Any]:
    total = len(results)
    if total <= 0:
        return {"cases": 0, "hit_at_1": 0.0, "hit_at_3": 0.0, "hit_at_5": 0.0, "mrr": 0.0, "misses": 0}
    ranks = [item.get("hit_rank") for item in results]
    answer_items = [
        item.get("answer_quality")
        for item in results
        if isinstance(item.get("answer_quality"), dict)
        and int((item.get("answer_quality") or {}).get("key_points_total") or 0) > 0
    ]
    answer_total_points = sum(int((item or {}).get("key_points_total") or 0) for item in answer_items)
    answer_matched_points = sum(int((item or {}).get("key_points_matched") or 0) for item in answer_items)
    retrieval_evaluated_records = sum(int((item or {}).get("evaluated_records") or 0) for item in answer_items)
    retrieval_effective_records = sum(int((item or {}).get("effective_records") or 0) for item in answer_items)
    metadata_items = [
        item.get("metadata_quality")
        for item in results
        if isinstance(item.get("metadata_quality"), dict) and (item.get("metadata_quality") or {}).get("evaluated") is True
    ]
    kg_items = [
        item.get("kg_hint_diagnostics")
        for item in results
        if isinstance(item.get("kg_hint_diagnostics"), dict)
    ]
    kg_candidate_records = sum(int((item or {}).get("kg_candidate_count") or 0) for item in kg_items)
    kg_noise_evaluated_items = [item for item in kg_items if bool((item or {}).get("kg_noise_evaluated"))]
    kg_noise_denominator = sum(int((item or {}).get("kg_candidate_count") or 0) for item in kg_noise_evaluated_items)
    kg_noise_records = sum(int((item or {}).get("kg_noise_record_count") or 0) for item in kg_noise_evaluated_items)
    generated_items = [
        item.get("generated_answer_quality")
        for item in results
        if isinstance(item.get("generated_answer_quality"), dict)
        and (item.get("generated_answer_quality") or {}).get("provided") is True
        and int((item.get("generated_answer_quality") or {}).get("key_points_total") or 0) > 0
    ]
    generated_total_points = sum(int((item or {}).get("key_points_total") or 0) for item in generated_items)
    generated_matched_points = sum(int((item or {}).get("key_points_matched") or 0) for item in generated_items)
    scope_items = [
        item.get("case_scope")
        for item in results
        if isinstance(item.get("case_scope"), dict)
    ]
    section_counts: dict[str, int] = {}
    for item in scope_items:
        section = _text((item or {}).get("knowledge_section"))
        if section:
            section_counts[section] = section_counts.get(section, 0) + 1
    required = tuple(_text(item) for item in required_sections if _text(item))
    covered_required = tuple(section for section in required if section_counts.get(section, 0) > 0)
    missing_required = tuple(section for section in required if section_counts.get(section, 0) <= 0)
    section_metadata_cases = sum(1 for item in scope_items if bool((item or {}).get("has_knowledge_section")))
    return {
        "cases": total,
        "hit_at_1": sum(1 for rank in ranks if rank == 1) / total,
        "hit_at_3": sum(1 for rank in ranks if isinstance(rank, int) and rank <= 3) / total,
        "hit_at_5": sum(1 for rank in ranks if isinstance(rank, int) and rank <= 5) / total,
        "mrr": sum((1 / rank) for rank in ranks if isinstance(rank, int) and rank > 0) / total,
        "misses": sum(1 for rank in ranks if rank is None),
        "answer_cases": len(answer_items),
        "answer_grounding_rate": (
            sum(1 for item in answer_items if bool((item or {}).get("grounded"))) / len(answer_items)
            if answer_items
            else 0.0
        ),
        "answer_key_point_recall": (answer_matched_points / answer_total_points) if answer_total_points else 0.0,
        "answer_missing_cases": sum(1 for item in answer_items if not bool((item or {}).get("grounded"))),
        "retrieval_effective_context_rate": (
            retrieval_effective_records / retrieval_evaluated_records if retrieval_evaluated_records else 0.0
        ),
        "retrieval_noise_rate": (
            1.0 - (retrieval_effective_records / retrieval_evaluated_records) if retrieval_evaluated_records else 0.0
        ),
        "retrieval_effective_records": retrieval_effective_records,
        "retrieval_evaluated_records": retrieval_evaluated_records,
        "expected_metadata_cases": len(metadata_items),
        "expected_metadata_case_rate": len(metadata_items) / total,
        "section_expected_metadata_cases": section_metadata_cases,
        "section_expected_metadata_case_rate": section_metadata_cases / total,
        "missing_knowledge_section_cases": total - section_metadata_cases,
        "knowledge_section_cases": {key: section_counts[key] for key in sorted(section_counts)},
        "required_sections": list(required),
        "covered_required_sections": list(covered_required),
        "missing_required_sections": list(missing_required),
        "required_section_coverage_rate": (len(covered_required) / len(required)) if required else 1.0,
        "top_1_expected_metadata_match_rate": (
            sum(1 for item in metadata_items if bool((item or {}).get("top_1_match"))) / len(metadata_items)
            if metadata_items
            else 0.0
        ),
        "top_3_expected_metadata_match_rate": (
            sum(1 for item in metadata_items if bool((item or {}).get("top_3_match"))) / len(metadata_items)
            if metadata_items
            else 0.0
        ),
        "top_5_expected_metadata_match_rate": (
            sum(1 for item in metadata_items if bool((item or {}).get("top_5_match"))) / len(metadata_items)
            if metadata_items
            else 0.0
        ),
        "top_1_expected_metadata_mismatch_cases": sum(
            1 for item in metadata_items if not bool((item or {}).get("top_1_match"))
        ),
        "top_3_expected_metadata_mismatch_cases": sum(
            1 for item in metadata_items if not bool((item or {}).get("top_3_match"))
        ),
        "top_5_expected_metadata_mismatch_cases": sum(
            1 for item in metadata_items if not bool((item or {}).get("top_5_match"))
        ),
        "kg_hint_cases": len(kg_items),
        "kg_candidate_cases": sum(1 for item in kg_items if int((item or {}).get("kg_candidate_count") or 0) > 0),
        "kg_candidate_case_rate": (
            sum(1 for item in kg_items if int((item or {}).get("kg_candidate_count") or 0) > 0) / total
        ),
        "kg_candidate_records": kg_candidate_records,
        "kg_query_expansion_records": sum(
            int((item or {}).get("kg_query_expansion_record_count") or 0) for item in kg_items
        ),
        "kg_entity_anchor_records": sum(
            int((item or {}).get("kg_entity_anchor_record_count") or 0) for item in kg_items
        ),
        "kg_relation_neighbor_records": sum(
            int((item or {}).get("kg_relation_neighbor_record_count") or 0) for item in kg_items
        ),
        "kg_boosted_records": sum(int((item or {}).get("kg_boosted_record_count") or 0) for item in kg_items),
        "kg_noise_evaluated_cases": len(kg_noise_evaluated_items),
        "kg_noise_records": kg_noise_records,
        "kg_noise_rate": (kg_noise_records / kg_noise_denominator) if kg_noise_denominator else 0.0,
        "generated_answer_cases": len(generated_items),
        "generated_answer_grounding_rate": (
            sum(1 for item in generated_items if bool((item or {}).get("grounded"))) / len(generated_items)
            if generated_items
            else 0.0
        ),
        "generated_answer_key_point_recall": (
            generated_matched_points / generated_total_points if generated_total_points else 0.0
        ),
        "generated_answer_context_supported_rate": (
            sum(1 for item in generated_items if bool((item or {}).get("context_supported"))) / len(generated_items)
            if generated_items
            else 0.0
        ),
        "generated_answer_policy_clean_rate": (
            sum(1 for item in generated_items if bool((item or {}).get("policy_clean", True))) / len(generated_items)
            if generated_items
            else 0.0
        ),
        "generated_answer_missing_cases": sum(1 for item in generated_items if not bool((item or {}).get("grounded"))),
        "generated_answer_fallback_rate": (
            sum(1 for item in generated_items if bool((item or {}).get("fallback"))) / len(generated_items)
            if generated_items
            else 0.0
        ),
        "generated_answer_fallback_cases": sum(1 for item in generated_items if bool((item or {}).get("fallback"))),
        "generated_answer_policy_violation_cases": sum(
            1 for item in generated_items if not bool((item or {}).get("policy_clean", True))
        ),
    }


def evaluate_quality_gate(
    summary: dict[str, Any],
    thresholds: dict[str, float] | None = None,
    maximums: dict[str, float] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for metric, minimum in (thresholds or {}).items():
        if metric not in _QUALITY_GATE_METRICS:
            continue
        try:
            actual = float(summary.get(metric, 0.0) or 0.0)
            minimum_value = float(minimum)
        except (TypeError, ValueError):
            continue
        checks.append(
            {
                "metric": metric,
                "actual": actual,
                "minimum": minimum_value,
                "passed": actual >= minimum_value,
            }
        )
    for metric, maximum in (maximums or {}).items():
        if metric not in _QUALITY_GATE_MAX_METRICS:
            continue
        try:
            actual = float(summary.get(metric, 0.0) or 0.0)
            maximum_value = float(maximum)
        except (TypeError, ValueError):
            continue
        checks.append(
            {
                "metric": metric,
                "actual": actual,
                "maximum": maximum_value,
                "passed": actual <= maximum_value,
            }
        )
    failed = sum(1 for check in checks if check.get("passed") is not True)
    return {"passed": failed == 0, "failed": failed, "checks": checks}


def quality_profile_thresholds(profile: str) -> dict[str, float]:
    return dict(_QUALITY_PROFILE_THRESHOLDS.get(str(profile or "none"), {}))


def quality_profile_maximums(profile: str) -> dict[str, float]:
    return dict(_QUALITY_PROFILE_MAXIMUMS.get(str(profile or "none"), {}))


def quality_profile_required_sections(profile: str) -> tuple[str, ...]:
    return tuple(_QUALITY_PROFILE_REQUIRED_SECTIONS.get(str(profile or "none"), ()))


def report_exit_code(report: dict[str, Any]) -> int:
    gate = report.get("gate") if isinstance(report.get("gate"), dict) else {}
    return QUALITY_GATE_EXIT_CODE if gate.get("passed") is False else 0


def _summary_metric(summary: dict[str, Any], metric: str) -> float | None:
    if metric not in summary:
        return None
    try:
        return float(summary.get(metric) or 0.0)
    except (TypeError, ValueError):
        return None


def _comparison_check(
    *,
    metric: str,
    baseline: float,
    candidate: float,
    direction: str,
    tolerance: float,
) -> dict[str, Any]:
    delta = candidate - baseline
    if direction == "lower_is_better":
        passed = candidate <= baseline + tolerance
        return {
            "metric": metric,
            "direction": direction,
            "baseline": baseline,
            "candidate": candidate,
            "delta": delta,
            "maximum_increase": tolerance,
            "passed": passed,
        }
    passed = candidate >= baseline - tolerance
    return {
        "metric": metric,
        "direction": "higher_is_better",
        "baseline": baseline,
        "candidate": candidate,
        "delta": delta,
        "maximum_drop": tolerance,
        "passed": passed,
    }


def compare_reports(
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    *,
    thresholds: dict[str, float] | None = None,
    maximums: dict[str, float] | None = None,
    max_quality_drop: float = 0.0,
    max_noise_increase: float = 0.0,
) -> dict[str, Any]:
    baseline_summary = baseline_report.get("summary") if isinstance(baseline_report.get("summary"), dict) else {}
    candidate_summary = candidate_report.get("summary") if isinstance(candidate_report.get("summary"), dict) else {}
    candidate_gate = evaluate_quality_gate(candidate_summary, thresholds, maximums)
    checks: list[dict[str, Any]] = []
    quality_tolerance = max(0.0, float(max_quality_drop or 0.0))
    noise_tolerance = max(0.0, float(max_noise_increase or 0.0))

    for metric in _COMPARISON_HIGHER_IS_BETTER_METRICS:
        baseline_value = _summary_metric(baseline_summary, metric)
        candidate_value = _summary_metric(candidate_summary, metric)
        if baseline_value is None or candidate_value is None:
            continue
        checks.append(
            _comparison_check(
                metric=metric,
                baseline=baseline_value,
                candidate=candidate_value,
                direction="higher_is_better",
                tolerance=quality_tolerance,
            )
        )

    for metric in _COMPARISON_LOWER_IS_BETTER_METRICS:
        baseline_value = _summary_metric(baseline_summary, metric)
        candidate_value = _summary_metric(candidate_summary, metric)
        if baseline_value is None or candidate_value is None:
            continue
        checks.append(
            _comparison_check(
                metric=metric,
                baseline=baseline_value,
                candidate=candidate_value,
                direction="lower_is_better",
                tolerance=noise_tolerance,
            )
        )

    failed = sum(1 for check in checks if check.get("passed") is not True)
    if candidate_gate.get("passed") is False:
        failed += 1
    return {
        "schema": "mimirq.changzhou_gov_service_knowledge.golden_compare.v1",
        "generated_at": _utc_now_text(),
        "summary": {
            "passed": failed == 0,
            "failed": failed,
            "compared_metrics": len(checks),
            "candidate_gate_passed": bool(candidate_gate.get("passed")),
            "baseline_cases": int(baseline_summary.get("cases") or 0),
            "candidate_cases": int(candidate_summary.get("cases") or 0),
        },
        "candidate_gate": candidate_gate,
        "checks": checks,
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
    }


def load_cases(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("golden cases must be a list or an object with cases[]")
    return [case for case in cases if isinstance(case, dict)]


def _normalize_answer_item(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    return {"answer": _text(raw)}


def load_answer_map(path: str) -> dict[str, dict[str, Any]]:
    if not _text(path):
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("answers"), list):
        out: dict[str, dict[str, Any]] = {}
        for raw in payload.get("answers") or []:
            if not isinstance(raw, dict):
                continue
            case_id = _text(raw.get("id") or raw.get("case_id"))
            if case_id:
                out[case_id] = dict(raw)
        return out
    if isinstance(payload, list):
        out: dict[str, dict[str, Any]] = {}
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            case_id = _text(raw.get("id") or raw.get("case_id"))
            if case_id:
                out[case_id] = dict(raw)
        return out
    if isinstance(payload, dict):
        return {_text(case_id): _normalize_answer_item(raw) for case_id, raw in payload.items() if _text(case_id)}
    raise ValueError("answers file must be an object, an object with answers[], or an answers[] list")


def load_report(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("report must be a JSON object")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("report must include summary object")
    return dict(payload)


def _should_bypass_proxy(url: str) -> bool:
    host = _text(urlparse(url).hostname).lower()
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local)


def _open_request(request: Request, *, timeout: float):
    if _should_bypass_proxy(request.full_url):
        return build_opener(ProxyHandler({})).open(request, timeout=timeout)
    return urlopen(request, timeout=timeout)


def kg_retrieval_overrides(kg_mode: str) -> dict[str, bool]:
    mode = _text(kg_mode).lower() or "default"
    if mode == "default":
        return {}
    if mode not in {"off", "on"}:
        raise ValueError(f"unsupported KG mode: {kg_mode}")
    enabled = mode == "on"
    return {
        "enable_kg_query_expansion": enabled,
        "enable_kg_chunk_injection": enabled,
        "enable_kg_chunk_boost": enabled,
    }


def _request_json(*, base_url: str, token: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/v1/integrations/dify/retrieval"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with _open_request(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body[:800]}") from exc
    except URLError as exc:
        raise RuntimeError(f"request failed for {url}: {exc}") from exc


def run_live_eval(
    *,
    cases: list[dict[str, Any]],
    base_url: str,
    token: str,
    top_k: int,
    timeout: float,
    answers: dict[str, dict[str, Any]] | None = None,
    generated_at: str = "",
    required_sections: tuple[str, ...] = (),
    kg_mode: str = "default",
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    answers_by_id = dict(answers or {})
    clean_base_url = base_url.rstrip("/")
    retrieval_overrides = kg_retrieval_overrides(kg_mode)
    for case in cases:
        payload = {
            "knowledge_id": case["knowledge_id"],
            "query": case["query"],
            "retrieval_setting": {
                "top_k": int(case.get("top_k") or top_k),
                "score_threshold": float(case.get("score_threshold") or 0.0),
            },
        }
        payload["retrieval_setting"].update(retrieval_overrides)
        response = _request_json(base_url=clean_base_url, token=token, payload=payload, timeout=timeout)
        records = response.get("records") if isinstance(response, dict) else []
        results.append(
            evaluate_case(
                case,
                records if isinstance(records, list) else [],
                generated_answer=answers_by_id.get(_text(case.get("id"))),
            )
        )
    return {
        "generated_at": _text(generated_at) or _utc_now_text(),
        "source": {"base_url": clean_base_url, "base_host": _text(urlparse(clean_base_url).hostname)},
        "summary": summarize_results(results, required_sections=required_sections),
        "results": results,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Changzhou plugin golden retrieval evaluation against MimirQ.")
    parser.add_argument("--report", default="", help="Re-evaluate an existing report JSON instead of running live retrieval.")
    parser.add_argument("--baseline-report", default="", help="KG-off or previous golden report JSON for comparison mode.")
    parser.add_argument("--candidate-report", default="", help="KG-on or candidate golden report JSON for comparison mode.")
    parser.add_argument("--cases", default=DEFAULT_CASES)
    parser.add_argument("--base-url", default=os.getenv("MIMIRQ_API_BASE_URL") or "http://127.0.0.1:8000")
    parser.add_argument("--token", default="", help="Dify external knowledge bearer token; defaults to env or --env-file.")
    parser.add_argument("--env-file", default=".env", help="Env file used to load DIFY_EXTERNAL_KNOWLEDGE_API_KEY(S).")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--answers", default="", help="Optional generated-answer JSON to score against the same cases.")
    parser.add_argument(
        "--kg-mode",
        choices=KG_MODES,
        default="default",
        help="Live retrieval KG override: default inherits service settings; off/on forces all KG assist knobs.",
    )
    parser.add_argument(
        "--quality-profile",
        choices=QUALITY_PROFILES,
        default="none",
        help="Named quality gate defaults; explicit threshold flags override profile values.",
    )
    parser.add_argument("--min-hit-at-1", type=float, default=None)
    parser.add_argument("--min-hit-at-3", type=float, default=None)
    parser.add_argument("--min-hit-at-5", type=float, default=None)
    parser.add_argument("--min-mrr", type=float, default=None)
    parser.add_argument("--min-answer-grounding-rate", type=float, default=None)
    parser.add_argument("--min-answer-key-point-recall", type=float, default=None)
    parser.add_argument("--min-retrieval-effective-context-rate", type=float, default=None)
    parser.add_argument("--min-expected-metadata-case-rate", type=float, default=None)
    parser.add_argument("--min-top-1-expected-metadata-match-rate", type=float, default=None)
    parser.add_argument("--min-top-3-expected-metadata-match-rate", type=float, default=None)
    parser.add_argument("--min-top-5-expected-metadata-match-rate", type=float, default=None)
    parser.add_argument("--min-generated-answer-grounding-rate", type=float, default=None)
    parser.add_argument("--min-generated-answer-key-point-recall", type=float, default=None)
    parser.add_argument("--min-generated-answer-context-supported-rate", type=float, default=None)
    parser.add_argument("--min-generated-answer-policy-clean-rate", type=float, default=None)
    parser.add_argument("--max-retrieval-noise-rate", type=float, default=None)
    parser.add_argument("--max-kg-noise-rate", type=float, default=None)
    parser.add_argument("--max-generated-answer-fallback-rate", type=float, default=None)
    parser.add_argument("--max-quality-drop", type=float, default=0.0)
    parser.add_argument("--max-noise-increase", type=float, default=0.0)
    parser.add_argument("--out", default="")
    return parser


def _thresholds_from_args(args: argparse.Namespace) -> dict[str, float]:
    thresholds = quality_profile_thresholds(str(args.quality_profile or "none"))
    pairs = {
        "hit_at_1": args.min_hit_at_1,
        "hit_at_3": args.min_hit_at_3,
        "hit_at_5": args.min_hit_at_5,
        "mrr": args.min_mrr,
        "answer_grounding_rate": args.min_answer_grounding_rate,
        "answer_key_point_recall": args.min_answer_key_point_recall,
        "retrieval_effective_context_rate": args.min_retrieval_effective_context_rate,
        "expected_metadata_case_rate": args.min_expected_metadata_case_rate,
        "top_1_expected_metadata_match_rate": args.min_top_1_expected_metadata_match_rate,
        "top_3_expected_metadata_match_rate": args.min_top_3_expected_metadata_match_rate,
        "top_5_expected_metadata_match_rate": args.min_top_5_expected_metadata_match_rate,
        "generated_answer_grounding_rate": args.min_generated_answer_grounding_rate,
        "generated_answer_key_point_recall": args.min_generated_answer_key_point_recall,
        "generated_answer_context_supported_rate": args.min_generated_answer_context_supported_rate,
        "generated_answer_policy_clean_rate": args.min_generated_answer_policy_clean_rate,
    }
    thresholds.update({metric: float(value) for metric, value in pairs.items() if value is not None})
    return thresholds


def _maximums_from_args(args: argparse.Namespace) -> dict[str, float]:
    maximums = quality_profile_maximums(str(args.quality_profile or "none"))
    pairs = {
        "retrieval_noise_rate": args.max_retrieval_noise_rate,
        "kg_noise_rate": args.max_kg_noise_rate,
        "generated_answer_fallback_rate": args.max_generated_answer_fallback_rate,
    }
    maximums.update({metric: float(value) for metric, value in pairs.items() if value is not None})
    return maximums


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        if args.baseline_report or args.candidate_report:
            if not args.baseline_report or not args.candidate_report:
                print("--baseline-report and --candidate-report are both required for comparison mode", file=sys.stderr)
                return 2
            report = compare_reports(
                load_report(str(args.baseline_report)),
                load_report(str(args.candidate_report)),
                thresholds=_thresholds_from_args(args),
                maximums=_maximums_from_args(args),
                max_quality_drop=float(args.max_quality_drop or 0.0),
                max_noise_increase=float(args.max_noise_increase or 0.0),
            )
            if args.out:
                Path(str(args.out)).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if bool((report.get("summary") or {}).get("passed")) else QUALITY_GATE_EXIT_CODE
        if args.report:
            report = load_report(str(args.report))
        else:
            token = load_token(str(args.token), env_file=str(args.env_file))
            if not token:
                print("DIFY_EXTERNAL_KNOWLEDGE_API_KEY(S), --token, or --env-file with token is required", file=sys.stderr)
                return 2
            report = run_live_eval(
                cases=load_cases(str(args.cases)),
                base_url=str(args.base_url),
                token=token,
                top_k=int(args.top_k),
                timeout=float(args.timeout),
                answers=load_answer_map(str(args.answers)) if args.answers else None,
                required_sections=quality_profile_required_sections(str(args.quality_profile or "none")),
                kg_mode=str(args.kg_mode or "default"),
            )
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        report["gate"] = evaluate_quality_gate(summary, _thresholds_from_args(args), _maximums_from_args(args))
    except Exception as exc:  # noqa: BLE001
        print(f"[changzhou-golden-eval] ERR: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(str(args.out)).write_text(text + "\n", encoding="utf-8")
    print(text)
    return report_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
