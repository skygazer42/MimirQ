"""
Chat API.
"""
import logging
import re
from uuid import UUID
import uuid
from datetime import datetime
import json
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func
from sqlalchemy.orm import Session
from langchain_core.documents import Document
from langchain_community.retrievers.bm25 import BM25Retriever

from app.core.database import get_db
from app.models.chat import Conversation, Message
from app.services.dataset_service import DatasetService
from app.api.schemas.chat import (
    ChatRequest,
    ConversationCreate,
    ConversationSchema,
    ConversationDetail,
    ConversationList,
    CheckpointListResponse,
    CheckpointDetailResponse,
)
from app.services.document_access import (
    filter_allowed_document_ids,
    get_allowed_document_id_sets,
    list_accessible_document_ids,
)
from app.rag.engine import get_rag_engine
from app.rag.core.text import parse_json_from_text
from app.services.metrics_logger import log_metrics, set_metrics_context
from app.core.token_utils import num_tokens_from_string
from app.core.config import settings
from app.core.env import is_production_env
from app.api.dependencies.tenant import get_tenant_id
from app.api.dependencies.auth import get_current_account_id
from app.rag.preprocessing.tokenization import tokenize_for_bm25

logger = logging.getLogger(__name__)

router = APIRouter()


def _format_stream_error_message(exc: Exception) -> str:
    raw = str(exc) or exc.__class__.__name__
    raw = " ".join(raw.split())
    raw = re.sub(r"sk-[A-Za-z0-9]{8,}", "sk-***", raw)
    raw = re.sub(r"(?i)bearer\\s+[A-Za-z0-9\\-_.]{8,}", "Bearer ***", raw)
    status_code = getattr(exc, "status_code", None)
    if status_code and isinstance(status_code, int):
        raw = f"HTTP {status_code}: {raw}"
    return raw.strip()


def _ensure_conversation_access(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    conv: Conversation
) -> List[UUID]:
    """
    Ensure the current user can access all documents bound to the conversation.
    Returns the allowed document ids (possibly empty if conversation has no docs).
    """
    if not conv.document_ids:
        return []
    doc_ids = list(conv.document_ids or [])
    allowed_ids, missing_ids = get_allowed_document_id_sets(
        db,
        tenant_id,
        account_id,
        doc_ids,
        check_member=False,
    )
    if missing_ids:
        missing = [str(doc_id) for doc_id in doc_ids if doc_id in missing_ids]
        raise HTTPException(status_code=404, detail=f"Documents not found: {', '.join(missing)}")
    allowed = [doc_id for doc_id in doc_ids if doc_id in allowed_ids]
    if not allowed:
        raise HTTPException(status_code=403, detail="No accessible documents for this request")
    return allowed


def _retrieve_long_term_messages(
    db: Session,
    conversation_id: UUID,
    tenant_id: UUID,
    query: str,
    top_k: int = 3
) -> List[dict]:
    """
    Simple long-term memory recall using BM25 over past messages.
    Used to enrich history context only; it does not modify storage.
    """
    max_messages = int(getattr(settings, "LONG_TERM_MEMORY_MAX_MESSAGES", 200) or 0)
    query_builder = (
        db.query(Message.content, Message.role, Message.created_at)
        .filter(
            Message.conversation_id == conversation_id,
            Message.tenant_id == tenant_id,
        )
        .order_by(Message.created_at.desc())
    )
    if max_messages > 0:
        query_builder = query_builder.limit(max_messages)

    rows = query_builder.all()
    if not rows:
        return []

    rows = list(reversed(rows))

    docs: List[Document] = []
    for content, role, created_at in rows:
        if not content or len(content.strip()) < settings.LONG_TERM_MEMORY_MIN_LEN:
            continue
        docs.append(
            Document(
                page_content=content,
                metadata={
                    "role": role,
                    "created_at": created_at.isoformat() if created_at else None,
                }
            )
        )

    if not docs:
        return []

    retriever = BM25Retriever.from_documents(
        docs,
        preprocess_func=tokenize_for_bm25,
        k=top_k
    )
    selected = retriever.invoke(query)

    enriched_history = []
    for doc in selected:
        enriched_history.append(
            {
                "role": doc.metadata.get("role", "assistant"),
                "content": doc.page_content,
                "from_long_term": True,
                "ts": doc.metadata.get("created_at")
            }
        )
    return enriched_history


@router.post("/stream")
async def stream_chat(
    http_request: Request,
    request: ChatRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    Streaming chat endpoint (core flow).
    """

    conversation_id = request.conversation_id
    citations_data = []
    full_response = ""
    allowed_doc_ids: list[UUID] = []
    long_term_messages: list[dict] = []
    allow_empty_docs = bool(getattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True))

    # 1. Load or create a conversation.
    if conversation_id:
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id
        ).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        target_doc_ids = request.document_ids if request.document_ids else (conversation.document_ids or [])
        if target_doc_ids:
            allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, target_doc_ids)
        else:
            # Default to accessible documents to avoid hard errors when document_ids are omitted.
            allowed_doc_ids = list_accessible_document_ids(db, tenant_id, account_id, status="completed")
            if not allowed_doc_ids and not allow_empty_docs:
                raise HTTPException(status_code=400, detail="No accessible documents for chat retrieval")
        # Update the conversation's document list with the allowed set.
        conversation.document_ids = allowed_doc_ids
    else:
        # Create a new conversation.
        if request.document_ids:
            allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, request.document_ids)
        else:
            allowed_doc_ids = list_accessible_document_ids(db, tenant_id, account_id, status="completed")
        if not allowed_doc_ids and not allow_empty_docs:
            raise HTTPException(status_code=400, detail="No accessible documents for chat retrieval")
        conversation = Conversation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            title=request.message[:50] + "..." if len(request.message) > 50 else request.message,
            document_ids=allowed_doc_ids
        )
        db.add(conversation)
        db.flush()
        conversation_id = conversation.id

    # 2. Persist the user message.
    user_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role='user',
        content=request.message
    )
    db.add(user_message)

    # Optional: long-term memory recall (BM25 over conversation messages).
    if request.enable_long_term_memory and settings.LONG_TERM_MEMORY_ENABLED and conversation_id:
        long_term_messages = _retrieve_long_term_messages(
            db=db,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            query=request.message,
            top_k=settings.LONG_TERM_MEMORY_TOP_K
        )

    # Update the conversation message count.
    conversation.message_count = (conversation.message_count or 0) + 1
    db.commit()

    # 3. Streaming response generator.
    async def event_stream():
        nonlocal citations_data, full_response
        doc_ids_to_use = allowed_doc_ids or []
        request_id = getattr(http_request.state, "request_id", None) or uuid.uuid4().hex
        assistant_message_id = uuid.uuid4()
        metrics_data = {}
        set_metrics_context(
            request_id=request_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            account_id=account_id,
        )

        # LangGraph path: stream stage events (custom) + state snapshots (values).
        if request.rag_config.use_graph:
            try:
                from app.rag.pipelines.langgraph import build_rag_state, rag_workflow

                thread_id = str(conversation_id) if conversation_id else f"rag-{request_id}"
                runtime_context = {
                    "request_id": str(request_id),
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "account_id": account_id,
                }

                state = build_rag_state(
                    question=request.message,
                    history=[m.model_dump() for m in request.history] + long_term_messages,
                    document_ids=doc_ids_to_use,
                    tenant_id=tenant_id,
                    top_k=request.rag_config.top_k,
                    score_threshold=request.rag_config.score_threshold,
                    retrieval_mode=request.rag_config.retrieval_mode,
                    alpha=request.rag_config.alpha,
                    enable_weight_rerank=request.rag_config.enable_weight_rerank,
                    vector_weight=request.rag_config.vector_weight,
                    keyword_weight=request.rag_config.keyword_weight,
                    mmr_lambda=request.rag_config.mmr_lambda,
                    enable_reranker=request.rag_config.enable_reranker,
                    reranker_provider=request.rag_config.reranker_provider,
                    reranker_top_n=request.rag_config.reranker_top_n,
                    metadata_filter=request.rag_config.metadata_filter,
                    structured_output=request.structured_output,
                    structured_preset=request.structured_preset,
                    prompt_template_id=request.prompt_template_id,
                    prompt_template_key=request.prompt_template_key,
                    prompt_ab_experiment_key=request.prompt_ab_experiment_key,
                    ab_user_key=account_id,
                    db=db,
                )

                recursion_limit = max(1, int(getattr(settings, "LANGGRAPH_RECURSION_LIMIT", 25) or 25))
                config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
                final_state: dict | None = None
                citations_sent = False
                answer_sent = False

                for mode, chunk in rag_workflow.stream(
                    state,
                    config=config,
                    context=runtime_context,
                    stream_mode=["custom", "values"],
                ):
                    if mode == "custom":
                        yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'graph', 'data': chunk}, ensure_ascii=False)}\n\n"
                        continue

                    if mode != "values" or not isinstance(chunk, dict):
                        continue

                    final_state = chunk

                    if not citations_sent and "citations" in chunk:
                        citations_data = chunk.get("citations") or []
                        citations_sent = True
                        yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'citations', 'data': citations_data}, ensure_ascii=False)}\n\n"

                    if not answer_sent and "answer" in chunk:
                        answer_text = chunk.get("answer") or ""
                        chunk_size = 120
                        for i in range(0, len(answer_text), chunk_size):
                            token_chunk = answer_text[i : i + chunk_size]
                            yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'token', 'data': {'content': token_chunk}}, ensure_ascii=False)}\n\n"
                            full_response += token_chunk
                        answer_sent = True

                graph_result = final_state or {}

                if not citations_sent:
                    citations_data = graph_result.get("citations") or []
                    yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'citations', 'data': citations_data}, ensure_ascii=False)}\n\n"

                if not answer_sent:
                    answer_text = graph_result.get("answer") or ""
                    chunk_size = 120
                    for i in range(0, len(answer_text), chunk_size):
                        token_chunk = answer_text[i : i + chunk_size]
                        yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'token', 'data': {'content': token_chunk}}, ensure_ascii=False)}\n\n"
                        full_response += token_chunk

                metrics_data = graph_result.get("metrics") or {
                    "retrieval_mode": request.rag_config.retrieval_mode,
                    "vector_backend": settings.VECTOR_BACKEND,
                    "elapsed_sec": None,
                }
                metrics_data = dict(metrics_data or {})
                retrieval_mode_used = metrics_data.get("retrieval_mode") or request.rag_config.retrieval_mode
                vector_backend_used = metrics_data.get("vector_backend") or settings.VECTOR_BACKEND

                structured_data = None
                structured_parse_meta = {"ok": False, "method": None, "error": None}
                if request.structured_output:
                    structured_data, structured_parse_meta = parse_json_from_text(full_response, expected="object")
                    metrics_data["structured_parse_ok"] = bool(structured_parse_meta.get("ok"))
                    metrics_data["structured_parse_method"] = structured_parse_meta.get("method")
                    metrics_data["structured_parse_error"] = structured_parse_meta.get("error")
                    metrics_data["structured_type"] = type(structured_data).__name__ if structured_data is not None else None
                    metrics_data["structured_preset"] = request.structured_preset

                done_payload = {
                    "type": "done",
                    "data": {
                        "assistant_message_id": str(assistant_message_id),
                        "conversation_id": str(conversation_id) if conversation_id else None,
                        "total_tokens": num_tokens_from_string(full_response or ""),
                        "total_chars": len(full_response or ""),
                        "citations_count": len(citations_data),
                        "model_used": graph_result.get("model_used"),
                        "route": graph_result.get("route"),
                        "retrieval_mode": retrieval_mode_used,
                        "vector_backend": vector_backend_used,
                        "metrics": metrics_data,
                        "structured": bool(structured_parse_meta.get("ok")) and structured_data is not None,
                        "structured_data": structured_data,
                    },
                    "request_id": str(request_id),
                }
                yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
                log_metrics(
                    {
                        "event": "rag_done",
                        "conversation_id": str(conversation_id) if conversation_id else None,
                        "tenant_id": str(tenant_id) if tenant_id else None,
                        "vector_backend": vector_backend_used,
                        "retrieval_mode": retrieval_mode_used,
                        "route": graph_result.get("route"),
                        "model_used": graph_result.get("model_used"),
                        "metrics": metrics_data,
                        "request_id": str(request_id),
                    }
                )

                assistant_message = Message(
                    id=assistant_message_id,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    role='assistant',
                    content=full_response,
                    citations=citations_data,
                    token_count=num_tokens_from_string(full_response or ""),
                    message_metadata={**(metrics_data or {}), "request_id": str(request_id)},
                )
                db.add(assistant_message)

                conversation.message_count += 1
                conversation.updated_at = datetime.utcnow()
                db.commit()
                return

            except Exception as e:  # noqa: BLE001
                logger.error("LangGraph stream error: %s", str(e)[:200])
                error_event = {
                    "type": "error",
                    "data": {
                        "message": "An error occurred during chat processing",
                        "conversation_id": str(conversation_id) if conversation_id else None,
                    },
                    "request_id": str(request_id),
                }
                yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
                return

        try:
            # Use the LangChain engine.
            engine = get_rag_engine()
            async for event in engine.stream_chat(
                question=request.message,
                history=[m.model_dump() for m in request.history] + long_term_messages,
                conversation_id=conversation_id,
                document_ids=doc_ids_to_use,
                metadata_filter=request.rag_config.metadata_filter,
                top_k=request.rag_config.top_k,
                score_threshold=request.rag_config.score_threshold,
                tenant_id=tenant_id,
                structured_output=request.structured_output,
                retrieval_mode=request.rag_config.retrieval_mode,
                alpha=request.rag_config.alpha,
                enable_weight_rerank=request.rag_config.enable_weight_rerank,
                vector_weight=request.rag_config.vector_weight,
                keyword_weight=request.rag_config.keyword_weight,
                mmr_lambda=request.rag_config.mmr_lambda,
                enable_reranker=request.rag_config.enable_reranker,
                reranker_provider=request.rag_config.reranker_provider,
                reranker_top_n=request.rag_config.reranker_top_n,
                structured_preset=request.structured_preset,
                prompt_template_id=request.prompt_template_id,
                prompt_template_key=request.prompt_template_key,
                prompt_ab_experiment_key=request.prompt_ab_experiment_key,
                ab_user_key=account_id,
                db=db,
                request_id=str(request_id),
            ):
                # Capture citations.
                if event['type'] == 'citations':
                    citations_data = event['data']
                if event['type'] == 'done':
                    if isinstance(event.get("data"), dict):
                        event["data"]["assistant_message_id"] = str(assistant_message_id)
                    metrics_data = event['data'].get("metrics", {})

                # Accumulate full response.
                if event['type'] == 'token':
                    full_response += event['data']['content']

                # Stream SSE events.
                event["request_id"] = str(request_id)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            # 4. Persist assistant response.
            assistant_message = Message(
                id=assistant_message_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role='assistant',
                content=full_response,
                citations=citations_data,
                token_count=num_tokens_from_string(full_response or ""),
                message_metadata={**(metrics_data or {}), "request_id": str(request_id)}
            )
            db.add(assistant_message)

            # Update conversation metadata.
            conversation.message_count += 1
            conversation.updated_at = datetime.utcnow()
            db.commit()

        except Exception as e:
            logger.error("Chat stream error: %s", str(e)[:200])
            is_production = is_production_env()
            detail = _format_stream_error_message(e)
            message = "An error occurred during chat processing"
            if not is_production and detail:
                message = f"{message}: {detail[:200]}"
            error_event = {
                "type": "error",
                "data": {
                    "message": message,
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "error_id": str(request_id),
                },
                "request_id": str(request_id),
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/conversations", response_model=ConversationSchema, status_code=201)
async def create_conversation(
    request: ConversationCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """Create a new conversation."""
    allow_empty_docs = bool(getattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True))
    if request.document_ids:
        allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, request.document_ids)
    else:
        allowed_doc_ids = list_accessible_document_ids(db, tenant_id, account_id, status="completed")
    if not allowed_doc_ids and not allow_empty_docs:
        raise HTTPException(status_code=400, detail="No accessible documents for conversation")
    conversation = Conversation(
        tenant_id=tenant_id,
        title=request.title,
        document_ids=allowed_doc_ids
    )

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return conversation


@router.get("/conversations", response_model=ConversationList)
async def list_conversations(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """List conversations."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    query = db.query(Conversation).filter(Conversation.tenant_id == tenant_id)
    total = query.count()

    conversations_raw = query.order_by(
        Conversation.updated_at.desc()
    ).offset(skip).limit(limit).all()

    doc_ids_by_conversation_id: dict[UUID, list[UUID]] = {}
    all_doc_ids: set[UUID] = set()
    for conv in conversations_raw:
        doc_ids = list(getattr(conv, "document_ids", None) or [])
        doc_ids_by_conversation_id[conv.id] = doc_ids
        all_doc_ids.update(doc_ids)

    allowed_doc_ids: set[UUID] = set()
    missing_doc_ids: set[UUID] = set()
    if all_doc_ids:
        allowed_doc_ids, missing_doc_ids = get_allowed_document_id_sets(
            db,
            tenant_id,
            account_id,
            list(all_doc_ids),
            check_member=False,
        )

    conversations = []
    for conv in conversations_raw:
        doc_ids = doc_ids_by_conversation_id.get(conv.id) or []
        if not doc_ids:
            conversations.append(conv)
            continue
        doc_id_set = set(doc_ids)
        if doc_id_set & missing_doc_ids:
            continue
        if doc_id_set & allowed_doc_ids:
            conversations.append(conv)

    result_items = []
    last_message_by_conversation_id: dict[UUID, Message] = {}
    conv_ids = [conv.id for conv in conversations]
    if conv_ids:
        latest_message_subq = (
            db.query(
                Message.id.label("id"),
                Message.conversation_id.label("conversation_id"),
                func.row_number()
                .over(
                    partition_by=Message.conversation_id,
                    order_by=(Message.created_at.desc(), Message.id.desc()),
                )
                .label("rn"),
            )
            .filter(
                Message.tenant_id == tenant_id,
                Message.conversation_id.in_(conv_ids),
            )
            .subquery()
        )
        latest_messages = (
            db.query(Message)
            .join(latest_message_subq, Message.id == latest_message_subq.c.id)
            .filter(latest_message_subq.c.rn == 1)
            .all()
        )
        last_message_by_conversation_id = {m.conversation_id: m for m in latest_messages}

    for conv in conversations:
        conv_dict = {
            "id": conv.id,
            "title": conv.title,
            "message_count": conv.message_count,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
            "last_message": None
        }

        last_msg = last_message_by_conversation_id.get(conv.id)
        if last_msg:
            conv_dict["last_message"] = last_msg.content[:100] + "..." if len(last_msg.content) > 100 else last_msg.content

        result_items.append(conv_dict)

    return {
        "total": total,
        "items": result_items
    }


@router.get("/conversations/{conversation_id}/messages", response_model=ConversationDetail)
async def get_conversation_messages(
    conversation_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """Fetch conversation history."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.tenant_id == tenant_id
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    _ensure_conversation_access(db, tenant_id, account_id, conversation)

    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.tenant_id == tenant_id
    ).order_by(Message.created_at.asc()).all()

    return {
        "conversation_id": conversation_id,
        "messages": messages
    }


def _checkpoint_values_to_json(values: dict | None) -> dict:
    data = dict(values or {})
    data.pop("docs", None)
    return jsonable_encoder(data)


@router.get("/conversations/{conversation_id}/checkpoints", response_model=CheckpointListResponse)
async def list_conversation_checkpoints(
    conversation_id: UUID,
    limit: int = Query(default=20, ge=1, le=200),
    before: Optional[str] = Query(default=None),
    include_values: bool = Query(default=False),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """List LangGraph checkpoints for this conversation (time-travel/debug)."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.tenant_id == tenant_id,
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _ensure_conversation_access(db, tenant_id, account_id, conversation)

    from app.rag.pipelines.langgraph import build_rag_graph

    graph = build_rag_graph()
    thread_id = str(conversation_id)
    base_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    before_config = (
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": "", "checkpoint_id": before}} if before else None
    )

    snapshots = list(graph.get_state_history(base_config, before=before_config, limit=limit))
    items = []
    for snap in reversed(snapshots):
        cfg = (snap.config or {}).get("configurable") or {}
        item = {
            "checkpoint_id": cfg.get("checkpoint_id"),
            "checkpoint_ns": cfg.get("checkpoint_ns", ""),
            "created_at": getattr(snap, "created_at", None),
            "next": getattr(snap, "next", None),
            "metadata": getattr(snap, "metadata", None),
        }
        if include_values:
            item["values"] = _checkpoint_values_to_json(getattr(snap, "values", None))
        items.append(jsonable_encoder(item))

    return {"thread_id": thread_id, "items": items}


@router.get("/conversations/{conversation_id}/checkpoints/{checkpoint_id}", response_model=CheckpointDetailResponse)
async def get_conversation_checkpoint(
    conversation_id: UUID,
    checkpoint_id: str,
    include_values: bool = Query(default=True),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Get a checkpoint snapshot (docs are excluded by default)."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.tenant_id == tenant_id,
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _ensure_conversation_access(db, tenant_id, account_id, conversation)

    from app.rag.pipelines.langgraph import build_rag_graph

    graph = build_rag_graph()
    thread_id = str(conversation_id)
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "", "checkpoint_id": checkpoint_id}}
    snap = graph.get_state(config)
    if not snap or getattr(snap, "created_at", None) is None:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    cfg = (snap.config or {}).get("configurable") or {}
    payload = {
        "thread_id": thread_id,
        "checkpoint_id": cfg.get("checkpoint_id"),
        "checkpoint_ns": cfg.get("checkpoint_ns", ""),
        "created_at": getattr(snap, "created_at", None),
        "next": getattr(snap, "next", None),
        "metadata": getattr(snap, "metadata", None),
    }
    if include_values:
        payload["values"] = _checkpoint_values_to_json(getattr(snap, "values", None))
    return jsonable_encoder(payload)


@router.delete("/conversations/{conversation_id}/checkpoints", status_code=204)
async def delete_conversation_checkpoints(
    conversation_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Clear checkpoints for this conversation (does not delete messages or the conversation)."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.tenant_id == tenant_id,
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _ensure_conversation_access(db, tenant_id, account_id, conversation)

    from app.rag.checkpointer.factory import get_checkpointer

    saver = get_checkpointer()
    saver.delete_thread(str(conversation_id))
    return None


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """Delete a conversation."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.tenant_id == tenant_id
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    _ensure_conversation_access(db, tenant_id, account_id, conversation)

    db.delete(conversation)
    db.commit()

    return None
