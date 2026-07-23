
import ast
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.external_conversation import (
    ExternalConversationIngestRequest,
    ExternalConversationIngestResponse,
)
from app.core.token_utils import num_tokens_from_string
from app.models.chat import Conversation, Message
from app.services.audit_log_service import audit_log_event
from app.services.chat_conversation_access import ensure_conversation_access
from app.services.chat_conversation_titles import (
    CONVERSATION_TITLE_SOURCE_AUTO,
    CONVERSATION_TITLE_SOURCE_MANUAL,
    apply_auto_conversation_title,
)
from app.services.dataset_service import DatasetService
from app.services.document_access import filter_allowed_document_ids

EXTERNAL_CONVERSATION_METADATA_KEY = "external_conversation"


def _metadata_text_field(field: str):
    return Message.message_metadata[EXTERNAL_CONVERSATION_METADATA_KEY][field].astext  # type: ignore[index]


def _request_title(request: ExternalConversationIngestRequest) -> str | None:
    title = str(request.title or "").strip()
    return title or None


def _dedupe_uuid_list(values: list[UUID]) -> list[UUID]:
    seen: set[UUID] = set()
    out: list[UUID] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _resolve_document_scope(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    request: ExternalConversationIngestRequest,
) -> tuple[UUID | None, list[UUID]]:
    requested_doc_ids = _dedupe_uuid_list(list(request.document_ids))
    if len(requested_doc_ids) > 0:
        allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, requested_doc_ids)
        if len(allowed_doc_ids) != len(requested_doc_ids):
            raise HTTPException(status_code=403, detail="Some external conversation documents are not accessible")
        return None, allowed_doc_ids

    if request.dataset_id is not None:
        DatasetService.ensure_member(db, tenant_id, account_id)
        dataset = DatasetService.get_dataset(db, tenant_id, request.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
        return request.dataset_id, []

    DatasetService.ensure_member(db, tenant_id, account_id)
    return None, []


def _find_conversation_by_external_id(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    source: str,
    source_conversation_id: str,
) -> Conversation | None:
    rows = (
        db.query(Message.conversation_id)
        .filter(
            Message.tenant_id == tenant_id,
            _metadata_text_field("source") == source,
            _metadata_text_field("source_conversation_id") == source_conversation_id,
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )
    conversation_ids = list(dict.fromkeys(row[0] for row in rows if row and row[0] is not None))
    if not conversation_ids:
        return None
    conversations = (
        db.query(Conversation)
        .filter(
            Conversation.tenant_id == tenant_id,
            Conversation.owner_account_id == str(account_id or "").strip(),
            Conversation.id.in_(conversation_ids),
        )
        .all()
    )
    by_id = {conversation.id: conversation for conversation in conversations}
    return next((by_id[item] for item in conversation_ids if item in by_id), None)


def _load_existing_conversation(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    request: ExternalConversationIngestRequest,
) -> tuple[Conversation | None, bool]:
    explicit: Conversation | None = None
    if request.conversation_id is not None:
        explicit = (
            db.query(Conversation)
            .filter(Conversation.tenant_id == tenant_id, Conversation.id == request.conversation_id)
            .first()
        )
        if explicit is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        ensure_conversation_access(db, tenant_id, account_id, explicit)

    mapped = _find_conversation_by_external_id(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        source=request.source,
        source_conversation_id=request.source_conversation_id,
    )
    if explicit is not None and mapped is not None and explicit.id != mapped.id:
        raise HTTPException(status_code=409, detail="External conversation is already mapped to another conversation")
    if explicit is not None:
        return explicit, False
    if mapped is not None:
        ensure_conversation_access(db, tenant_id, account_id, mapped)
        return mapped, False
    return None, True


def _create_external_conversation(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    request: ExternalConversationIngestRequest,
    dataset_id: UUID | None,
    document_ids: list[UUID],
) -> Conversation:
    title = _request_title(request)
    conversation = Conversation(
        tenant_id=tenant_id,
        owner_account_id=str(account_id or "").strip() or None,
        title=title,
        title_source=CONVERSATION_TITLE_SOURCE_MANUAL if title else CONVERSATION_TITLE_SOURCE_AUTO,
        dataset_id=dataset_id,
        document_ids=document_ids,
    )
    if not title:
        first_user_message = next((msg.content for msg in request.messages if msg.role == "user"), "")
        apply_auto_conversation_title(conversation, first_user_message)
    db.add(conversation)
    db.flush()
    return conversation


def _existing_source_message_ids(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    source: str,
    source_conversation_id: str,
    source_message_ids: list[str],
) -> set[str]:
    ids = [str(item).strip() for item in source_message_ids if str(item or "").strip()]
    if not ids:
        return set()
    rows = (
        db.query(_metadata_text_field("source_message_id"))
        .filter(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
            _metadata_text_field("source") == source,
            _metadata_text_field("source_conversation_id") == source_conversation_id,
            _metadata_text_field("source_message_id").in_(ids),
        )
        .all()
    )
    return {str(row[0]).strip() for row in rows if row and str(row[0] or "").strip()}


def _external_message_metadata(
    *,
    request: ExternalConversationIngestRequest,
    message_metadata: dict[str, Any],
    account_id: str,
    imported_at: datetime,
) -> dict[str, Any]:
    source_run_id = message_metadata.get("source_run_id") or request.source_run_id
    external_meta = {
        "source": request.source,
        "source_conversation_id": request.source_conversation_id,
        "source_message_id": message_metadata.get("source_message_id"),
        "source_run_id": source_run_id,
        "source_user_id": request.source_user_id,
        "imported_by": account_id,
        "imported_at": imported_at.isoformat(),
    }
    return {
        EXTERNAL_CONVERSATION_METADATA_KEY: external_meta,
        "external_metadata": {
            "conversation": dict(request.metadata or {}),
            "message": dict(message_metadata.get("metadata") or {}),
            "citations": list(message_metadata.get("citations") or []),
        },
    }


def _is_mimirq_citation(value: Any) -> bool:
    return _normalize_mimirq_citation(value) is not None


_CITATION_CONTENT_KEYS = ("chunk_content", "content", "text", "quote", "snippet", "page_content")
_CITATION_TITLE_KEYS = ("document_name", "title", "filename", "source", "source_path", "document_id")
_CITATION_SCORE_KEYS = (
    "relevance_score",
    "score",
    "mimirq_score",
    "retrieval_score",
    "rerank_score",
    "vector_score",
    "bm25_score",
    "keyword_score",
)
_CITATION_OPTIONAL_KEYS = (
    "chunk_index",
    "page_number",
    "bbox",
    "bbox_page_number",
    "start_char",
    "end_char",
    "evidence_start_char",
    "evidence_end_char",
    "header_path",
    "chunk_strategy",
    "chunk_role",
    "retrieval_role",
    "neighbor_of",
    "doc_pipeline_key",
    "pipeline_hash",
    "vector_score",
    "bm25_score",
    "keyword_score",
    "rerank_score",
    "retrieval_score",
    "reranker_provider",
    "rerank_elapsed_sec",
    "rerank_model_used",
    "retrieval_mode",
    "vector_backend",
    "retrieval_elapsed_sec",
    "hit_type",
    "has_image",
    "img_id",
    "img_url",
    "kg_path",
    "kg_path_provenance",
)
_CITATION_SERIALIZED_LIST_MAX_CHARS = 1_000_000
_EXTERNAL_CITATION_LIST_KEYS = (
    "citations",
    "retrieval_citations",
    "retrieval_records",
    "records",
    "sources",
    "source_documents",
    "documents",
)
_EXTERNAL_CITATION_WRAPPER_KEYS = (
    "retrieval",
    "mimirq",
    "mimirq_retrieval",
    "external_knowledge",
)


def _first_non_empty(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def _normalize_uuid_text(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except Exception:
        return ""


def _normalize_mimirq_citation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    raw_metadata = value.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    document_id = _normalize_uuid_text(value.get("document_id") or metadata.get("document_id"))
    chunk_id = _normalize_uuid_text(value.get("chunk_id") or metadata.get("chunk_id"))
    chunk_content = str(
        _first_non_empty(value, _CITATION_CONTENT_KEYS)
        or _first_non_empty(metadata, _CITATION_CONTENT_KEYS)
        or ""
    ).strip()

    if not document_id or not chunk_id or not chunk_content:
        return None

    document_name = str(
        _first_non_empty(value, _CITATION_TITLE_KEYS)
        or _first_non_empty(metadata, _CITATION_TITLE_KEYS)
        or "Document"
    ).strip()

    out: dict[str, Any] = {
        "document_id": document_id,
        "chunk_id": chunk_id,
        "chunk_content": chunk_content,
        "document_name": document_name or "Document",
    }

    for key in _CITATION_OPTIONAL_KEYS:
        candidate = value.get(key, metadata.get(key))
        if candidate is not None and candidate != "":
            out[key] = candidate

    score = _first_non_empty(value, _CITATION_SCORE_KEYS)
    if score is None:
        score = _first_non_empty(metadata, _CITATION_SCORE_KEYS)
    if score is not None:
        try:
            out["relevance_score"] = float(score)
        except Exception:
            pass

    return out


def _citation_items_from_value(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, str):
        return []

    text = value.strip()
    if not text or len(text) > _CITATION_SERIALIZED_LIST_MAX_CHARS:
        return []

    parsed: Any
    try:
        parsed = json.loads(text)
    except Exception:
        try:
            parsed = ast.literal_eval(text)
        except Exception:
            return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _citation_candidates_from_metadata(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for key in _EXTERNAL_CITATION_LIST_KEYS:
        candidates.extend(_citation_items_from_value(metadata.get(key)))

    for wrapper_key in _EXTERNAL_CITATION_WRAPPER_KEYS:
        wrapper = metadata.get(wrapper_key)
        if not isinstance(wrapper, dict):
            continue
        for key in _EXTERNAL_CITATION_LIST_KEYS:
            candidates.extend(_citation_items_from_value(wrapper.get(key)))

    return candidates


def _external_message_citation_candidates(
    citations: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = [item for item in citations if isinstance(item, dict)]
    if isinstance(metadata, dict):
        candidates.extend(_citation_candidates_from_metadata(metadata))
    return candidates


def _mimirq_citations_for_storage(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in citations:
        normalized = _normalize_mimirq_citation(item)
        if normalized is None:
            continue
        key = (str(normalized.get("document_id") or ""), str(normalized.get("chunk_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out


def _next_message_created_at(
    requested_at: datetime | None,
    *,
    imported_at: datetime,
    previous_at: datetime | None,
) -> datetime:
    candidate = requested_at or imported_at
    if previous_at is not None and candidate <= previous_at:
        return previous_at + timedelta(microseconds=1)
    return candidate


def ingest_external_conversation(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    request: ExternalConversationIngestRequest,
    request_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> ExternalConversationIngestResponse:
    dataset_id, document_ids = _resolve_document_scope(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request,
    )
    conversation, should_create = _load_existing_conversation(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request,
    )
    created_conversation = False
    if conversation is None:
        conversation = _create_external_conversation(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            request=request,
            dataset_id=dataset_id,
            document_ids=document_ids,
        )
        created_conversation = True
    elif request.update_title and _request_title(request):
        conversation.title = _request_title(request)
        conversation.title_source = CONVERSATION_TITLE_SOURCE_MANUAL

    source_message_ids = [msg.source_message_id for msg in request.messages if msg.source_message_id]
    existing_ids = _existing_source_message_ids(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        source=request.source,
        source_conversation_id=request.source_conversation_id,
        source_message_ids=[str(item) for item in source_message_ids],
    )

    inserted_ids: list[UUID] = []
    skipped_source_ids: list[str] = []
    imported_at = datetime.now(UTC)
    latest_message_time: datetime | None = None
    inserted_user_messages = 0

    for incoming in request.messages:
        source_message_id = str(incoming.source_message_id or "").strip()
        if source_message_id and source_message_id in existing_ids:
            skipped_source_ids.append(source_message_id)
            continue

        citation_candidates = _external_message_citation_candidates(incoming.citations, incoming.metadata)
        stored_citations = _mimirq_citations_for_storage(citation_candidates)
        metadata = _external_message_metadata(
            request=request,
            message_metadata={
                "source_message_id": source_message_id or None,
                "source_run_id": incoming.source_run_id,
                "metadata": incoming.metadata,
                "citations": citation_candidates,
            },
            account_id=account_id,
            imported_at=imported_at,
        )
        message_id = uuid4()
        message_created_at = _next_message_created_at(
            incoming.created_at,
            imported_at=imported_at,
            previous_at=latest_message_time,
        )
        latest_message_time = message_created_at
        message_kwargs: dict[str, Any] = {
            "id": message_id,
            "tenant_id": tenant_id,
            "conversation_id": conversation.id,
            "role": incoming.role,
            "content": incoming.content,
            "citations": stored_citations if incoming.role == "assistant" else [],
            "token_count": incoming.token_count
            if incoming.token_count is not None
            else num_tokens_from_string(incoming.content or ""),
            "message_metadata": metadata,
        }
        message_kwargs["created_at"] = message_created_at
        message = Message(**message_kwargs)
        db.add(message)
        inserted_ids.append(message_id)
        if incoming.role == "user":
            inserted_user_messages += 1
        if source_message_id:
            existing_ids.add(source_message_id)

    if inserted_ids:
        conversation.message_count = int(conversation.message_count or 0) + inserted_user_messages
        conversation.updated_at = latest_message_time or imported_at

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="external_conversation.ingest",
        resource_type="conversation",
        resource_id=str(conversation.id),
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        details={
            "source": request.source,
            "source_conversation_id": request.source_conversation_id,
            "created_conversation": created_conversation,
            "inserted_messages": len(inserted_ids),
            "skipped_messages": len(skipped_source_ids),
        },
    )
    db.commit()

    return ExternalConversationIngestResponse(
        conversation_id=conversation.id,
        created_conversation=created_conversation if should_create else False,
        source=request.source,
        source_conversation_id=request.source_conversation_id,
        inserted_messages=len(inserted_ids),
        skipped_messages=len(skipped_source_ids),
        message_ids=inserted_ids,
        skipped_source_message_ids=skipped_source_ids,
    )
