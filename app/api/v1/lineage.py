
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk, DocumentPermission
from app.services.lineage_service import (
    ANSWER_LINEAGE_SCHEMA,
    CHUNK_RETRIEVAL_LINEAGE_SCHEMA,
    authorize_answer_lineage_access,
    authorize_chunk_lineage_access,
    build_answer_lineage_payload,
    build_chunk_lineage_payload,
    load_answer_lineage_trace,
    summarize_chunk_retrieval_usage_from_records,
)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
_DEFAULT_RAG_METRICS_LOG_PATH = "./logs/rag_metrics.jsonl"


def _load_chunk_lineage_dependencies(
    db: Session,
    *,
    tenant_id: UUID,
    chunk_id: UUID,
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
    retrieval_usage = {
        "schema": CHUNK_RETRIEVAL_LINEAGE_SCHEMA,
        "chunk_id": str(chunk_id),
        "window_minutes": 60,
        "traces_scanned": 0,
        "traces_with_hits": 0,
        "citations_matched": 0,
        "last_seen_ts_ms": None,
        "request_ids": [],
        "retrieval_modes": {},
        "hits": [],
    }
    if bool(getattr(settings, "ENABLE_METRICS_LOG", False)):
        path = Path(str(getattr(settings, "METRICS_LOG_PATH", _DEFAULT_RAG_METRICS_LOG_PATH) or _DEFAULT_RAG_METRICS_LOG_PATH))
        if path.exists():
            from app.services.lineage_service import _read_jsonl_tail  # noqa: WPS433

            records = _read_jsonl_tail(path, max_bytes=5_000_000)
            retrieval_usage = summarize_chunk_retrieval_usage_from_records(
                records,
                tenant_id=tenant_id,
                chunk_id=chunk_id,
                window_minutes=60,
                max_hits=20,
            )
    return {
        "chunk": chunk,
        "document": document,
        "permissions": permissions,
        "retrieval_usage": retrieval_usage,
    }


@router.get("/chunk/{chunk_id}", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_chunk_lineage(
    chunk_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    deps = _load_chunk_lineage_dependencies(db, tenant_id=tenant_id, chunk_id=chunk_id)
    if deps is None:
        raise HTTPException(status_code=404, detail="Chunk lineage not found")
    document = deps["document"]
    if not authorize_chunk_lineage_access(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document_id=document.id,
    ):
        raise HTTPException(status_code=403, detail="No permission to access chunk lineage")
    return build_chunk_lineage_payload(
        chunk=deps["chunk"],
        document=document,
        permissions=deps["permissions"],
        retrieval_usage=deps["retrieval_usage"],
    )


@router.get("/answer/{request_id}", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_answer_lineage(
    request_id: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    record = load_answer_lineage_trace(
        tenant_id=tenant_id,
        request_id=str(request_id or "").strip(),
    )
    if not isinstance(record, dict):
        raise HTTPException(status_code=404, detail="Answer lineage not found")
    if not authorize_answer_lineage_access(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        trace_record=record,
    ):
        raise HTTPException(status_code=403, detail="No permission to access answer lineage")
    payload = build_answer_lineage_payload(trace_record=record)
    if str(payload.get("schema") or "") != ANSWER_LINEAGE_SCHEMA:
        raise HTTPException(status_code=500, detail="Invalid answer lineage payload")
    return payload
