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


def _citation_to_dify_record(citation: dict[str, Any], *, dataset_id: UUID | None) -> dict[str, Any]:
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
        record = _citation_to_dify_record(citation, dataset_id=fallback_dataset_id)
        if str(record.get("content") or "").strip():
            records.append(record)

    _sort_records_for_query(records, query=body.query)
    return DifyExternalKnowledgeResponse(records=[DifyExternalKnowledgeRecord(**record) for record in records[:top_k]])
