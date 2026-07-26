"""Shared constants and low-level helpers for the Dify external knowledge adapter.

Mechanically extracted from `app.api.v1.integrations_dify`; do not import that
module from here (see package docstring).
"""

import re
from typing import Any
from uuid import UUID

from app.rag.pipeline_plugins.contracts import DISPLAY_METADATA_KEY, EVALUABLE_METADATA_KEY, INDEXED_METADATA_KEY

_SCORE_KEYS = (
    "score",
    "relevance_score",
    "retrieval_score",
    "rerank_score",
    "vector_score",
    "bm25_score",
    "keyword_score",
    "mimirq_score",
)
_METADATA_SCORE_KEYS = tuple(key for key in _SCORE_KEYS if key != "score")
_PUBLIC_METADATA_VIEW_KEYS = (EVALUABLE_METADATA_KEY, DISPLAY_METADATA_KEY)
_RETRIEVAL_METADATA_VIEW_KEYS = (INDEXED_METADATA_KEY, *_PUBLIC_METADATA_VIEW_KEYS)
_METADATA_ANCHOR_KEYS = (
    "question",
    "aliases",
    "primary_alias",
    "service_name",
    "service_aliases",
    "case_title",
    "source_topic",
    "title",
)
_FUZZY_METADATA_ANCHOR_KEYS = (
    "service_name",
    "aliases",
    "primary_alias",
    "service_aliases",
    "case_title",
    "source_topic",
    "title",
)
_REGION_ANCHOR_KEYS = ("district", "applicable_area")
_MIN_REGION_ANCHOR_OVERLAP_CHARS = 3
_MIN_REGIONAL_QUESTION_OVERLAP_CHARS = 8
_MIN_SPECIFIC_INTENT_CHARS = 7
_EXACT_PRIMARY_ALIAS_MATCH_BONUS = 0.16
_URL_EVIDENCE_BONUS = 0.04
_URL_EVIDENCE_BONUS_MAX = 0.08
_SOURCE_RECORD_ID_KEYS = ("source_record_id", "record_id")
_SOURCE_RECORD_SCOPE_KEYS = ("knowledge_section", "source_file", "source_topic", "document_id")
_DEFAULT_RESPONSE_HINT_ANSWER_PREFIX = "Answer highlights"
_MAX_HINT_VALUE_CHARS = 700
_MAX_QA_HINT_VALUE_CHARS = 420
_QUESTION_ANCHOR_NEAR_MATCH_MIN_CHARS = 8
_QUESTION_ANCHOR_NEAR_MATCH_MIN_RATIO = 0.86
_QUESTION_ANCHOR_QUERY_MARKERS = ("是否", "能否", "可否", "什么是", "为什么", "怎么", "如何", "哪里", "吗", "？", "?")
_EXPLICIT_QUESTION_FORM_MARKERS = ("请问", "是否", "能否", "可否", "吗", "？", "?", "什么是", "为什么")
_MIXED_INTENT_QUERY_MARKERS = (
    "另外",
    "同时",
    "以及",
    "并且",
    "还想",
    "还要",
    "一次知道",
    "分别",
    "顺便",
    "合并回答",
    "一并回答",
    "一起回答",
    "分别回答",
    "分开回答",
    "请合并",
    "请分别",
)
_MIXED_INTENT_LIST_SPLIT_RE = re.compile(r"[、,，/]|以及|或者|或|和")
_MIXED_INTENT_SUBJECT_TRAILING_INSTRUCTION_RE = re.compile(
    r"(?:[，,、：:；;]\s*)?"
    r"(?:请|麻烦|帮我|帮忙)?"
    r"(?:合并回答|一并回答|一起回答|分别回答|分开回答|同时说明|说明一下|告诉我|给一下|列一下|回答)\s*$"
)
_QUOTED_ANCHOR_RE = re.compile(
    r'"([^"]{3,80})"'
    r"|“([^”]{3,80})”"
    r"|「([^」]{3,80})」"
    r"|『([^』]{3,80})』"
    r"|《([^》]{3,80})》"
    r"|'([^']{3,80})'"
)
_QUESTION_ANCHOR_SHORT_QUERY_MIN_CHARS = 4
_QUESTION_ANCHOR_SHORT_QUERY_MAX_CHARS = 24
_SERVICE_ANCHOR_ADMIN_MARKERS = ("在", "到")
_SERVICE_ANCHOR_QUERY_TRAILING_CHARS = " \t\r\n?？。！!，,、：:；;"
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_URL_EVIDENCE_QUERY_MARKERS = (
    "入口",
    "链接",
    "网址",
    "网站",
    "网页",
    "在线",
    "线上",
    "网上",
    "app",
    "小程序",
    "二维码",
    "url",
    "http",
)
_FAST_ANSWER_QUERY_STOP_TERMS = {
    "什么",
    "哪些",
    "怎么",
    "如何",
    "申请",
    "办理",
    "查询",
    "帮我",
    "核对",
    "依据",
    "最好",
    "是不是能办",
}
_QUESTION_ANCHOR_INTENT_GROUPS = (
    ("application", ("申请", "申报", "办理", "申领", "领取", "怎么领", "怎么申请", "如何申请", "流程", "步骤")),
    ("amount", ("怎么算", "计算", "多少钱", "多少", "补贴多少", "标准", "金额")),
    ("timing", ("多久", "多久到账", "何时", "什么时候", "时间", "进度")),
)
_QUESTION_ANCHOR_SUBJECT_NOISE_TERMS = (
    "办理",
    "办",
    "事项",
    "这个事项",
    "这个",
    "请问",
    "可以",
    "能否",
    "是否",
    "怎么",
    "如何",
    "是什么",
    "什么",
    "帮我",
    "直接说清楚",
    "麻烦查一下",
    "麻烦帮我查一下",
    "主要想确认",
)


def _first_non_empty(citation: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = citation.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _clamp_score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def _citation_score(citation: dict[str, Any]) -> float:
    for key in _SCORE_KEYS:
        if citation.get(key) is not None:
            return _clamp_score(citation.get(key))
    metadata = citation.get("metadata")
    if isinstance(metadata, dict):
        for key in _METADATA_SCORE_KEYS:
            if metadata.get(key) is not None:
                return _clamp_score(metadata.get(key))
    return 0.0


def _citation_dataset_id(citation: dict[str, Any], *, fallback_dataset_id: UUID | None) -> UUID | None:
    raw_metadata = citation.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    for value in (citation.get("dataset_id"), metadata.get("dataset_id"), fallback_dataset_id):
        if value is None:
            continue
        try:
            return UUID(str(value))
        except ValueError:
            continue
    return None


def _citation_chunk_id(citation: dict[str, Any]) -> str:
    raw_metadata = citation.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    for value in (citation.get("chunk_id"), metadata.get("chunk_id")):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _iter_record_metadata_layers(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw_metadata = record.get("metadata")
    if not isinstance(raw_metadata, dict):
        return []
    layers = [raw_metadata]
    for key in _RETRIEVAL_METADATA_VIEW_KEYS:
        nested = raw_metadata.get(key)
        if isinstance(nested, dict) and nested:
            layers.append(nested)
    return layers


def _metadata_terms(value: Any) -> list[str]:
    raw_items = value if isinstance(value, list | tuple | set) else [value]
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _response_hint_metadata_conditions_match(layer: dict[str, Any], field_spec: dict[str, Any]) -> bool:
    conditions = field_spec.get("when_metadata")
    if conditions is None:
        conditions = field_spec.get("metadata_when")
    if not isinstance(conditions, dict) or not conditions:
        return True
    for key, expected in conditions.items():
        name = str(key or "").strip()
        if not name:
            return False
        expected_terms = {_normalize_match_term(term) for term in _metadata_terms(expected)}
        if not expected_terms:
            return False
        actual_terms = {_normalize_match_term(term) for term in _metadata_terms(layer.get(name))}
        if not actual_terms or actual_terms.isdisjoint(expected_terms):
            return False
    return True


def _normalize_match_term(value: Any) -> str:
    text = str(value or "").strip().casefold()
    out: list[str] = []
    for char in text:
        if char.isspace():
            continue
        if re.match(r"[\W_]", char, flags=re.UNICODE):
            continue
        out.append(char)
    return "".join(out)
