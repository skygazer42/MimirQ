"""
对话 API（含租户隔离）
"""
from uuid import UUID
import uuid
from datetime import datetime
import json
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import jieba
from langchain_core.documents import Document
from langchain_community.retrievers.bm25 import BM25Retriever

from app.core.database import get_db
from app.models.chat import Conversation, Message
from app.models.document import Document as DBDocument
from app.services.dataset_service import DatasetService
from app.schemas.chat import (
    ChatRequest,
    ConversationCreate,
    ConversationSchema,
    ConversationDetail,
    ConversationList,
)
from app.services.document_access import filter_allowed_document_ids, list_accessible_document_ids
from app.rag.engine import get_rag_engine
from app.rag.graph import run_rag_graph
from app.services.metrics_logger import log_metrics
from app.core.config import settings
from app.dependencies.tenant import get_tenant_id
from app.dependencies.auth import get_current_account_id

router = APIRouter()


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
    allowed = filter_allowed_document_ids(db, tenant_id, account_id, conv.document_ids)
    return allowed


def _retrieve_long_term_messages(
    db: Session,
    conversation_id: UUID,
    tenant_id: UUID,
    query: str,
    top_k: int = 3
) -> List[dict]:
    """
    简单的长期记忆召回：对历史消息做 BM25 检索，取最相关的若干条。
    仅用于追加到 history 以提供额外上下文，不修改存储。
    """
    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.tenant_id == tenant_id
    ).order_by(Message.created_at.asc()).all()

    docs: List[Document] = []
    for msg in messages:
        if not msg.content or len(msg.content.strip()) < settings.LONG_TERM_MEMORY_MIN_LEN:
            continue
        docs.append(
            Document(
                page_content=msg.content,
                metadata={
                    "role": msg.role,
                    "created_at": msg.created_at.isoformat()
                }
            )
        )

    if not docs:
        return []

    retriever = BM25Retriever.from_documents(
        docs,
        preprocess_func=lambda text: list(jieba.cut_for_search(text)),
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
    request: ChatRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """
    流式对话接口 - 核心功能
    """

    conversation_id = request.conversation_id
    citations_data = []
    full_response = ""
    allowed_doc_ids: list[UUID] = []
    long_term_messages: list[dict] = []

    # 确认租户成员
    DatasetService.ensure_member(db, tenant_id, account_id)

    # 1. 获取或创建对话
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
            # 默认：使用当前用户可访问的文档（避免前端未传 document_ids 时直接报错）
            allowed_doc_ids = list_accessible_document_ids(db, tenant_id, account_id, status="completed")
            if not allowed_doc_ids:
                raise HTTPException(status_code=400, detail="No accessible documents for chat retrieval")
        # 更新会话中的文档列表为当前允许的集合
        conversation.document_ids = allowed_doc_ids
        db.commit()
    else:
        # 创建新对话
        if request.document_ids:
            allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, request.document_ids)
        else:
            allowed_doc_ids = list_accessible_document_ids(db, tenant_id, account_id, status="completed")
        if not allowed_doc_ids:
            raise HTTPException(status_code=400, detail="No accessible documents for chat retrieval")
        conversation = Conversation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            title=request.message[:50] + "..." if len(request.message) > 50 else request.message,
            document_ids=allowed_doc_ids
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        conversation_id = conversation.id

    # 2. 保存用户消息
    user_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role='user',
        content=request.message
    )
    db.add(user_message)
    db.commit()

    # 可选：长期记忆召回（基于 BM25 的对话消息检索）
    if request.enable_long_term_memory and settings.LONG_TERM_MEMORY_ENABLED and conversation_id:
        long_term_messages = _retrieve_long_term_messages(
            db=db,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            query=request.message,
            top_k=settings.LONG_TERM_MEMORY_TOP_K
        )

    # 更新对话消息计数
    conversation.message_count += 1
    db.commit()

    # 3. 流式响应函数
    async def event_stream():
        nonlocal citations_data, full_response
        doc_ids_to_use = allowed_doc_ids or []
        request_id = uuid.uuid4()
        metrics_data = {}

        # 非流式 LangGraph 快捷通道：更快出完整答复，用于工具/Agent风格编排
        if request.rag_config.get("use_graph") and not request.stream:
            graph_result = run_rag_graph(
                question=request.message,
                history=[m.model_dump() for m in (request.history or [])] + long_term_messages,
                document_ids=doc_ids_to_use,
                tenant_id=tenant_id,
                top_k=request.rag_config.get('top_k', settings.RETRIEVAL_TOP_K),
                score_threshold=request.rag_config.get('score_threshold', settings.SIMILARITY_THRESHOLD),
                retrieval_mode=request.rag_config.get('retrieval_mode', 'hybrid'),
                alpha=request.rag_config.get('alpha', 0.6),
                enable_weight_rerank=request.rag_config.get('enable_weight_rerank', True),
                vector_weight=request.rag_config.get('vector_weight', 0.6),
                keyword_weight=request.rag_config.get('keyword_weight', 0.4),
                mmr_lambda=request.rag_config.get('mmr_lambda', settings.RETRIEVAL_MMR_LAMBDA),
                enable_reranker=request.rag_config.get('enable_reranker', settings.ENABLE_RERANKER),
                reranker_provider=request.rag_config.get('reranker_provider', settings.RERANKER_PROVIDER),
                reranker_top_n=request.rag_config.get('reranker_top_n', settings.RERANKER_TOP_N),
                structured_preset=request.structured_preset,
                structured_output=request.structured_output,
                prompt_template_id=request.prompt_template_id,
                prompt_template_key=request.prompt_template_key,
                prompt_ab_experiment_key=request.prompt_ab_experiment_key,
                ab_user_key=account_id,
                db=db,
            )
            citations_data = graph_result.get("citations", [])
            yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'citations', 'data': citations_data}, ensure_ascii=False)}\n\n"
            answer_text = graph_result.get("answer", "")
            # 模拟流式输出：按 120 字节分块
            chunk_size = 120
            for i in range(0, len(answer_text), chunk_size):
                token_chunk = answer_text[i:i+chunk_size]
                yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'token', 'data': {'content': token_chunk}}, ensure_ascii=False)}\n\n"
                full_response += token_chunk
            metrics_data = graph_result.get("metrics") or {
                "retrieval_mode": request.rag_config.get('retrieval_mode', 'hybrid'),
                "vector_backend": settings.VECTOR_BACKEND,
                "elapsed_sec": None,
            }
            done_payload = {
                "type": "done",
                "data": {
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "total_tokens": len(full_response),
                    "citations_count": len(citations_data),
                    "model_used": graph_result.get("model_used"),
                    "route": graph_result.get("route"),
                    "retrieval_mode": request.rag_config.get('retrieval_mode', 'hybrid'),
                    "vector_backend": settings.VECTOR_BACKEND,
                    "metrics": metrics_data,
                    "structured": False,
                    "structured_data": None,
                },
                "request_id": str(request_id),
            }
            yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
            log_metrics(
                {
                    "event": "rag_done",
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "vector_backend": settings.VECTOR_BACKEND,
                    "retrieval_mode": request.rag_config.get('retrieval_mode', 'hybrid'),
                    "route": graph_result.get("route"),
                    "model_used": graph_result.get("model_used"),
                    "metrics": metrics_data,
                    "request_id": str(request_id),
                }
            )

            # 保存助手回复到数据库（Graph 路径同样需要持久化）
            assistant_message = Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role='assistant',
                content=full_response,
                citations=citations_data,
                token_count=len(full_response),
                message_metadata={**(metrics_data or {}), "request_id": str(request_id)}
            )
            db.add(assistant_message)

            # 更新对话
            conversation.message_count += 1
            conversation.updated_at = datetime.utcnow()
            db.commit()
            return

        try:
            # 使用 LangChain Agent
            engine = get_rag_engine()
            async for event in engine.stream_chat(
                question=request.message,
                history=[m.model_dump() for m in (request.history or [])] + long_term_messages,
                conversation_id=conversation_id,
                document_ids=doc_ids_to_use,
                top_k=request.rag_config.get('top_k', settings.RETRIEVAL_TOP_K),
                score_threshold=request.rag_config.get('score_threshold', settings.SIMILARITY_THRESHOLD),
                tenant_id=tenant_id,
                structured_output=request.structured_output,
                retrieval_mode=request.rag_config.get('retrieval_mode', 'hybrid'),
                alpha=request.rag_config.get('alpha', 0.6),
                enable_weight_rerank=request.rag_config.get('enable_weight_rerank', True),
                vector_weight=request.rag_config.get('vector_weight', 0.6),
                keyword_weight=request.rag_config.get('keyword_weight', 0.4),
                mmr_lambda=request.rag_config.get('mmr_lambda', settings.RETRIEVAL_MMR_LAMBDA),
                enable_reranker=request.rag_config.get('enable_reranker', settings.ENABLE_RERANKER),
                reranker_provider=request.rag_config.get('reranker_provider', settings.RERANKER_PROVIDER),
                reranker_top_n=request.rag_config.get('reranker_top_n', settings.RERANKER_TOP_N),
                structured_preset=request.structured_preset,
                prompt_template_id=request.prompt_template_id,
                prompt_template_key=request.prompt_template_key,
                prompt_ab_experiment_key=request.prompt_ab_experiment_key,
                ab_user_key=account_id,
                db=db,
                request_id=str(request_id),
            ):
                # 记录引用信息
                if event['type'] == 'citations':
                    citations_data = event['data']
                if event['type'] == 'done':
                    metrics_data = event['data'].get("metrics", {})

                # 累积完整回复
                if event['type'] == 'token':
                    full_response += event['data']['content']

                # SSE 输出
                event["request_id"] = str(request_id)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            # 4. 保存助手回复到数据库
            assistant_message = Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role='assistant',
                content=full_response,
                citations=citations_data,
                token_count=len(full_response),
                message_metadata={**(metrics_data or {}), "request_id": str(request_id)}
            )
            db.add(assistant_message)

            # 更新对话
            conversation.message_count += 1
            conversation.updated_at = datetime.utcnow()
            db.commit()

        except Exception as e:
            error_event = {
                "type": "error",
                "data": {"message": str(e)}
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
    """创建新对话"""
    if request.document_ids:
        allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, request.document_ids)
    else:
        allowed_doc_ids = list_accessible_document_ids(db, tenant_id, account_id, status="completed")
    if not allowed_doc_ids:
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
    skip: int = 0,
    limit: int = 20,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """获取对话列表"""
    DatasetService.ensure_member(db, tenant_id, account_id)
    query = db.query(Conversation).filter(Conversation.tenant_id == tenant_id)
    total = query.count()

    conversations_raw = query.order_by(
        Conversation.updated_at.desc()
    ).offset(skip).limit(limit).all()

    conversations = []
    for conv in conversations_raw:
        try:
            _ensure_conversation_access(db, tenant_id, account_id, conv)
            conversations.append(conv)
        except HTTPException:
            # skip conversations the user cannot access
            continue

    result_items = []
    for conv in conversations:
        conv_dict = {
            "id": conv.id,
            "title": conv.title,
            "message_count": conv.message_count,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
            "last_message": None
        }

        last_msg = db.query(Message).filter(
            Message.conversation_id == conv.id,
            Message.tenant_id == tenant_id
        ).order_by(Message.created_at.desc()).first()

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
    """获取对话历史"""
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


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    """删除对话"""
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
