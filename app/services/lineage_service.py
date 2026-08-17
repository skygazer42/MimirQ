from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat import Conversation
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk, DocumentPermission
from app.rag.core.hashing import stable_hash
from app.services.chat_conversation_access import resolve_conversation_owner_account_id
from app.services.connector_reconcile_service import extract_connector_source_identity
from app.services.dataset_service import DatasetService
from app.services.document_access import get_allowed_document_id_sets
from app.services.jsonl_tail import read_jsonl_tail
from app.services.rbac_service import TenantPermissions, role_allows

CHUNK_RETRIEVAL_LINEAGE_SCHEMA = "mimirq.chunk_retrieval_lineage.v1"
CHUNK_LINEAGE_SCHEMA = "mimirq.lineage.chunk.v1"
ANSWER_LINEAGE_SCHEMA = "mimirq.lineage.answer.v1"


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _to_int(v: Any) -> int | None:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _safe_str(v: Any, *, max_len: int = 255) -> str | None:
    s = str(v or "").strip()
    if not s:
        return None
    return s[: max(1, int(max_len or 255))]


def _safe_dict(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, Mapping) else {}


def _safe_list(raw: Any) -> list[Any]:
    return list(raw) if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)) else []


def _read_jsonl_tail(path: Path, *, max_bytes: int) -> list[dict[str, Any]]:
    records, _truncated = read_jsonl_tail(path, max_bytes=max_bytes)
    return records


def _can_read_observability(member: Any) -> bool:
    return role_allows(
        TenantPermissions.OBSERVABILITY_READ,
        role=str(getattr(member, "role", "") or ""),
    )


def load_answer_lineage_trace(
    *,
    tenant_id: UUID,
    request_id: str,
) -> dict[str, Any] | None:
    tenant_key = str(tenant_id)
    request_key = str(request_id or "").strip()
    if not request_key or not bool(getattr(settings, "ENABLE_METRICS_LOG", False)):
        return None
    path = Path(str(getattr(settings, "METRICS_LOG_PATH", "./logs/rag_metrics.jsonl") or "./logs/rag_metrics.jsonl"))
    if not path.exists():
        return None

    records = _read_jsonl_tail(path, max_bytes=5_000_000)
    for record in reversed(records):
        if str(record.get("event") or "") != "rag_trace":
            continue
        if str(record.get("tenant_id") or "") != tenant_key:
            continue
        if str(record.get("request_id") or "").strip() == request_key:
            return dict(record)
    return None


def authorize_chunk_lineage_access(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document_id: UUID,
) -> bool:
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    if _can_read_observability(member):
        return True
    allowed_ids, _missing_ids = get_allowed_document_id_sets(
        db,
        tenant_id,
        account_id,
        [document_id],
        check_member=False,
    )
    return document_id in allowed_ids


def _trace_citation_document_ids(trace_record: Mapping[str, Any]) -> list[UUID] | None:
    doc_ids: list[UUID] = []
    seen: set[UUID] = set()
    for citation_raw in _safe_list(trace_record.get("citations")):
        citation = _safe_dict(citation_raw)
        document_id_raw = citation.get("document_id")
        document_id_text = str(document_id_raw or "").strip()
        if not document_id_text:
            continue
        try:
            document_id = UUID(document_id_text)
        except Exception:
            return None
        if document_id in seen:
            continue
        seen.add(document_id)
        doc_ids.append(document_id)
    return doc_ids


def authorize_answer_lineage_access(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    trace_record: Mapping[str, Any],
) -> bool:
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    if _can_read_observability(member):
        return True

    normalized_account_id = str(account_id or "").strip()
    owns_trace = str(trace_record.get("account_id") or "").strip() == normalized_account_id
    if not owns_trace:
        conversation_raw = _safe_str(trace_record.get("conversation_id"), max_len=120)
        if not conversation_raw:
            return False

        try:
            conversation_id = UUID(conversation_raw)
        except Exception:
            return False

        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
            .first()
        )
        if conversation is None:
            return False
        owns_trace = resolve_conversation_owner_account_id(conversation) == normalized_account_id
    if not owns_trace:
        return False

    citation_doc_ids = _trace_citation_document_ids(trace_record)
    if citation_doc_ids is None:
        return False
    if not citation_doc_ids:
        return True

    allowed_ids, missing_ids = get_allowed_document_id_sets(
        db,
        tenant_id,
        account_id,
        citation_doc_ids,
        check_member=False,
    )
    if missing_ids:
        return False
    return len(allowed_ids) == len(citation_doc_ids)


def _hash_permission_ids(permissions: Iterable[Any] | None, *, max_items: int = 200) -> list[str]:
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    limit = max(0, int(max_items or 0))
    for raw in permissions or []:
        account_id = _safe_str(getattr(raw, "account_id", None), max_len=255)
        if not account_id:
            continue
        digest = stable_hash(account_id, length=32)
        if digest in seen:
            continue
        seen.add(digest)
        rows.append((account_id, digest))
        if limit and len(rows) >= limit:
            break
    rows.sort(key=lambda item: item[0])
    return [digest for _account_id, digest in rows]


@dataclass(frozen=True)
class _TraceChunkUsage:
    citations_matched: int
    request_id: str | None
    retrieval_mode: str | None
    hits: list[dict[str, Any]]


def _eligible_retrieval_trace(
    raw: Mapping[str, Any],
    *,
    tenant_id: str,
    cutoff_ms: int,
) -> tuple[dict[str, Any], int] | None:
    record = dict(raw) if isinstance(raw, Mapping) else {}
    if str(record.get("event") or "") != "rag_trace":
        return None
    if str(record.get("tenant_id") or "") != tenant_id:
        return None
    ts_ms = _to_int(record.get("ts_ms")) or 0
    if ts_ms and ts_ms < cutoff_ms:
        return None
    return record, ts_ms


def _chunk_hit_payload(
    *,
    record: Mapping[str, Any],
    citation: Mapping[str, Any],
    retrieval: Mapping[str, Any],
    retrieval_mode: str | None,
    chunk_id: str,
    ts_ms: int,
    citation_index: int,
    request_id: str | None,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "conversation_id": _safe_str(record.get("conversation_id"), max_len=120),
        "ts_ms": int(ts_ms),
        "citation_index": int(citation_index),
        "document_id": _safe_str(citation.get("document_id"), max_len=120),
        "chunk_id": chunk_id,
        "page_number": _to_int(citation.get("page_number")),
        "chunk_index": _to_int(citation.get("chunk_index")),
        "retrieval_role": _safe_str(citation.get("retrieval_role"), max_len=80),
        "hit_type": _safe_str(citation.get("hit_type"), max_len=40),
        "retrieval": {
            "mode": retrieval_mode,
            "requested_mode": _safe_str(retrieval.get("requested_mode"), max_len=80),
            "retrieval_config_hash": _safe_str(retrieval.get("retrieval_config_hash"), max_len=120),
            "reranker_provider": _safe_str(retrieval.get("reranker_provider"), max_len=80),
        },
    }


def _trace_chunk_usage(
    record: Mapping[str, Any],
    *,
    chunk_id: str,
    ts_ms: int,
    hit_limit: int,
) -> _TraceChunkUsage:
    retrieval = _safe_dict(record.get("retrieval"))
    retrieval_mode = _safe_str(retrieval.get("mode"), max_len=80)
    request_id = _safe_str(record.get("request_id"), max_len=120)
    citations_matched = 0
    hits: list[dict[str, Any]] = []
    for index, citation_raw in enumerate(_safe_list(record.get("citations"))):
        citation = _safe_dict(citation_raw)
        if str(citation.get("chunk_id") or "") != chunk_id:
            continue
        citations_matched += 1
        if len(hits) < hit_limit:
            hits.append(
                _chunk_hit_payload(
                    record=record,
                    citation=citation,
                    retrieval=retrieval,
                    retrieval_mode=retrieval_mode,
                    chunk_id=chunk_id,
                    ts_ms=ts_ms,
                    citation_index=index,
                    request_id=request_id,
                )
            )
    return _TraceChunkUsage(
        citations_matched=citations_matched,
        request_id=request_id if citations_matched else None,
        retrieval_mode=retrieval_mode if citations_matched else None,
        hits=hits,
    )


def _request_ids_from_sorted_hits(hits: Sequence[Mapping[str, Any]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for item in hits:
        request_id = _safe_str(item.get("request_id"), max_len=120)
        if not request_id or request_id in seen:
            continue
        seen.add(request_id)
        ordered.append(request_id)
    return ordered


def summarize_chunk_retrieval_usage_from_records(
    records: Sequence[Mapping[str, Any]] | None,
    *,
    tenant_id: UUID | str,
    chunk_id: UUID | str,
    now: datetime | None = None,
    window_minutes: int = 60,
    max_hits: int = 20,
) -> dict[str, Any]:
    tenant_key = str(tenant_id)
    chunk_key = str(chunk_id)
    now_dt = now or _now_utc()
    cutoff_ms = int(now_dt.timestamp() * 1000) - (max(1, int(window_minutes or 0)) * 60 * 1000)

    traces_scanned = 0
    traces_with_hits = 0
    citations_matched = 0
    last_seen_ts_ms: int | None = None
    request_ids: list[str] = []
    request_seen: set[str] = set()
    retrieval_modes: dict[str, int] = {}
    hits: list[dict[str, Any]] = []

    hit_limit = max(0, int(max_hits or 0))
    for raw in records or []:
        eligible = _eligible_retrieval_trace(raw, tenant_id=tenant_key, cutoff_ms=cutoff_ms)
        if eligible is None:
            continue
        record, ts_ms = eligible
        traces_scanned += 1
        usage = _trace_chunk_usage(
            record,
            chunk_id=chunk_key,
            ts_ms=ts_ms,
            hit_limit=max(0, hit_limit - len(hits)),
        )
        if not usage.citations_matched:
            continue
        traces_with_hits += 1
        citations_matched += usage.citations_matched
        last_seen_ts_ms = max(last_seen_ts_ms or ts_ms, ts_ms)
        if usage.request_id and usage.request_id not in request_seen:
            request_seen.add(usage.request_id)
            request_ids.append(usage.request_id)
        if usage.retrieval_mode:
            retrieval_modes[usage.retrieval_mode] = int(retrieval_modes.get(usage.retrieval_mode, 0) or 0) + 1
        hits.extend(usage.hits)

    hits.sort(
        key=lambda item: (
            -int(item.get("ts_ms") or 0),
            str(item.get("request_id") or ""),
            int(item.get("citation_index") or 0),
        )
    )

    ordered_request_ids = _request_ids_from_sorted_hits(hits)
    if ordered_request_ids:
        request_ids = ordered_request_ids

    return {
        "schema": CHUNK_RETRIEVAL_LINEAGE_SCHEMA,
        "chunk_id": chunk_key,
        "window_minutes": int(max(1, int(window_minutes or 0))),
        "traces_scanned": int(traces_scanned),
        "traces_with_hits": int(traces_with_hits),
        "citations_matched": int(citations_matched),
        "last_seen_ts_ms": last_seen_ts_ms,
        "request_ids": request_ids[: max(0, int(max_hits or 0))],
        "retrieval_modes": dict(sorted(retrieval_modes.items(), key=lambda kv: kv[0])),
        "hits": hits[: max(0, int(max_hits or 0))],
    }


def _extract_pipeline_version(
    meta: Mapping[str, Any] | None, *, active_pipeline_hash: str | None
) -> dict[str, Any] | None:
    meta_map = dict(meta or {})
    versions = meta_map.get("pipeline_provenance_versions")
    if not isinstance(versions, dict) or not versions:
        return None

    active = _safe_str(active_pipeline_hash, max_len=255)
    if active and isinstance(versions.get(active), dict):
        return dict(versions.get(active) or {})

    for key in sorted(versions.keys()):
        payload = versions.get(key)
        if isinstance(payload, dict):
            return dict(payload)
    return None


def build_chunk_lineage_payload(
    *,
    chunk: Any,
    document: Any,
    permissions: Iterable[Any] | None = None,
    retrieval_usage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    doc_meta = _safe_dict(getattr(document, "doc_metadata", None))
    chunk_meta = _safe_dict(getattr(chunk, "doc_metadata", None))
    connector = extract_connector_source_identity(document)

    active_pipeline_hash = _safe_str(
        chunk_meta.get("pipeline_hash") or doc_meta.get("pipeline_hash"),
        max_len=255,
    )
    acl_provenance = _safe_dict(doc_meta.get("acl_provenance"))
    effective_access = _safe_dict(acl_provenance.get("effective_access"))
    source_acl = _safe_dict(acl_provenance.get("source_acl"))
    permission_hashes = _hash_permission_ids(permissions)

    payload = {
        "schema": CHUNK_LINEAGE_SCHEMA,
        "chunk": {
            "chunk_id": str(getattr(chunk, "id", "")),
            "document_id": str(getattr(chunk, "document_id", "")),
            "chunk_index": _to_int(getattr(chunk, "chunk_index", None)),
            "page_number": _to_int(getattr(chunk, "page_number", None)),
            "start_char": _to_int(getattr(chunk, "start_char", None)),
            "end_char": _to_int(getattr(chunk, "end_char", None)),
            "vector_id": _safe_str(getattr(chunk, "vector_id", None), max_len=255),
            "chunk_role": _safe_str(chunk_meta.get("chunk_role"), max_len=80),
            "chunk_quality": _safe_dict(chunk_meta.get("chunk_quality")) or None,
        },
        "document": {
            "document_id": str(getattr(document, "id", "")),
            "tenant_id": str(getattr(document, "tenant_id", "")),
            "dataset_id": (
                str(getattr(document, "dataset_id", "")) if getattr(document, "dataset_id", None) is not None else None
            ),
            "filename": _safe_str(getattr(document, "filename", None), max_len=500),
            "file_type": _safe_str(getattr(document, "file_type", None), max_len=32),
            "status": _safe_str(getattr(document, "status", None), max_len=80),
            "chunk_count": _to_int(getattr(document, "chunk_count", None)),
            "total_characters": _to_int(getattr(document, "total_characters", None)),
        },
        "connector": {
            "connector_id": connector.get("connector_id"),
            "config_id": connector.get("config_id"),
            "source_ref": connector.get("source_ref"),
            "source_id": connector.get("source_id"),
        },
        "acl": {
            "mode": _safe_str(getattr(document, "access_mode", None), max_len=80)
            or _safe_str(effective_access.get("mode"), max_len=80),
            "owner_id_hash": (
                stable_hash(str(getattr(document, "owner_id", "")), length=32)
                if _safe_str(getattr(document, "owner_id", None), max_len=255)
                else None
            ),
            "permission_count": int(len(permission_hashes)),
            "permission_hashes": permission_hashes,
            "effective_access": effective_access or None,
            "source_acl": source_acl or None,
        },
        "pipeline": {
            "active_pipeline_hash": active_pipeline_hash,
            "version": _extract_pipeline_version(doc_meta, active_pipeline_hash=active_pipeline_hash),
        },
        "retrieval_usage": dict(retrieval_usage or {}),
    }
    return payload


def build_answer_lineage_payload(
    *,
    trace_record: Mapping[str, Any],
    chunk_by_id: Mapping[str, Any] | None = None,
    document_by_id: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    record = dict(trace_record or {})
    retrieval = _safe_dict(record.get("retrieval"))
    citations_raw = _safe_list(record.get("citations"))

    chunks_out: list[dict[str, Any]] = []
    docs_seen: dict[str, dict[str, Any]] = {}
    for idx, citation_raw in enumerate(citations_raw):
        citation = _safe_dict(citation_raw)
        chunk_id = _safe_str(citation.get("chunk_id"), max_len=120)
        document_id = _safe_str(citation.get("document_id"), max_len=120)
        chunk_obj = (chunk_by_id or {}).get(chunk_id or "")
        document_obj = (document_by_id or {}).get(document_id or "")
        if document_id:
            docs_seen.setdefault(
                document_id,
                {
                    "document_id": document_id,
                    "filename": _safe_str(getattr(document_obj, "filename", None), max_len=500),
                    "dataset_id": (
                        str(getattr(document_obj, "dataset_id", ""))
                        if getattr(document_obj, "dataset_id", None) is not None
                        else None
                    ),
                },
            )
        chunks_out.append(
            {
                "rank": int(idx + 1),
                "chunk_id": chunk_id,
                "document_id": document_id,
                "page_number": _to_int(citation.get("page_number")),
                "chunk_index": _to_int(citation.get("chunk_index")),
                "retrieval_role": _safe_str(citation.get("retrieval_role"), max_len=80),
                "hit_type": _safe_str(citation.get("hit_type"), max_len=40),
                "retrieval_score": citation.get("retrieval_score"),
                "rerank_score": citation.get("rerank_score"),
                "chunk_role": _safe_str(
                    _safe_dict(getattr(chunk_obj, "doc_metadata", None)).get("chunk_role"), max_len=80
                ),
            }
        )

    return {
        "schema": ANSWER_LINEAGE_SCHEMA,
        "request_id": _safe_str(record.get("request_id"), max_len=120),
        "conversation_id": _safe_str(record.get("conversation_id"), max_len=120),
        "ts_ms": _to_int(record.get("ts_ms")),
        "retrieval": {
            "mode": _safe_str(retrieval.get("mode"), max_len=80),
            "requested_mode": _safe_str(retrieval.get("requested_mode"), max_len=80),
            "retrieval_config_hash": _safe_str(retrieval.get("retrieval_config_hash"), max_len=120),
            "top_k": _to_int(retrieval.get("top_k")),
            "query_count": _to_int(retrieval.get("query_count")),
            "enable_reranker": bool(retrieval.get("enable_reranker") or False),
            "reranker_provider": _safe_str(retrieval.get("reranker_provider"), max_len=80),
            "reranker_top_n": _to_int(retrieval.get("reranker_top_n")),
        },
        "citations_count": int(len(chunks_out)),
        "documents": list(docs_seen.values()),
        "chunks": chunks_out,
    }


def get_chunk_lineage(
    db: Session,
    *,
    tenant_id: UUID,
    chunk_id: UUID,
    window_minutes: int = 60,
    max_bytes: int = 5_000_000,
    max_hits: int = 20,
) -> dict[str, Any] | None:
    row = (
        db.query(DocumentChunk, DBDocument)
        .join(DBDocument, DBDocument.id == DocumentChunk.document_id)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DBDocument.tenant_id == tenant_id,
            DocumentChunk.id == chunk_id,
        )
        .first()
    )
    if not row:
        return None

    chunk, document = row
    permissions = (
        db.query(DocumentPermission)
        .filter(
            DocumentPermission.tenant_id == tenant_id,
            DocumentPermission.document_id == document.id,
        )
        .all()
    )

    usage: dict[str, Any] = {
        "schema": CHUNK_RETRIEVAL_LINEAGE_SCHEMA,
        "chunk_id": str(chunk_id),
        "window_minutes": int(max(1, int(window_minutes or 0))),
        "traces_scanned": 0,
        "traces_with_hits": 0,
        "citations_matched": 0,
        "last_seen_ts_ms": None,
        "request_ids": [],
        "retrieval_modes": {},
        "hits": [],
    }

    if bool(getattr(settings, "ENABLE_METRICS_LOG", False)):
        path = Path(
            str(getattr(settings, "METRICS_LOG_PATH", "./logs/rag_metrics.jsonl") or "./logs/rag_metrics.jsonl")
        )
        if path.exists():
            records = _read_jsonl_tail(path, max_bytes=max_bytes)
            usage = summarize_chunk_retrieval_usage_from_records(
                records,
                tenant_id=tenant_id,
                chunk_id=chunk_id,
                window_minutes=window_minutes,
                max_hits=max_hits,
            )

    return build_chunk_lineage_payload(
        chunk=chunk,
        document=document,
        permissions=permissions,
        retrieval_usage=usage,
    )


__all__ = [
    "ANSWER_LINEAGE_SCHEMA",
    "CHUNK_LINEAGE_SCHEMA",
    "CHUNK_RETRIEVAL_LINEAGE_SCHEMA",
    "authorize_answer_lineage_access",
    "authorize_chunk_lineage_access",
    "build_answer_lineage_payload",
    "build_chunk_lineage_payload",
    "get_chunk_lineage",
    "load_answer_lineage_trace",
    "summarize_chunk_retrieval_usage_from_records",
]
