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
from dataclasses import dataclass
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
_MIN_SPECIFIC_INTENT_CHARS = 7
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
_ENUMERATION_QUERY_TERMS = ("申请", "入口", "类型", "类别", "哪些", "什么")


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
    markers = (
        f"{number}.",
        f"{number}、",
        f"{number}．",
        f"{number})",
        f"{number}）",
        f"({number})",
        f"（{number}）",
    )
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
        while start < len(normalized) and normalized[start].isspace():
            start += 1
        end = start
        while end < len(normalized) and normalized[end] not in "（(：:；;。":
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
    first_marker_index, _marker = _find_numbered_marker(" ".join(text.split()), 1, start=0)
    if first_marker_index < 0:
        return []
    prefix = " ".join(text.split())[:first_marker_index][-90:]
    query_text = str(query or "").strip()
    if not any(term in prefix for term in _ENUMERATION_INTRO_TERMS):
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
    return min(0.02 * matches, 0.08)


def _sort_records_for_query(records: list[dict[str, Any]], *, query: str) -> None:
    records.sort(
        key=lambda item: float(item.get("score") or 0.0) + _record_intent_bonus(item, query=query),
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
    body: DifyExternalKnowledgeRequest,
    actor: Annotated[_DifyActor, Depends(_require_dify_actor)],
    db: Annotated[Session, Depends(get_db)],
) -> DifyExternalKnowledgeResponse:
    dataset_ids = _resolve_knowledge_dataset_ids(body.knowledge_id, query=body.query)
    configured_max = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX", 50) or 50)
    top_k = max(1, min(int(body.retrieval_setting.top_k), configured_max))
    score_threshold = _clamp_score(body.retrieval_setting.score_threshold)
    metadata_filter = _metadata_condition_to_filter(body.metadata_condition)

    records: list[dict[str, Any]] = []
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
    return DifyExternalKnowledgeResponse(records=[DifyExternalKnowledgeRecord(**record) for record in records[:top_k]])
