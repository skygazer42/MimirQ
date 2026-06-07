"""
Dify external knowledge adapter.

This router exposes MimirQ datasets as a Dify External Knowledge API source.
Dify calls this endpoint with a `knowledge_id`; MimirQ maps it to one or more
dataset IDs, runs the existing retrieval-only pipeline, and returns Dify records.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.schemas.chat import ChatRAGConfig
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document, DocumentChunk

logger = logging.getLogger(__name__)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    401: {"description": "Unauthorized"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    503: {"description": "Service Unavailable"},
}

_TOKEN_SPLIT_RE = re.compile(r"[,\s]+")
_CONTENT_KEYS = ("content", "chunk_content", "text", "quote", "snippet", "page_content")
_TITLE_KEYS = ("title", "document_name", "filename", "source", "document_id", "chunk_id")
_SCORE_KEYS = (
    "score",
    "relevance_score",
    "retrieval_score",
    "rerank_score",
    "vector_score",
    "bm25_score",
    "keyword_score",
)
_METADATA_KEYS = (
    "document_id",
    "chunk_id",
    "chunk_index",
    "page_number",
    "header_path",
    "source_path",
    "retrieval_role",
    "hit_type",
)
_PUBLIC_METADATA_VIEW_KEYS = ("_evaluable_metadata", "_display_metadata")
_RETRIEVAL_INTENT_KEYS = ("retrieval_intents", "query_intents", "intent_terms")
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
_REGION_ANCHOR_KEYS = ("district", "applicable_area")
_MIN_REGIONAL_QUESTION_OVERLAP_CHARS = 8
_MIN_SPECIFIC_INTENT_CHARS = 7
_INTENT_MATCH_BONUS = 0.06
_INTENT_MATCH_BONUS_MAX = 0.18
_SECTION_TYPE_INTENT_FALLBACKS = {
    "operation_entry": ("系统入口", "办理入口", "从哪里进入办理"),
    "operation_steps": ("申报流程", "申报步骤", "网上办理怎么操作", "操作步骤"),
    "operation_material_upload": ("材料上传", "上传材料", "附件上传"),
    "operation_query": ("进度查询", "结果查询", "查询办理进度"),
    "operation_url": ("在线入口", "网上办理地址", "操作手册入口"),
}
_ANSWER_HIGHLIGHT_KEYS = ("answer_highlights", "answer_key_points", "summary_points")
_STRUCTURED_ANSWER_LABELS = (
    "答案",
    "事项名称",
    "问题",
    "办理地点",
    "收费情况",
    "咨询方式",
    "办理时间",
    "受理条件",
    "在线办理地址",
)
_SERVICE_HINT_LABELS = ("事项名称", "办理地点", "收费情况", "咨询方式", "办理时间", "受理条件")
_QA_HINT_LABELS = ("问题", "答案")
_MAX_HINT_VALUE_CHARS = 700
_MAX_QA_HINT_VALUE_CHARS = 420
_SERVICE_TERM_SYNONYMS = (("社会保障卡", "社保卡"),)
_ENUMERATION_INTRO_TERMS = ("类型", "类别", "方式", "入口")
_ENUMERATION_QUERY_TERMS = ("申请", "入口", "类型", "类别", "哪些", "什么", "如何")
_NAMED_WAY_MARKERS = {1: "方式一", 2: "方式二", 3: "方式三", 4: "方式四"}
_DIAGNOSTIC_QUERY_PREVIEW_CHARS = 120
_FAST_CHUNK_QUERY_NGRAM_MIN = 2
_FAST_CHUNK_QUERY_NGRAM_MAX = 8
_FAST_CHUNK_MIN_SCORE = 2.0
_FAST_CHUNK_SCORE_NORMALIZER = 24.0
_FAST_CHUNK_INTENT_GROUPS = {
    "apply": ("申请", "办理", "申报", "领取", "怎么申请", "如何申请", "怎么办理", "如何办理", "怎么操作"),
    "materials": ("材料", "带什么", "需要什么", "所需材料", "证明材料"),
    "status": ("进度", "多久", "到账", "审核", "失败", "修改", "多少钱", "标准", "怎么算", "时限", "发放", "放款"),
}
_FAST_CHUNK_ENTITY_FAMILIES = {
    "id_card_reissue": ("身份证补领", "身份证补办", "补领身份证", "补办身份证", "居民身份证补领"),
}
_FAST_CHUNK_SQL_PREFILTER_MAX_TERMS = 40
_FAST_CHUNK_SQL_PREFILTER_MIN_ROWS = 20
_FAST_CHUNK_SQL_PREFILTER_LOW_VALUE_TERMS = {
    "哪里",
    "哪里办",
    "在哪里",
    "在哪",
    "办理",
    "怎么",
    "如何",
    "需要",
    "哪些",
    "什么",
    "多少",
    "是否",
    "可以",
    "请问",
}
_FAST_CHUNK_SQL_PREFILTER_TWO_CHAR_MARKERS = ("区", "卡", "证", "险", "金", "费", "税", "医", "车", "房", "学", "企", "户")


class _DifyErrorRoute(APIRoute):
    def get_route_handler(self):  # noqa: ANN201
        original_route_handler = super().get_route_handler()

        async def _custom_route_handler(request: Request):  # noqa: ANN202
            try:
                return await original_route_handler(request)
            except HTTPException as exc:
                return _dify_error_response(exc)

        return _custom_route_handler


def _dify_error_response(exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "error_code" in detail and "error_msg" in detail:
        payload = {"error_code": int(detail["error_code"]), "error_msg": str(detail["error_msg"])}
    else:
        msg = str(detail or "")
        if exc.status_code == 401 and "authorization header" in msg.lower():
            code = 1001
        elif exc.status_code == 401:
            code = 1002
        elif exc.status_code == 404 and "knowledge" in msg.lower():
            code = 2001
        else:
            code = int(exc.status_code or 500)
        payload = {"error_code": code, "error_msg": msg or "Dify external knowledge request failed"}
    return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)


router = APIRouter(route_class=_DifyErrorRoute, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@dataclass(frozen=True)
class _DifyActor:
    tenant_id: UUID
    account_id: str


class DifyRetrievalSetting(BaseModel):
    top_k: int = Field(default=5, ge=1, le=200)
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)


class DifyExternalKnowledgeRequest(BaseModel):
    knowledge_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    retrieval_setting: DifyRetrievalSetting = Field(default_factory=DifyRetrievalSetting)
    metadata_condition: dict[str, Any] | None = None


class DifyExternalKnowledgeRecord(BaseModel):
    content: str
    score: float
    title: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DifyExternalKnowledgeResponse(BaseModel):
    records: list[DifyExternalKnowledgeRecord]


def _split_items(raw: object) -> list[str]:
    return [p for p in _TOKEN_SPLIT_RE.split(str(raw or "").strip()) if p]


def _token_matches(provided_token: str, expected_token: str) -> bool:
    expected = str(expected_token or "").strip()
    provided = str(provided_token or "").strip()
    if not expected or not provided:
        return False
    if expected.lower().startswith("sha256:"):
        digest = expected.split(":", 1)[1].strip().lower()
        if not digest:
            return False
        provided_digest = hashlib.sha256(provided.encode("utf-8", "ignore")).hexdigest()
        return hmac.compare_digest(provided_digest, digest)
    return hmac.compare_digest(provided, expected)


def _extract_bearer_token(authorization: str | None) -> str:
    raw = str(authorization or "").strip()
    if not raw.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid Dify Authorization header")
    token = raw[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid Dify Authorization header")
    return token


def _coerce_uuid(value: object, *, label: str) -> UUID:
    try:
        return UUID(str(value or "").strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}") from exc


def _require_dify_actor(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> _DifyActor:
    if not bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", False)):
        raise HTTPException(status_code=404, detail="Dify external knowledge is disabled")

    expected_tokens = _split_items(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", ""))
    if not expected_tokens:
        raise HTTPException(status_code=503, detail="Dify external knowledge API key is not configured")

    provided = _extract_bearer_token(authorization)
    if not any(_token_matches(provided, expected) for expected in expected_tokens):
        raise HTTPException(status_code=401, detail="Invalid Dify API key")

    raw_tenant = str(
        request.headers.get(str(getattr(settings, "TENANT_HEADER", "X-Tenant-ID") or "X-Tenant-ID"))
        or getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", "")
        or getattr(settings, "DEFAULT_TENANT_ID", "")
    ).strip()
    tenant_id = _coerce_uuid(raw_tenant, label="Dify tenant id")
    account_id = str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "") or "system:dify").strip()
    if not account_id:
        raise HTTPException(status_code=503, detail="Dify external knowledge account is not configured")
    return _DifyActor(tenant_id=tenant_id, account_id=account_id)


def _dedupe_dataset_ids(dataset_ids: list[UUID]) -> list[UUID]:
    seen: set[UUID] = set()
    out: list[UUID] = []
    for dataset_id in dataset_ids:
        if dataset_id in seen:
            continue
        seen.add(dataset_id)
        out.append(dataset_id)
    return out


def _coerce_dataset_id_list(value: Any) -> list[UUID]:
    if isinstance(value, dict):
        for key in ("dataset_ids", "datasets", "dataset_id"):
            if key in value:
                return _coerce_dataset_id_list(value[key])
        raise HTTPException(status_code=400, detail="Dify knowledge mapping must include dataset_id or dataset_ids")
    if isinstance(value, str):
        return [_coerce_uuid(value, label="dataset id")]
    if isinstance(value, list | tuple | set):
        dataset_ids: list[UUID] = []
        for item in value:
            if isinstance(item, dict):
                dataset_ids.extend(_coerce_dataset_id_list(item))
            else:
                dataset_ids.append(_coerce_uuid(item, label="dataset id"))
        return _dedupe_dataset_ids(dataset_ids)
    raise HTTPException(status_code=400, detail="Dify knowledge mapping must be a dataset id or list")


def _query_terms_match(query: str, terms: Any) -> bool:
    query_text = str(query or "").strip().casefold()
    if not query_text:
        return False
    raw_terms = terms if isinstance(terms, list | tuple | set) else [terms]
    for raw in raw_terms:
        term = str(raw or "").strip().casefold()
        if term and term in query_text:
            return True
    return False


def _route_mode(route: dict[str, Any]) -> str:
    mode = str(route.get("mode") or route.get("merge") or "prepend").strip().lower()
    if mode in {"replace", "override"}:
        return "replace"
    if mode in {"append", "extend"}:
        return "append"
    return "prepend"


def _apply_query_dataset_routes(base_dataset_ids: list[UUID], mapping: dict[str, Any], *, query: str) -> list[UUID]:
    routes = mapping.get("query_routes") or mapping.get("query_dataset_routes") or mapping.get("routes")
    if not isinstance(routes, list):
        return base_dataset_ids

    current = list(base_dataset_ids)
    for raw_route in routes:
        if not isinstance(raw_route, dict):
            continue
        terms = raw_route.get("terms") or raw_route.get("query_terms") or raw_route.get("contains")
        if not _query_terms_match(query, terms):
            continue
        routed_dataset_ids = _coerce_dataset_id_list(raw_route)
        if not routed_dataset_ids:
            continue
        mode = _route_mode(raw_route)
        if mode == "replace":
            current = routed_dataset_ids
        elif mode == "append":
            current = [*current, *routed_dataset_ids]
        else:
            current = [*routed_dataset_ids, *current]
    return _dedupe_dataset_ids(current)


def _load_knowledge_map() -> dict[str, Any]:
    raw = str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON", "") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail="Dify knowledge map JSON is invalid") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=503, detail="Dify knowledge map JSON must be an object")
    return data


def _resolve_knowledge_dataset_ids(knowledge_id: str, *, query: str = "") -> list[UUID]:
    key = str(knowledge_id or "").strip()
    knowledge_map = _load_knowledge_map()
    if key in knowledge_map:
        raw_mapping = knowledge_map[key]
        dataset_ids = _coerce_dataset_id_list(raw_mapping)
        if isinstance(raw_mapping, dict):
            dataset_ids = _apply_query_dataset_routes(dataset_ids, raw_mapping, query=query)
        if not dataset_ids:
            raise HTTPException(status_code=404, detail="Dify knowledge mapping is empty")
        return dataset_ids

    try:
        return [UUID(key)]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Dify knowledge mapping not found") from exc


def _metadata_condition_to_filter(condition: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(condition, dict) or not condition:
        return None
    for key in ("metadata_filter", "filter"):
        value = condition.get(key)
        if isinstance(value, dict) and value:
            return value

    raw_conditions = condition.get("conditions")
    if not isinstance(raw_conditions, list) or not raw_conditions:
        return None

    logical_operator = str(condition.get("logical_operator") or "and").strip().lower()
    if logical_operator not in {"and", "or"}:
        raise HTTPException(status_code=400, detail="Invalid Dify metadata_condition logical_operator")

    parts: list[dict[str, Any]] = []
    for raw_condition in raw_conditions:
        if not isinstance(raw_condition, dict):
            raise HTTPException(status_code=400, detail="Invalid Dify metadata_condition condition")
        parts.append(_dify_metadata_condition_item_to_filter(raw_condition))

    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return {"$or" if logical_operator == "or" else "$and": parts}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _dify_metadata_condition_item_to_filter(condition: dict[str, Any]) -> dict[str, Any]:
    name = str(condition.get("name") or "").strip()
    op = str(condition.get("comparison_operator") or "").strip().lower()
    value = condition.get("value")
    if not name or not op:
        raise HTTPException(status_code=400, detail="Invalid Dify metadata_condition condition")

    if op == "contains":
        return {name: {"$contains": value}}
    if op == "not contains":
        return {"$not": {name: {"$contains": value}}}
    if op == "start with":
        return {name: {"$startswith": value}}
    if op == "end with":
        return {name: {"$endswith": value}}
    if op in {"is", "="}:
        return {name: {"$eq": value}}
    if op in {"is not", "≠", "!="}:
        return {name: {"$ne": value}}
    if op == "in":
        return {name: {"$in": _as_list(value)}}
    if op == "not in":
        return {name: {"$nin": _as_list(value)}}
    if op == "empty":
        return {"$or": [{name: {"$exists": False}}, {name: {"$eq": ""}}, {name: {"$eq": []}}]}
    if op == "not empty":
        return {
            "$and": [
                {name: {"$exists": True}},
                {"$not": {name: {"$eq": ""}}},
                {"$not": {name: {"$eq": []}}},
            ]
        }
    if op in {">", "after"}:
        return {name: {"$gt": value}}
    if op == "<" or op == "before":
        return {name: {"$lt": value}}
    if op in {"≥", ">="}:
        return {name: {"$gte": value}}
    if op in {"≤", "<="}:
        return {name: {"$lte": value}}

    raise HTTPException(status_code=400, detail=f"Unsupported Dify metadata comparison operator: {op}")


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


def _load_chunk_content_map(
    *,
    db: Session,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
) -> dict[str, str]:
    chunk_ids: list[UUID] = []
    seen: set[UUID] = set()
    for citation in citations or []:
        chunk_id = _citation_chunk_id(citation)
        if not chunk_id:
            continue
        try:
            parsed = UUID(chunk_id)
        except ValueError:
            continue
        if parsed in seen:
            continue
        seen.add(parsed)
        chunk_ids.append(parsed)
    if not chunk_ids:
        return {}

    try:
        rows = (
            db.query(DocumentChunk.id, DocumentChunk.content)
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.id.in_(chunk_ids),
                DocumentChunk.disabled_at.is_(None),
            )
            .all()
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to hydrate Dify chunk content; falling back to citation snippets", exc_info=True)
        return {}
    out: dict[str, str] = {}
    for chunk_id, content in rows:
        text = str(content or "").strip()
        if text:
            out[str(chunk_id)] = text
    return out


def _fast_chunk_query_terms(query: str) -> list[str]:
    normalized = _normalize_match_term(query)
    if not normalized:
        return []
    terms: set[str] = {normalized}
    max_size = min(_FAST_CHUNK_QUERY_NGRAM_MAX, len(normalized))
    for size in range(max_size, _FAST_CHUNK_QUERY_NGRAM_MIN - 1, -1):
        for start in range(0, len(normalized) - size + 1):
            term = normalized[start : start + size]
            if term:
                terms.add(term)
    return sorted(terms, key=lambda item: (-len(item), item))


def _fast_chunk_sql_prefilter_terms(query: str) -> list[str]:
    normalized = _normalize_match_term(query)
    if not normalized:
        return []

    terms: list[str] = []

    def add(raw: str) -> None:
        term = _normalize_sql_prefilter_term(raw)
        if len(term) < 2 or term in terms or term in _FAST_CHUNK_SQL_PREFILTER_LOW_VALUE_TERMS:
            return
        terms.append(term)

    for canonical, alias in _SERVICE_TERM_SYNONYMS:
        canonical_norm = _normalize_match_term(canonical)
        alias_norm = _normalize_match_term(alias)
        if (canonical_norm and canonical_norm in normalized) or (alias_norm and alias_norm in normalized):
            add(canonical)
            add(alias)

    for size in (4, 3, 5, 2):
        if len(normalized) < size:
            continue
        for start in range(0, len(normalized) - size + 1):
            term = normalized[start : start + size]
            if size == 2 and not any(marker in term for marker in _FAST_CHUNK_SQL_PREFILTER_TWO_CHAR_MARKERS):
                continue
            add(term)
            if len(terms) >= _FAST_CHUNK_SQL_PREFILTER_MAX_TERMS:
                return terms
    return terms


def _sql_like_contains_pattern(term: str) -> str:
    escaped = str(term or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _normalize_sql_prefilter_term(value: Any) -> str:
    text = str(value or "").strip().casefold()
    out: list[str] = []
    for char in text:
        if char.isspace():
            continue
        if re.match(r"[\W_]", char, flags=re.UNICODE):
            continue
        out.append(char)
    return "".join(out)


def _fast_chunk_metadata_values(metadata: dict[str, Any]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    layers = [metadata, *[metadata.get(key) for key in _PUBLIC_METADATA_VIEW_KEYS]]
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        for key in (
            *_METADATA_ANCHOR_KEYS,
            *_RETRIEVAL_INTENT_KEYS,
            *_REGION_ANCHOR_KEYS,
            *_ANSWER_HIGHLIGHT_KEYS,
            "category_path",
            "category_leaf",
            "section_type",
            "chunk_kind",
            "source_file",
            "knowledge_section",
            "gov_knowledge_type",
        ):
            for term in _metadata_terms(layer.get(key)):
                values.append((key, term))
    return values


def _fast_chunk_intent_groups(text: str) -> set[str]:
    normalized = _normalize_match_term(text)
    groups: set[str] = set()
    for group, terms in _FAST_CHUNK_INTENT_GROUPS.items():
        if any(_normalize_match_term(term) in normalized for term in terms):
            groups.add(group)
    return groups


def _fast_chunk_entity_families(text: str) -> set[str]:
    normalized = _normalize_match_term(text)
    families: set[str] = set()
    for family, terms in _FAST_CHUNK_ENTITY_FAMILIES.items():
        if any(_normalize_match_term(term) in normalized for term in terms):
            families.add(family)
    return families


def _fast_chunk_intent_alignment_score(*, query: str, candidate_text: str) -> float:
    query_groups = _fast_chunk_intent_groups(query)
    if not query_groups:
        return 0.0
    candidate_groups = _fast_chunk_intent_groups(candidate_text)
    score = 0.0
    for group in query_groups:
        if group in candidate_groups:
            score += 14.0
        else:
            score -= 8.0
    if "apply" in query_groups and "status" in candidate_groups:
        score -= 24.0
    if "materials" in query_groups and "materials" not in candidate_groups:
        score -= 18.0
    return score


def _fast_chunk_entity_alignment_score(*, query: str, candidate_text: str) -> float:
    query_families = _fast_chunk_entity_families(query)
    if not query_families:
        return 0.0
    candidate_families = _fast_chunk_entity_families(candidate_text)
    missing = query_families - candidate_families
    return -12.0 * len(missing)


def _metadata_text(metadata: dict[str, Any], *keys: str) -> str:
    parts: list[str] = []
    for key in keys:
        for value in _metadata_terms(metadata.get(key)):
            parts.append(value)
    return "\n".join(parts)


def _fast_chunk_material_answer_score(*, query: str, content: str, metadata: dict[str, Any]) -> float:
    if "materials" not in _fast_chunk_intent_groups(query):
        return 0.0
    question_text = _metadata_text(metadata, "question")
    answer_text = _metadata_text(metadata, "answer", "answer_highlights", "answer_key_points")
    question_norm = _normalize_match_term(question_text)
    answer_norm = _normalize_match_term(answer_text)
    content_norm = _normalize_match_term(content)
    has_material_question = "材料" in question_norm or "材料" in content_norm
    has_material_answer = "材料" in answer_norm or any(
        term in answer_norm for term in ("居民户口簿", "身份证件", "证明材料", "居住证", "护照")
    )
    question_bonus = 26.0 if "材料" in question_norm else 0.0
    if has_material_question and has_material_answer:
        return 34.0 + question_bonus
    if has_material_question:
        return 14.0 + question_bonus
    return -24.0


def _fast_chunk_identity_key(chunk: DocumentChunk, document: Document) -> str:
    metadata = dict(getattr(chunk, "doc_metadata", None) or {})
    raw_identity = metadata.get("_record_identity")
    if isinstance(raw_identity, dict) and str(raw_identity.get("key") or "").strip():
        return str(raw_identity.get("key")).strip()
    source_record_id = str(metadata.get("source_record_id") or "").strip()
    knowledge_section = str(metadata.get("knowledge_section") or "").strip()
    if source_record_id:
        return f"{knowledge_section}|{source_record_id}"
    return f"{getattr(document, 'id', '')}:{getattr(chunk, 'chunk_index', '')}"


def _fast_chunk_candidate_score(*, query: str, content: str, metadata: dict[str, Any]) -> float:
    query_norm = _normalize_match_term(query)
    if not query_norm:
        return 0.0
    content_norm = _normalize_match_term(content)
    score = 0.0
    candidate_text = content
    metadata_values = _fast_chunk_metadata_values(metadata)
    if metadata_values:
        candidate_text = "\n".join([content, *[term for _key, term in metadata_values]])
    score += _fast_chunk_intent_alignment_score(query=query, candidate_text=candidate_text)
    score += _fast_chunk_entity_alignment_score(query=query, candidate_text=candidate_text)
    score += _fast_chunk_material_answer_score(query=query, content=content, metadata=metadata)

    for key, raw_term in metadata_values:
        term = _normalize_match_term(raw_term)
        if len(term) < 2:
            continue
        if term == query_norm:
            score += 18.0
        elif term in query_norm:
            score += 8.0 + min(len(term), 16) / 2.0
        elif query_norm in term:
            score += 7.0 + min(len(query_norm), 16) / 3.0
        else:
            overlap = _longest_common_substring_length(query_norm, term)
            if overlap >= 8:
                score += 7.0 + overlap / 2.0
            elif overlap >= 4 and key in {"question", "service_name", "case_title", "primary_alias"}:
                score += 3.0 + overlap / 2.0

        if key == "question" and len(term) >= 4:
            overlap = _longest_common_substring_length(query_norm, term)
            if overlap >= _MIN_REGIONAL_QUESTION_OVERLAP_CHARS:
                score += 8.0
        elif key in _REGION_ANCHOR_KEYS and term in query_norm:
            score += 5.0
        elif key in _RETRIEVAL_INTENT_KEYS and term in query_norm:
            score += 4.0

    seen_terms: set[str] = set()
    for term in _fast_chunk_query_terms(query):
        if term in seen_terms or len(term) < _FAST_CHUNK_QUERY_NGRAM_MIN:
            continue
        seen_terms.add(term)
        if term in content_norm:
            score += min(len(term), 8) / 2.0

    fields = _structured_fields_from_content(content)
    if fields:
        if _service_hint_matches_query(fields, metadata, query=query):
            score += 8.0
        if "答案" in fields and any(term in content_norm for term in _fast_chunk_query_terms(query)[:8]):
            score += 3.0

    return score


def _fast_chunk_score_to_relevance(score: float) -> float:
    if score <= 0:
        return 0.0
    return min(1.0, 0.35 + (score / _FAST_CHUNK_SCORE_NORMALIZER))


def _retrieve_fast_chunk_citations(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_ids: list[UUID],
    query: str,
    top_k: int,
    metadata_filter: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if metadata_filter:
        return []
    if not bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CHUNK_SEARCH_ENABLED", True)):
        return []

    max_chunks = max(100, int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CHUNK_SEARCH_MAX_CHUNKS", 6000) or 6000))
    try:
        base_query = (
            db.query(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                Document.tenant_id == tenant_id,
                Document.dataset_id.in_(dataset_ids),
                DocumentChunk.disabled_at.is_(None),
                Document.disabled_at.is_(None),
            )
            .order_by(Document.id.asc(), DocumentChunk.chunk_index.asc())
        )
        prefilter_terms = _fast_chunk_sql_prefilter_terms(query)
        rows = []
        if prefilter_terms:
            prefilter_limit = min(max_chunks, max(top_k * 120, 600))
            rows = (
                base_query.filter(
                    or_(
                        *[
                            DocumentChunk.content.ilike(_sql_like_contains_pattern(term), escape="\\")
                            for term in prefilter_terms
                        ]
                    )
                )
                .limit(prefilter_limit)
                .all()
            )
        if len(rows) < min(max(top_k, _FAST_CHUNK_SQL_PREFILTER_MIN_ROWS), max_chunks):
            rows = base_query.limit(max_chunks).all()
    except Exception:  # noqa: BLE001
        logger.warning("Dify fast chunk search failed; falling back to RAG retrieval", exc_info=True)
        return []

    ranked: list[tuple[float, DocumentChunk, Document]] = []
    for chunk, document in rows:
        metadata = dict(getattr(chunk, "doc_metadata", None) or {})
        content = str(getattr(chunk, "content", "") or "")
        score = _fast_chunk_candidate_score(query=query, content=content, metadata=metadata)
        if score < _FAST_CHUNK_MIN_SCORE:
            continue
        ranked.append((score, chunk, document))

    ranked.sort(
        key=lambda item: (
            item[0],
            -int(getattr(item[1], "chunk_index", 0) or 0),
        ),
        reverse=True,
    )
    grouped: dict[str, list[tuple[float, DocumentChunk, Document]]] = {}
    for item in ranked:
        _score, chunk, document = item
        grouped.setdefault(_fast_chunk_identity_key(chunk, document), []).append(item)
    for items in grouped.values():
        items.sort(key=lambda item: int(getattr(item[1], "chunk_index", 0) or 0))

    selected: list[tuple[float, DocumentChunk, Document]] = []
    selected_ids: set[str] = set()
    sibling_cap = max(1, min(3, int(top_k or 1)))
    for item in ranked:
        _score, chunk, document = item
        chunk_id = str(getattr(chunk, "id", "") or "")
        if chunk_id in selected_ids:
            continue
        identity = _fast_chunk_identity_key(chunk, document)
        group = grouped.get(identity) or [item]
        ordered_group = [item, *[candidate for candidate in group if str(getattr(candidate[1], "id", "") or "") != chunk_id]]
        for candidate in ordered_group[:sibling_cap]:
            candidate_chunk_id = str(getattr(candidate[1], "id", "") or "")
            if candidate_chunk_id in selected_ids:
                continue
            selected_ids.add(candidate_chunk_id)
            selected.append(candidate)
            if len(selected) >= max(top_k * 4, top_k):
                break
        if len(selected) >= max(top_k * 4, top_k):
            break

    out: list[dict[str, Any]] = []
    for score, chunk, document in selected:
        metadata = dict(getattr(chunk, "doc_metadata", None) or {})
        dataset_id = getattr(document, "dataset_id", None)
        out.append(
            {
                "chunk_content": str(getattr(chunk, "content", "") or ""),
                "relevance_score": _fast_chunk_score_to_relevance(score),
                "keyword_score": _fast_chunk_score_to_relevance(score),
                "document_name": str((getattr(document, "doc_metadata", None) or {}).get("source_path") or getattr(document, "filename", "") or ""),
                "document_id": str(getattr(document, "id", "") or ""),
                "chunk_id": str(getattr(chunk, "id", "") or ""),
                "dataset_id": str(dataset_id or ""),
                "page_number": getattr(chunk, "page_number", None),
                "metadata": metadata,
            }
        )
    return out


def _iter_record_metadata_layers(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw_metadata = record.get("metadata")
    if not isinstance(raw_metadata, dict):
        return []
    layers = [raw_metadata]
    for key in _PUBLIC_METADATA_VIEW_KEYS:
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


def _request_client_ip(request: Request) -> str:
    forwarded_for = str(request.headers.get("x-forwarded-for") or "").strip()
    if forwarded_for:
        first = forwarded_for.split(",", 1)[0].strip()
        if first:
            return first
    return str(getattr(getattr(request, "client", None), "host", "") or "").strip()


def _diagnostic_query_hash(query: str) -> str:
    text = str(query or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:16]


def _diagnostic_query_preview(query: str) -> str:
    text = " ".join(str(query or "").split())
    if len(text) <= _DIAGNOSTIC_QUERY_PREVIEW_CHARS:
        return text
    return f"{text[:_DIAGNOSTIC_QUERY_PREVIEW_CHARS].rstrip()}..."


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


def _structured_fields_from_content(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in str(content or "").splitlines():
        parts = _field_line_parts(line)
        if parts is None:
            continue
        label, value = parts
        if label not in _STRUCTURED_ANSWER_LABELS or label in fields:
            continue
        limit = _MAX_QA_HINT_VALUE_CHARS if label == "答案" else _MAX_HINT_VALUE_CHARS
        fields[label] = _clamp_hint_value(value, limit=limit)
    return fields


def _metadata_answer_highlights(metadata: dict[str, Any]) -> list[str]:
    highlights: list[str] = []
    seen: set[str] = set()
    for layer in [metadata, *[metadata.get(key) for key in _PUBLIC_METADATA_VIEW_KEYS]]:
        if not isinstance(layer, dict):
            continue
        for key in _ANSWER_HIGHLIGHT_KEYS:
            for value in _metadata_terms(layer.get(key)):
                text = _clamp_hint_value(value)
                if not text or text in seen:
                    continue
                seen.add(text)
                highlights.append(text)
    return highlights


def _normalize_match_term(value: Any) -> str:
    text = str(value or "").strip().casefold()
    for source, target in _SERVICE_TERM_SYNONYMS:
        text = text.replace(source.casefold(), target.casefold())
    out: list[str] = []
    for char in text:
        if char.isspace():
            continue
        if re.match(r"[\W_]", char, flags=re.UNICODE):
            continue
        out.append(char)
    return "".join(out)


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
    return any(region in query_term for region in _record_region_terms(record))


def _service_candidate_terms(fields: dict[str, str], metadata: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in (fields.get("事项名称"),):
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    for layer in [metadata, *[metadata.get(key) for key in _PUBLIC_METADATA_VIEW_KEYS]]:
        if not isinstance(layer, dict):
            continue
        for key in ("service_name", "service_aliases", "aliases", "primary_alias"):
            for value in _metadata_terms(layer.get(key)):
                if value in seen:
                    continue
                seen.add(value)
                out.append(value)
    return out


def _service_hint_matches_query(fields: dict[str, str], metadata: dict[str, Any], *, query: str) -> bool:
    query_term = _normalize_match_term(query)
    if not query_term:
        return True
    for candidate in _service_candidate_terms(fields, metadata):
        term = _normalize_match_term(candidate)
        if len(term) >= 4 and (term in query_term or query_term in term):
            return True
    return False


def _answer_hints_from_fields(fields: dict[str, str], *, query: str = "") -> list[str]:
    if "答案" in fields:
        return [f"{label}：{fields[label]}" for label in _QA_HINT_LABELS if fields.get(label)]
    if "事项名称" in fields or "办理地点" in fields:
        service_bits = [f"{label}：{fields[label]}" for label in _SERVICE_HINT_LABELS if fields.get(label)]
        question = str(query or "").strip()
        if question:
            return [f"问题：{question}", f"答案：{'；'.join(service_bits)}"]
        return service_bits
    return [f"{label}：{value}" for label, value in fields.items()]


def _find_numbered_marker(text: str, number: int, *, start: int) -> tuple[int, str]:
    markers = [
        f"{number}.",
        f"{number}、",
        f"{number}．",
        f"{number})",
        f"{number}）",
        f"({number})",
        f"（{number}）",
    ]
    named_marker = _NAMED_WAY_MARKERS.get(number)
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


def _extract_numbered_option_terms(text: str, *, max_terms: int = 4) -> list[str]:
    normalized = " ".join(str(text or "").split())
    terms: list[str] = []
    cursor = 0
    for number in range(1, max_terms + 1):
        marker_index, marker = _find_numbered_marker(normalized, number, start=cursor)
        if marker_index < 0:
            break
        start = marker_index + len(marker)
        while start < len(normalized) and (normalized[start].isspace() or normalized[start] in "，、,:："):
            start += 1
        end = start
        stop_chars = "（(：:；;。"
        if marker.startswith("方式"):
            stop_chars += "，,"
        while end < len(normalized) and normalized[end] not in stop_chars:
            end += 1
        term = normalized[start:end].strip()
        if 2 <= len(term) <= 40:
            terms.append(term)
        cursor = end
    return terms


def _enumerated_answer_hints(content: str, *, query: str = "") -> list[str]:
    text = str(content or "").strip()
    if not text:
        return []
    first_marker_index, marker = _find_numbered_marker(" ".join(text.split()), 1, start=0)
    if first_marker_index < 0:
        return []
    prefix = " ".join(text.split())[:first_marker_index][-90:]
    query_text = str(query or "").strip()
    if not any(term in prefix for term in _ENUMERATION_INTRO_TERMS) and not any(
        marker.startswith(term) for term in _ENUMERATION_INTRO_TERMS
    ):
        return []
    if query_text and not any(term in query_text for term in _ENUMERATION_QUERY_TERMS):
        return []
    terms = _extract_numbered_option_terms(text)
    if len(terms) < 2:
        return []
    return [f"必答要点：回答申请/入口/类型类问题时必须保留这些选项名称：{'、'.join(terms)}"]


def _content_with_answer_hints(content: str, metadata: dict[str, Any], *, query: str = "") -> str:
    body = str(content or "").strip()
    if not body:
        return body
    enumerated_hints = _enumerated_answer_hints(body, query=query)
    enumerated_prefix = "；".join(enumerated_hints)
    if body.startswith("答案要点："):
        if enumerated_prefix and not body.startswith(enumerated_prefix):
            return f"{enumerated_prefix}\n\n{body}"
        return body
    fields = _structured_fields_from_content(body)
    if ("事项名称" in fields or "办理地点" in fields) and not _service_hint_matches_query(
        fields,
        metadata,
        query=query,
    ):
        return body
    hints = _metadata_answer_highlights(metadata) or _answer_hints_from_fields(fields, query=query)
    if not hints and not enumerated_prefix:
        return body
    if enumerated_prefix and not hints:
        return f"{enumerated_prefix}\n\n原始证据：\n{body}"
    if enumerated_prefix:
        return f"{enumerated_prefix}\n\n答案要点：{'；'.join(hints)}\n\n原始证据：\n{body}"
    return f"答案要点：{'；'.join(hints)}\n\n原始证据：\n{body}"


def _record_retrieval_intents(record: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for metadata in _iter_record_metadata_layers(record):
        for key in _RETRIEVAL_INTENT_KEYS:
            for term in _metadata_terms(metadata.get(key)):
                if term in seen:
                    continue
                seen.add(term)
                out.append(term)
        section_type = str(metadata.get("section_type") or metadata.get("chunk_kind") or "").strip()
        if section_type.startswith("one_thing_"):
            section_type = section_type.removeprefix("one_thing_")
        for term in _SECTION_TYPE_INTENT_FALLBACKS.get(section_type, ()):
            if term in seen:
                continue
            seen.add(term)
            out.append(term)
    return out


def _is_specific_intent_term(term: str) -> bool:
    text = str(term or "").strip()
    return len(text) >= _MIN_SPECIFIC_INTENT_CHARS


def _record_intent_bonus(record: dict[str, Any], *, query: str) -> float:
    query_text = str(query or "").casefold()
    if not query_text:
        return 0.0
    matches = 0
    for term in _record_retrieval_intents(record):
        if not _is_specific_intent_term(term):
            continue
        folded = term.casefold()
        if folded and (folded in query_text or query_text in folded):
            matches += 1
    return min(_INTENT_MATCH_BONUS * matches, _INTENT_MATCH_BONUS_MAX)


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
                if len(candidate) < 4:
                    continue
                if candidate == query_term:
                    best = max(best, 0.14)
                elif candidate in query_term or query_term in candidate:
                    best = max(best, 0.08)
                elif key == "question" and has_query_region:
                    overlap = _longest_common_substring_length(query_term, candidate)
                    if overlap >= _MIN_REGIONAL_QUESTION_OVERLAP_CHARS:
                        best = max(best, 0.12)
    return best


def _sort_records_for_query(records: list[dict[str, Any]], *, query: str) -> None:
    records.sort(
        key=lambda item: (
            float(item.get("score") or 0.0)
            + _record_metadata_anchor_bonus(item, query=query)
            + _record_intent_bonus(item, query=query)
        ),
        reverse=True,
    )


def _citation_to_dify_record(citation: dict[str, Any], *, dataset_id: UUID | None, query: str = "") -> dict[str, Any]:
    content = _first_non_empty(citation, _CONTENT_KEYS)
    title = _first_non_empty(citation, _TITLE_KEYS) or "Untitled"

    raw_metadata = citation.get("metadata")
    metadata: dict[str, Any] = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    resolved_dataset_id = _citation_dataset_id(citation, fallback_dataset_id=dataset_id)
    if resolved_dataset_id is not None:
        metadata["dataset_id"] = str(resolved_dataset_id)
    for key in _METADATA_KEYS:
        value = citation.get(key)
        if value is not None and value != "":
            metadata[key] = value
    content = _content_with_answer_hints(content, metadata, query=query)

    return {
        "content": content,
        "score": _citation_score(citation),
        "title": title,
        "metadata": metadata,
    }


async def _retrieve_dataset_citations(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_ids: list[UUID],
    query: str,
    top_k: int,
    score_threshold: float,
    metadata_filter: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from app.api.v1.rag import EvidenceRetrieveRequest, retrieve_evidence

    rag_config = ChatRAGConfig(
        top_k=top_k,
        score_threshold=score_threshold,
        retrieval_mode="hybrid",
        visible_evidence_only=True,
        metadata_filter=metadata_filter,
        enable_reranker=False,
        reranker_provider="none",
        reranker_top_n=max(1, int(top_k or 1)),
    )

    response = await retrieve_evidence(
        body=EvidenceRetrieveRequest(query=query, dataset_ids=dataset_ids, rag_config=rag_config),
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    return list(response.citations or [])


@router.post("/retrieval", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def retrieve_external_knowledge(
    request: Request,
    body: DifyExternalKnowledgeRequest,
    actor: Annotated[_DifyActor, Depends(_require_dify_actor)],
    db: Annotated[Session, Depends(get_db)],
) -> DifyExternalKnowledgeResponse:
    started = time.perf_counter()
    dataset_ids = _resolve_knowledge_dataset_ids(body.knowledge_id, query=body.query)
    configured_max = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX", 5) or 5)
    top_k = max(1, min(int(body.retrieval_setting.top_k), configured_max))
    score_threshold = _clamp_score(body.retrieval_setting.score_threshold)
    metadata_filter = _metadata_condition_to_filter(body.metadata_condition)
    log_extra_base = {
        "event": "dify_external_retrieval",
        "client_ip": _request_client_ip(request),
        "knowledge_id": str(body.knowledge_id or "").strip(),
        "query_hash": _diagnostic_query_hash(body.query),
        "query_preview": _diagnostic_query_preview(body.query),
        "query_chars": len(str(body.query or "")),
        "top_k": top_k,
        "score_threshold": score_threshold,
        "dataset_count": len(dataset_ids),
        "metadata_filter": bool(metadata_filter),
    }

    records: list[dict[str, Any]] = []
    citation_count = 0
    retrieval_path = "rag"
    try:
        citations = _retrieve_fast_chunk_citations(
            db=db,
            tenant_id=actor.tenant_id,
            dataset_ids=dataset_ids,
            query=body.query,
            top_k=top_k,
            metadata_filter=metadata_filter,
        )
        if citations:
            retrieval_path = "fast_chunk"
        else:
            citations = await _retrieve_dataset_citations(
                db=db,
                tenant_id=actor.tenant_id,
                account_id=actor.account_id,
                dataset_ids=dataset_ids,
                query=body.query,
                top_k=top_k,
                score_threshold=score_threshold,
                metadata_filter=metadata_filter,
            )
        citation_count = len(citations)
        fallback_dataset_id = dataset_ids[0] if dataset_ids else None
        chunk_content_map = _load_chunk_content_map(db=db, tenant_id=actor.tenant_id, citations=citations)
        for citation in citations:
            chunk_id = _citation_chunk_id(citation)
            if chunk_id and chunk_content_map.get(chunk_id):
                citation = {**citation, "content": chunk_content_map[chunk_id]}
            record = _citation_to_dify_record(citation, dataset_id=fallback_dataset_id, query=body.query)
            if str(record.get("content") or "").strip():
                records.append(record)

        _sort_records_for_query(records, query=body.query)
        response_records = [DifyExternalKnowledgeRecord(**record) for record in records[:top_k]]
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        record_count = len(response_records)
        logger.info(
            "Dify external retrieval completed client_ip=%s knowledge_id=%s query_hash=%s "
            "query_preview=%r top_k=%s score_threshold=%s dataset_count=%s citations=%s records=%s "
            "elapsed_ms=%s metadata_filter=%s retrieval_path=%s",
            log_extra_base["client_ip"],
            log_extra_base["knowledge_id"],
            log_extra_base["query_hash"],
            log_extra_base["query_preview"],
            top_k,
            score_threshold,
            len(dataset_ids),
            citation_count,
            record_count,
            elapsed_ms,
            bool(metadata_filter),
            retrieval_path,
            extra={
                **log_extra_base,
                "phase": "finished",
                "citation_count": citation_count,
                "record_count": record_count,
                "elapsed_ms": elapsed_ms,
                "retrieval_path": retrieval_path,
            },
        )
        return DifyExternalKnowledgeResponse(records=response_records)
    except Exception:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.exception(
            "Dify external retrieval failed client_ip=%s knowledge_id=%s query_hash=%s "
            "query_preview=%r top_k=%s score_threshold=%s dataset_count=%s citations=%s records=%s "
            "elapsed_ms=%s metadata_filter=%s retrieval_path=%s",
            log_extra_base["client_ip"],
            log_extra_base["knowledge_id"],
            log_extra_base["query_hash"],
            log_extra_base["query_preview"],
            top_k,
            score_threshold,
            len(dataset_ids),
            citation_count,
            len(records),
            elapsed_ms,
            bool(metadata_filter),
            retrieval_path,
            extra={
                **log_extra_base,
                "phase": "failed",
                "citation_count": citation_count,
                "record_count": len(records),
                "elapsed_ms": elapsed_ms,
                "retrieval_path": retrieval_path,
            },
        )
        raise
