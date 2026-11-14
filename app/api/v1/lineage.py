"""Read authorized, versioned JSON reports owned by the lineage service."""

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document, DocumentChunk, DocumentPermission
from app.services.lineage_service import (
    authorize_answer_lineage_access,
    authorize_chunk_lineage_access,
    build_answer_lineage_payload,
    build_chunk_lineage_payload,
    load_answer_lineage_trace,
    summarize_chunk_retrieval_usage_from_records,
)

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)
_DEFAULT_RAG_METRICS_LOG_PATH = "./logs/rag_metrics.jsonl"


class ChunkLineageResponse(BaseModel):
    """Stable report envelope; the lineage owner supplies versioned detail mappings."""

    schema_version: str = Field(alias="schema")
    chunk: dict[str, Any]
    document: dict[str, Any]
    connector: dict[str, Any]
    acl: dict[str, Any]
    pipeline: dict[str, Any]
    retrieval_usage: dict[str, Any]


class AnswerLineageResponse(BaseModel):
    schema_version: str = Field(alias="schema")
    request_id: str | None
    conversation_id: str | None
    ts_ms: int | None
    retrieval: dict[str, Any]
    citations_count: int
    documents: list[dict[str, Any]]
    chunks: list[dict[str, Any]]


@router.get("/chunk/{chunk_id}")
def get_chunk_lineage(
    chunk_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ChunkLineageResponse:
    row = (
        db.query(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            Document.tenant_id == tenant_id,
            DocumentChunk.id == chunk_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Chunk lineage not found")
    chunk, document = row
    if not authorize_chunk_lineage_access(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document_id=document.id,
    ):
        raise HTTPException(status_code=404, detail="Chunk lineage not found")
    permissions = (
        db.query(DocumentPermission)
        .filter(
            DocumentPermission.tenant_id == tenant_id,
            DocumentPermission.document_id == document.id,
        )
        .all()
    )
    records: list[dict[str, Any]] = []
    if settings.ENABLE_METRICS_LOG:
        path = Path(settings.METRICS_LOG_PATH or _DEFAULT_RAG_METRICS_LOG_PATH)
        if path.exists():
            from app.services.jsonl_tail import read_jsonl_tail

            records, _truncated = read_jsonl_tail(path, max_bytes=5_000_000)
    retrieval_usage = summarize_chunk_retrieval_usage_from_records(
        records,
        tenant_id=tenant_id,
        chunk_id=chunk_id,
        window_minutes=60,
        max_hits=20,
    )
    return ChunkLineageResponse.model_validate(
        build_chunk_lineage_payload(
            chunk=chunk,
            document=document,
            permissions=permissions,
            retrieval_usage=retrieval_usage,
        )
    )


@router.get("/answer/{request_id}")
def get_answer_lineage(
    request_id: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> AnswerLineageResponse:
    record = load_answer_lineage_trace(
        tenant_id=tenant_id,
        request_id=request_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Answer lineage not found")
    if not authorize_answer_lineage_access(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        trace_record=record,
    ):
        raise HTTPException(status_code=404, detail="Answer lineage not found")
    return AnswerLineageResponse.model_validate(build_answer_lineage_payload(trace_record=record))
