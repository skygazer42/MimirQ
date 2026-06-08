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
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.schemas.chat import ChatRAGConfig
from app.core.config import settings
from app.core.database import get_db
from app.models.document import DocumentChunk
from app.rag.pipeline_plugins.contracts import DISPLAY_METADATA_KEY, EVALUABLE_METADATA_KEY, INDEXED_METADATA_KEY
from app.rag.retrieval.planner import (
    DatasetRouteHint,
    DatasetScopePlan,
    compact_high_confidence_items,
    normalize_route_mode,
    plan_dataset_scope,
    resolve_internal_candidate_top_k,
    retrieval_policy_fallback_multiplier,
    retrieval_policy_query_terms,
    retrieval_policy_response_compaction,
)
from app.rag.retrieval.plugin_policy import (
    filter_records_by_retrieval_policy_alignment,
    record_retrieval_policy_bonus,
    records_retrieval_policy_diagnostics,
)

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
    "kg_pagerank",
    "kg_path_length",
    "kg_shared_events",
    "kg_evidence_anchored",
    "kg_path",
    "kg_path_provenance",
    "kg_duplicate_candidate",
    "kg_edge_conf_low",
    "kg_edge_conf_mid",
    "kg_edge_conf_high",
)
_PUBLIC_METADATA_VIEW_KEYS = (EVALUABLE_METADATA_KEY, DISPLAY_METADATA_KEY)
_RETRIEVAL_METADATA_VIEW_KEYS = (INDEXED_METADATA_KEY, *_PUBLIC_METADATA_VIEW_KEYS)
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
_ENUMERATION_INTRO_TERMS = ("类型", "类别", "方式", "入口")
_ENUMERATION_QUERY_TERMS = ("申请", "入口", "类型", "类别", "哪些", "什么", "如何")
_NAMED_WAY_MARKERS = {1: "方式一", 2: "方式二", 3: "方式三", 4: "方式四"}
_DIAGNOSTIC_QUERY_PREVIEW_CHARS = 120


def _resolve_internal_candidate_top_k(requested_top_k: int) -> int:
    return resolve_internal_candidate_top_k(
        requested_top_k,
        minimum=getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN", 20),
        multiplier=getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER", 4),
        maximum=getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX", 50),
    )


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
    # MimirQ-compatible extension for direct gates and internal probes.
    # Dify's standard payload can omit these fields; None keeps env/default behavior.
    enable_kg_query_expansion: bool | None = None
    enable_kg_chunk_injection: bool | None = None
    kg_chunk_injection_max_chunks: int | None = Field(default=None, ge=0, le=50)
    enable_kg_chunk_boost: bool | None = None
    kg_chunk_boost_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    kg_chunk_boost_max_promoted: int | None = Field(default=None, ge=0, le=20)


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


def _route_hint_terms(raw_route: dict[str, Any]) -> tuple[str, ...]:
    raw_terms = raw_route.get("terms") or raw_route.get("query_terms") or raw_route.get("contains")
    terms = raw_terms if isinstance(raw_terms, list | tuple | set) else [raw_terms]
    return tuple(str(term or "").strip() for term in terms if str(term or "").strip())


def _apply_query_dataset_routes(base_dataset_ids: list[UUID], mapping: dict[str, Any], *, query: str) -> list[UUID]:
    return list(_plan_query_dataset_scope(base_dataset_ids, mapping, query=query).dataset_ids)


def _knowledge_mapping_plugin_refs(mapping: Any) -> tuple[str, ...]:
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


def _retrieval_policy_filter_fields_for_plugin_refs(plugin_refs: tuple[str, ...]) -> set[str] | None:
    if not plugin_refs:
        return None
    out: set[str] = set()
    for plugin_ref in plugin_refs:
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        raw_fields = policy.get("filter_fields") if isinstance(policy, dict) else None
        if not isinstance(raw_fields, list | tuple | set):
            continue
        for raw in raw_fields:
            field_name = str(raw or "").strip()
            if field_name:
                out.add(field_name)
    return out


def _retrieval_policy_fallback_multiplier_for_plugin_refs(plugin_refs: tuple[str, ...]) -> int:
    multiplier = 1
    for plugin_ref in plugin_refs:
        multiplier = max(
            multiplier,
            retrieval_policy_fallback_multiplier(_retrieval_policy_for_plugin_ref(plugin_ref)),
        )
    return multiplier


def _resolve_knowledge_policy_filter_fields(knowledge_id: str) -> set[str] | None:
    key = str(knowledge_id or "").strip()
    raw_mapping = _load_knowledge_map().get(key)
    return _retrieval_policy_filter_fields_for_plugin_refs(_knowledge_mapping_plugin_refs(raw_mapping))


def _resolve_knowledge_policy_fallback_multiplier(knowledge_id: str) -> int:
    key = str(knowledge_id or "").strip()
    raw_mapping = _load_knowledge_map().get(key)
    return _retrieval_policy_fallback_multiplier_for_plugin_refs(_knowledge_mapping_plugin_refs(raw_mapping))


def _resolve_knowledge_policy_plugin_refs(knowledge_id: str) -> tuple[str, ...]:
    key = str(knowledge_id or "").strip()
    raw_mapping = _load_knowledge_map().get(key)
    return _knowledge_mapping_plugin_refs(raw_mapping)


def _apply_policy_fallback_candidate_multiplier(candidate_top_k: int, *, multiplier: int) -> int:
    safe_candidate_top_k = max(1, int(candidate_top_k or 1))
    safe_multiplier = max(1, int(multiplier or 1))
    try:
        configured_max = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX", 50) or 50)
    except (TypeError, ValueError):
        configured_max = 50
    max_candidates = max(safe_candidate_top_k, configured_max)
    return min(max_candidates, safe_candidate_top_k * safe_multiplier)


def _plan_query_dataset_scope(base_dataset_ids: list[UUID], mapping: dict[str, Any], *, query: str) -> DatasetScopePlan:
    routes = mapping.get("query_routes") or mapping.get("query_dataset_routes") or mapping.get("routes")
    if not isinstance(routes, list):
        return plan_dataset_scope(base_dataset_ids=base_dataset_ids, query=query)

    strict_routes = bool(mapping.get("strict_query_routes") or mapping.get("query_routes_strict"))
    route_hints: list[DatasetRouteHint] = []
    for raw_route in routes:
        if not isinstance(raw_route, dict):
            continue
        routed_dataset_ids = _coerce_dataset_id_list(raw_route)
        if not routed_dataset_ids:
            continue
        route_hints.append(
            DatasetRouteHint(
                terms=_route_hint_terms(raw_route),
                dataset_ids=tuple(routed_dataset_ids),
                mode=normalize_route_mode(raw_route.get("mode") or raw_route.get("merge") or "prepend"),
            )
        )
    return plan_dataset_scope(
        base_dataset_ids=base_dataset_ids,
        route_hints=route_hints,
        query=query,
        strict_routes=strict_routes,
        matched_replace_routes_as_primary_scope=True,
    )


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
    return list(_resolve_knowledge_dataset_scope(knowledge_id, query=query).dataset_ids)


def _resolve_knowledge_dataset_scope(knowledge_id: str, *, query: str = "") -> DatasetScopePlan:
    key = str(knowledge_id or "").strip()
    knowledge_map = _load_knowledge_map()
    if key in knowledge_map:
        raw_mapping = knowledge_map[key]
        dataset_ids = _coerce_dataset_id_list(raw_mapping)
        if isinstance(raw_mapping, dict):
            plan = _plan_query_dataset_scope(dataset_ids, raw_mapping, query=query)
        else:
            plan = plan_dataset_scope(base_dataset_ids=dataset_ids, query=query)
        if not plan.dataset_ids:
            raise HTTPException(status_code=404, detail="Dify knowledge mapping is empty")
        return plan

    try:
        return plan_dataset_scope(base_dataset_ids=[UUID(key)], query=query)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Dify knowledge mapping not found") from exc


def _metadata_condition_to_filter(
    condition: dict[str, Any] | None,
    *,
    allowed_fields: set[str] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(condition, dict) or not condition:
        return None
    for key in ("metadata_filter", "filter"):
        value = condition.get(key)
        if isinstance(value, dict) and value:
            _validate_metadata_filter_fields(value, allowed_fields=allowed_fields)
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
    metadata_filter = parts[0] if len(parts) == 1 else {"$or" if logical_operator == "or" else "$and": parts}
    _validate_metadata_filter_fields(metadata_filter, allowed_fields=allowed_fields)
    return metadata_filter


def _metadata_filter_field_names(metadata_filter: Any) -> set[str]:
    if not isinstance(metadata_filter, dict):
        return set()
    out: set[str] = set()
    for key, value in metadata_filter.items():
        name = str(key or "").strip()
        if not name:
            continue
        if name in {"$and", "$or"}:
            values = value if isinstance(value, list | tuple | set) else [value]
            for item in values:
                out.update(_metadata_filter_field_names(item))
            continue
        if name == "$not":
            out.update(_metadata_filter_field_names(value))
            continue
        if name.startswith("$"):
            continue
        out.add(name)
    return out


def _validate_metadata_filter_fields(metadata_filter: dict[str, Any], *, allowed_fields: set[str] | None) -> None:
    if allowed_fields is None:
        return
    disallowed = sorted(field_name for field_name in _metadata_filter_field_names(metadata_filter) if field_name not in allowed_fields)
    if disallowed:
        raise HTTPException(
            status_code=400,
            detail=f"Dify metadata filter field is not allowed by plugin retrieval_policy: {disallowed[0]}",
        )


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
    policy = _retrieval_policy_for_plugin_ref(plugin_ref)
    for term in retrieval_policy_query_terms(policy, metadata_layers=metadata_layers):
        if term in seen:
            continue
        seen.add(term)
        out.append(term)
    return out


def _is_specific_intent_term(term: str) -> bool:
    text = str(term or "").strip()
    return len(text) >= _MIN_SPECIFIC_INTENT_CHARS


def _record_intent_bonus(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    query_text = str(query or "").casefold()
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


@lru_cache(maxsize=128)
def _retrieval_policy_for_plugin_ref(plugin_ref: str) -> dict[str, Any]:
    ref = str(plugin_ref or "").strip()
    if not ref.startswith("plugin:"):
        return {}
    try:
        from app.rag.pipeline_plugins.registry import resolve_registered_plugin_descriptor

        descriptor = resolve_registered_plugin_descriptor(ref)
    except Exception:  # noqa: BLE001
        return {}
    policy = getattr(descriptor, "retrieval_policy", None)
    if isinstance(policy, dict) and policy.get("schema") == "mimirq.retrieval_policy.v1":
        return dict(policy)
    return {}


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
        policy_resolver=_retrieval_policy_for_plugin_ref,
    )


def _response_compaction_for_records(
    records: list[dict[str, Any]],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    refs: list[str] = []
    seen: set[str] = set()
    for ref in policy_plugin_refs:
        text = str(ref or "").strip()
        if text and text not in seen:
            seen.add(text)
            refs.append(text)
    for record in records or ():
        text = _record_plugin_ref(record, fallback_plugin_refs=policy_plugin_refs)
        if text and text not in seen:
            seen.add(text)
            refs.append(text)
    for ref in refs:
        compaction = retrieval_policy_response_compaction(_retrieval_policy_for_plugin_ref(ref))
        if bool(compaction.get("enabled")):
            return compaction
    return {"enabled": False}


def _sort_records_for_query(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> None:
    records.sort(key=lambda item: _record_rank_score(item, query=query, policy_plugin_refs=policy_plugin_refs), reverse=True)


def _record_rank_score(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    return (
        float(record.get("score") or 0.0)
        + _record_metadata_anchor_bonus(record, query=query)
        + _record_intent_bonus(record, query=query, policy_plugin_refs=policy_plugin_refs)
        + record_retrieval_policy_bonus(
            record,
            query=query,
            plugin_ref_for_record=lambda item: _record_plugin_ref(item, fallback_plugin_refs=policy_plugin_refs),
            metadata_layers_for_record=_iter_record_metadata_layers,
            policy_resolver=_retrieval_policy_for_plugin_ref,
        )
    )


def _compact_records_for_response(
    records: list[dict[str, Any]],
    *,
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    limited = list(records or [])[: max(1, int(top_k or 1))]
    if not limited:
        return []
    compaction_enabled = bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED", True))
    policy_compaction = _response_compaction_for_records(limited, policy_plugin_refs=policy_plugin_refs)
    if compaction_enabled and bool(policy_compaction.get("enabled")):
        limited = filter_records_by_retrieval_policy_alignment(
            limited,
            query=query,
            plugin_ref_for_record=lambda item: _record_plugin_ref(item, fallback_plugin_refs=policy_plugin_refs),
            metadata_layers_for_record=_iter_record_metadata_layers,
            policy_resolver=_retrieval_policy_for_plugin_ref,
        )
    if not limited:
        return []
    compacted = compact_high_confidence_items(
        limited,
        scores=[_record_rank_score(record, query=query, policy_plugin_refs=policy_plugin_refs) for record in limited],
        top_k=top_k,
        enabled=compaction_enabled,
        min_top_score=float(
            policy_compaction.get("min_top_score")
            if bool(policy_compaction.get("enabled"))
            else getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE", 0.7)
            or 0.7
        ),
        relative_score_floor=float(
            policy_compaction.get("relative_score_floor")
            if bool(policy_compaction.get("enabled"))
            else getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR", 0.65)
            or 0.65
        ),
        min_items=int(
            policy_compaction.get("min_records")
            if bool(policy_compaction.get("enabled"))
            else getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS", 1)
            or 1
        ),
    )
    return list(compacted)


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


def _record_dedupe_key(record: dict[str, Any]) -> tuple[str, str, str]:
    metadata = record.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    chunk_id = str(metadata.get("chunk_id") or "").strip()
    document_id = str(metadata.get("document_id") or "").strip()
    content = str(record.get("content") or "").strip()
    title = str(record.get("title") or "").strip()
    return (chunk_id, document_id, content or title)


def _dedupe_records(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
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
    min_records = max(1, int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS", 1) or 1))
    if len(records) < min_records:
        return False
    min_top_score = float(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE", 0.45) or 0.0)
    if min_top_score <= 0:
        return True
    top_score = max(
        (_record_rank_score(record, query=query, policy_plugin_refs=policy_plugin_refs) for record in records),
        default=0.0,
    )
    return top_score >= min_top_score


def _records_from_citations(
    *,
    db: Session,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
    fallback_dataset_id: UUID | None,
    query: str,
) -> list[dict[str, Any]]:
    chunk_content_map = _load_chunk_content_map(db=db, tenant_id=tenant_id, citations=citations)
    records: list[dict[str, Any]] = []
    for citation in citations:
        chunk_id = _citation_chunk_id(citation)
        if chunk_id and chunk_content_map.get(chunk_id):
            citation = {**citation, "content": chunk_content_map[chunk_id]}
        record = _citation_to_dify_record(citation, dataset_id=fallback_dataset_id, query=query)
        if str(record.get("content") or "").strip():
            records.append(record)
    return records


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
    requested_top_k: int | None = None,
    enable_kg_query_expansion: bool | None = None,
    enable_kg_chunk_injection: bool | None = None,
    kg_chunk_injection_max_chunks: int | None = None,
    enable_kg_chunk_boost: bool | None = None,
    kg_chunk_boost_weight: float | None = None,
    kg_chunk_boost_max_promoted: int | None = None,
) -> list[dict[str, Any]]:
    from app.api.v1.rag import EvidenceRetrieveRequest, retrieve_evidence

    evidence_top_k = max(1, int(top_k or 1))
    if requested_top_k is None:
        evidence_top_k = _resolve_internal_candidate_top_k(evidence_top_k)

    kg_query_expansion_enabled = (
        _dify_kg_bool("DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED", False)
        if enable_kg_query_expansion is None
        else bool(enable_kg_query_expansion)
    )
    kg_chunk_injection_enabled = (
        _dify_kg_bool("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED", False)
        if enable_kg_chunk_injection is None
        else bool(enable_kg_chunk_injection)
    )
    kg_chunk_boost_enabled = (
        _dify_kg_bool("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED", False)
        if enable_kg_chunk_boost is None
        else bool(enable_kg_chunk_boost)
    )

    rag_config = ChatRAGConfig(
        top_k=evidence_top_k,
        score_threshold=score_threshold,
        retrieval_mode="hybrid",
        visible_evidence_only=True,
        metadata_filter=metadata_filter,
        enable_reranker=False,
        reranker_provider="none",
        reranker_top_n=max(1, int(evidence_top_k or 1)),
        lexical_db_hybrid_metadata_exact_fallback_enabled=True,
        metadata_exact_db_fallback_enabled=False,
        enable_kg_query_expansion=kg_query_expansion_enabled,
        enable_kg_chunk_injection=kg_chunk_injection_enabled,
        kg_chunk_injection_max_chunks=(
            _dify_kg_int("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS", 3)
            if kg_chunk_injection_max_chunks is None
            else int(kg_chunk_injection_max_chunks)
        ),
        enable_kg_chunk_boost=kg_chunk_boost_enabled,
        kg_chunk_boost_weight=(
            _dify_kg_float("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT", 0.25)
            if kg_chunk_boost_weight is None
            else float(kg_chunk_boost_weight)
        ),
        kg_chunk_boost_max_promoted=(
            _dify_kg_int("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED", 2)
            if kg_chunk_boost_max_promoted is None
            else int(kg_chunk_boost_max_promoted)
        ),
    )

    scoped_dataset_ids = _dedupe_dataset_ids(list(dataset_ids or []))
    evidence_request_kwargs: dict[str, Any] = {"query": query, "rag_config": rag_config}
    evidence_request_kwargs["dataset_ids"] = scoped_dataset_ids

    response = await retrieve_evidence(
        body=EvidenceRetrieveRequest(**evidence_request_kwargs),
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
    scope_plan = _resolve_knowledge_dataset_scope(body.knowledge_id, query=body.query)
    dataset_ids = list(scope_plan.dataset_ids)
    primary_scope_enabled = bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED", True))
    primary_dataset_ids = list(scope_plan.primary_dataset_ids if primary_scope_enabled else scope_plan.dataset_ids)
    if not primary_dataset_ids:
        primary_dataset_ids = dataset_ids
    expansion_dataset_ids = list(scope_plan.expansion_dataset_ids if primary_scope_enabled else ())
    configured_max = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX", 5) or 5)
    top_k = max(1, min(int(body.retrieval_setting.top_k), configured_max))
    candidate_top_k = _resolve_internal_candidate_top_k(top_k)
    policy_fallback_multiplier = _resolve_knowledge_policy_fallback_multiplier(body.knowledge_id)
    candidate_top_k = _apply_policy_fallback_candidate_multiplier(
        candidate_top_k,
        multiplier=policy_fallback_multiplier,
    )
    policy_plugin_refs = _resolve_knowledge_policy_plugin_refs(body.knowledge_id)
    score_threshold = _clamp_score(body.retrieval_setting.score_threshold)
    policy_filter_fields = _resolve_knowledge_policy_filter_fields(body.knowledge_id)
    metadata_filter = _metadata_condition_to_filter(body.metadata_condition, allowed_fields=policy_filter_fields)
    log_extra_base = {
        "event": "dify_external_retrieval",
        "client_ip": _request_client_ip(request),
        "knowledge_id": str(body.knowledge_id or "").strip(),
        "query_hash": _diagnostic_query_hash(body.query),
        "query_preview": _diagnostic_query_preview(body.query),
        "query_chars": len(str(body.query or "")),
        "top_k": top_k,
        "candidate_top_k": candidate_top_k,
        "policy_fallback_multiplier": policy_fallback_multiplier,
        "score_threshold": score_threshold,
        "dataset_count": len(dataset_ids),
        "primary_dataset_count": len(primary_dataset_ids),
        "expansion_dataset_count": len(expansion_dataset_ids),
        "route_count": scope_plan.route_count,
        "matched_route_count": scope_plan.matched_route_count,
        "strict_scope": scope_plan.strict_scope,
        "metadata_filter": bool(metadata_filter),
    }

    records: list[dict[str, Any]] = []
    citation_count = 0
    primary_citation_count = 0
    expansion_citation_count = 0
    retrieval_path = "rag:primary_scope" if primary_scope_enabled else "rag"
    try:
        primary_citations = await _retrieve_dataset_citations(
            db=db,
            tenant_id=actor.tenant_id,
            account_id=actor.account_id,
            dataset_ids=primary_dataset_ids,
            query=body.query,
            top_k=candidate_top_k,
            requested_top_k=top_k,
            score_threshold=score_threshold,
            metadata_filter=metadata_filter,
            enable_kg_query_expansion=body.retrieval_setting.enable_kg_query_expansion,
            enable_kg_chunk_injection=body.retrieval_setting.enable_kg_chunk_injection,
            kg_chunk_injection_max_chunks=body.retrieval_setting.kg_chunk_injection_max_chunks,
            enable_kg_chunk_boost=body.retrieval_setting.enable_kg_chunk_boost,
            kg_chunk_boost_weight=body.retrieval_setting.kg_chunk_boost_weight,
            kg_chunk_boost_max_promoted=body.retrieval_setting.kg_chunk_boost_max_promoted,
        )
        primary_citation_count = len(primary_citations)
        records.extend(
            _records_from_citations(
                db=db,
                tenant_id=actor.tenant_id,
                citations=primary_citations,
                fallback_dataset_id=primary_dataset_ids[0] if primary_dataset_ids else None,
                query=body.query,
            )
        )

        if expansion_dataset_ids and not _records_meet_primary_scope(
            records,
            query=body.query,
            policy_plugin_refs=policy_plugin_refs,
        ):
            retrieval_path = "rag:primary_scope+expansion_scope"
            expansion_citations = await _retrieve_dataset_citations(
                db=db,
                tenant_id=actor.tenant_id,
                account_id=actor.account_id,
                dataset_ids=expansion_dataset_ids,
                query=body.query,
                top_k=candidate_top_k,
                requested_top_k=top_k,
                score_threshold=score_threshold,
                metadata_filter=metadata_filter,
                enable_kg_query_expansion=body.retrieval_setting.enable_kg_query_expansion,
                enable_kg_chunk_injection=body.retrieval_setting.enable_kg_chunk_injection,
                kg_chunk_injection_max_chunks=body.retrieval_setting.kg_chunk_injection_max_chunks,
                enable_kg_chunk_boost=body.retrieval_setting.enable_kg_chunk_boost,
                kg_chunk_boost_weight=body.retrieval_setting.kg_chunk_boost_weight,
                kg_chunk_boost_max_promoted=body.retrieval_setting.kg_chunk_boost_max_promoted,
            )
            expansion_citation_count = len(expansion_citations)
            records.extend(
                _records_from_citations(
                    db=db,
                    tenant_id=actor.tenant_id,
                    citations=expansion_citations,
                    fallback_dataset_id=expansion_dataset_ids[0] if expansion_dataset_ids else None,
                    query=body.query,
                )
            )

        citation_count = primary_citation_count + expansion_citation_count
        records = _dedupe_records(records, query=body.query, policy_plugin_refs=policy_plugin_refs)
        _sort_records_for_query(records, query=body.query, policy_plugin_refs=policy_plugin_refs)
        policy_diagnostics = _records_retrieval_policy_diagnostics(
            records,
            query=body.query,
            policy_plugin_refs=policy_plugin_refs,
        )
        compacted_records = _compact_records_for_response(
            records,
            query=body.query,
            top_k=top_k,
            policy_plugin_refs=policy_plugin_refs,
        )
        response_records = [DifyExternalKnowledgeRecord(**record) for record in compacted_records]
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        record_count = len(response_records)
        logger.info(
            "Dify external retrieval completed client_ip=%s knowledge_id=%s query_hash=%s "
            "query_preview=%r top_k=%s candidate_top_k=%s score_threshold=%s dataset_count=%s "
            "primary_dataset_count=%s expansion_dataset_count=%s citations=%s primary_citations=%s "
            "expansion_citations=%s candidate_records=%s records=%s elapsed_ms=%s metadata_filter=%s "
            "retrieval_path=%s policy_records=%s policy_boosted_records=%s policy_boost_field_records=%s "
            "policy_query_expansion_records=%s policy_rerank_feature_records=%s "
            "policy_anchor_mismatch_records=%s",
            log_extra_base["client_ip"],
            log_extra_base["knowledge_id"],
            log_extra_base["query_hash"],
            log_extra_base["query_preview"],
            top_k,
            candidate_top_k,
            score_threshold,
            len(dataset_ids),
            len(primary_dataset_ids),
            len(expansion_dataset_ids),
            citation_count,
            primary_citation_count,
            expansion_citation_count,
            len(records),
            record_count,
            elapsed_ms,
            bool(metadata_filter),
            retrieval_path,
            policy_diagnostics["retrieval_policy_record_count"],
            policy_diagnostics["retrieval_policy_boosted_record_count"],
            policy_diagnostics["retrieval_policy_boost_field_record_count"],
            policy_diagnostics["retrieval_policy_query_expansion_record_count"],
            policy_diagnostics["retrieval_policy_rerank_feature_record_count"],
            policy_diagnostics["retrieval_policy_anchor_mismatch_record_count"],
            extra={
                **log_extra_base,
                "phase": "finished",
                "citation_count": citation_count,
                "primary_citation_count": primary_citation_count,
                "expansion_citation_count": expansion_citation_count,
                "candidate_record_count": len(records),
                "record_count": record_count,
                "elapsed_ms": elapsed_ms,
                "retrieval_path": retrieval_path,
                **policy_diagnostics,
            },
        )
        return DifyExternalKnowledgeResponse(records=response_records)
    except Exception:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        policy_diagnostics = _records_retrieval_policy_diagnostics(
            records,
            query=body.query,
            policy_plugin_refs=policy_plugin_refs,
        )
        logger.exception(
            "Dify external retrieval failed client_ip=%s knowledge_id=%s query_hash=%s "
            "query_preview=%r top_k=%s candidate_top_k=%s score_threshold=%s dataset_count=%s "
            "primary_dataset_count=%s expansion_dataset_count=%s citations=%s records=%s elapsed_ms=%s "
            "metadata_filter=%s retrieval_path=%s policy_records=%s policy_boosted_records=%s "
            "policy_boost_field_records=%s policy_query_expansion_records=%s "
            "policy_rerank_feature_records=%s policy_anchor_mismatch_records=%s",
            log_extra_base["client_ip"],
            log_extra_base["knowledge_id"],
            log_extra_base["query_hash"],
            log_extra_base["query_preview"],
            top_k,
            candidate_top_k,
            score_threshold,
            len(dataset_ids),
            len(primary_dataset_ids),
            len(expansion_dataset_ids),
            citation_count,
            len(records),
            elapsed_ms,
            bool(metadata_filter),
            retrieval_path,
            policy_diagnostics["retrieval_policy_record_count"],
            policy_diagnostics["retrieval_policy_boosted_record_count"],
            policy_diagnostics["retrieval_policy_boost_field_record_count"],
            policy_diagnostics["retrieval_policy_query_expansion_record_count"],
            policy_diagnostics["retrieval_policy_rerank_feature_record_count"],
            policy_diagnostics["retrieval_policy_anchor_mismatch_record_count"],
            extra={
                **log_extra_base,
                "phase": "failed",
                "citation_count": citation_count,
                "record_count": len(records),
                "elapsed_ms": elapsed_ms,
                "retrieval_path": retrieval_path,
                **policy_diagnostics,
            },
        )
        raise
