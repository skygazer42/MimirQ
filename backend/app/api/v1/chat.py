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
from app.services.rag_agent import rag_agent
from app.core.config import settings
from app.dependencies.tenant import get_tenant_id
from app.dependencies.auth import get_current_account_id

router = APIRouter()


def _filter_allowed_document_ids(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    doc_ids: Optional[List[UUID]]
) -> List[UUID]:
    if doc_ids is None:
        doc_ids = []

    if not doc_ids:
        return []

    documents = db.query(DBDocument).filter(
        DBDocument.tenant_id == tenant_id,
        DBDocument.id.in_(doc_ids)
    ).all()

    found_ids = {doc.id for doc in documents}
    missing = set(doc_ids) - found_ids
    if missing:
        raise HTTPException(status_code=404, detail=f"Documents not found: {', '.join([str(m) for m in missing])}")

    allowed: list[UUID] = []
    for doc in documents:
        if doc.dataset_id:
            ds = DatasetService.get_dataset(db, tenant_id, doc.dataset_id)
            if DatasetService.check_dataset_permission(db, ds, account_id):
                allowed.append(doc.id)
        else:
            # legacy document without dataset binding: allow for now
            allowed.append(doc.id)

    if not allowed:
        raise HTTPException(status_code=403, detail="No accessible documents for this request")

    return allowed


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
    allowed = _filter_allowed_document_ids(db, tenant_id, account_id, conv.document_ids)
    return allowed


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
            allowed_doc_ids = _filter_allowed_document_ids(db, tenant_id, account_id, target_doc_ids)
        else:
            allowed_doc_ids = []
            raise HTTPException(status_code=400, detail="document_ids are required for chat retrieval")
        # 更新会话中的文档列表为当前允许的集合
        conversation.document_ids = allowed_doc_ids
        db.commit()
    else:
        # 创建新对话
        allowed_doc_ids = _filter_allowed_document_ids(db, tenant_id, account_id, request.document_ids or [])
        if not allowed_doc_ids:
            raise HTTPException(status_code=400, detail="document_ids are required for chat retrieval")
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

    # 更新对话消息计数
    conversation.message_count += 1
    db.commit()

    # 3. 流式响应函数
    async def event_stream():
        nonlocal citations_data, full_response
        doc_ids_to_use = allowed_doc_ids or []

        try:
            # 使用 LangChain Agent
            async for event in rag_agent.stream_chat(
                question=request.message,
                conversation_id=conversation_id,
                document_ids=doc_ids_to_use,
                top_k=request.rag_config.get('top_k', settings.RETRIEVAL_TOP_K),
                tenant_id=tenant_id
            ):
                # 记录引用信息
                if event['type'] == 'citations':
                    citations_data = event['data']

                # 累积完整回复
                if event['type'] == 'token':
                    full_response += event['data']['content']

                # SSE 输出
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            # 4. 保存助手回复到数据库
            assistant_message = Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role='assistant',
                content=full_response,
                citations=citations_data,
                token_count=len(full_response)
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
    allowed_doc_ids = _filter_allowed_document_ids(db, tenant_id, account_id, request.document_ids or [])
    if not allowed_doc_ids:
        raise HTTPException(status_code=400, detail="document_ids are required for conversation")
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
