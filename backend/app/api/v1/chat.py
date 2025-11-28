"""
对话 API
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
import json
import uuid
from datetime import datetime

from app.database import get_db
from app.models.chat import Conversation, Message
from app.schemas.chat import (
    ChatRequest,
    ConversationCreate,
    ConversationSchema,
    ConversationDetail,
    ConversationList,
    MessageSchema
)
from app.services.rag_agent import rag_agent
from app.config import settings

router = APIRouter()


@router.post("/stream")
async def stream_chat(
    request: ChatRequest,
    db: Session = Depends(get_db)
):
    """
    流式对话接口 - 核心功能

    流程：
    1. 创建或获取对话会话
    2. 保存用户消息
    3. RAG 检索 + LLM 流式生成
    4. 保存助手回复
    """

    conversation_id = request.conversation_id
    citations_data = []
    full_response = ""

    # 1. 获取或创建对话
    if conversation_id:
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id
        ).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        # 创建新对话
        conversation = Conversation(
            title=request.message[:50] + "..." if len(request.message) > 50 else request.message,
            document_ids=request.document_ids or []
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        conversation_id = conversation.id

    # 2. 保存用户消息
    user_message = Message(
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

        try:
            # 使用 LangChain Agent (自动管理对话历史)
            async for event in rag_agent.stream_chat(
                question=request.message,
                conversation_id=conversation_id,
                document_ids=request.document_ids,
                top_k=request.rag_config.get('top_k', settings.RETRIEVAL_TOP_K)
            ):
                # 记录引用信息
                if event['type'] == 'citations':
                    citations_data = event['data']

                # 累积完整回复
                if event['type'] == 'token':
                    full_response += event['data']['content']

                # SSE 格式输出
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            # 4. 保存助手回复到数据库
            assistant_message = Message(
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
            # 错误事件
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
    db: Session = Depends(get_db)
):
    """
    创建新对话
    """
    conversation = Conversation(
        title=request.title,
        document_ids=request.document_ids or []
    )

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return conversation


@router.get("/conversations", response_model=ConversationList)
async def list_conversations(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """
    获取对话列表
    """
    query = db.query(Conversation)
    total = query.count()

    conversations = query.order_by(
        Conversation.updated_at.desc()
    ).offset(skip).limit(limit).all()

    # 添加最后一条消息预览
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

        # 获取最后一条消息
        last_msg = db.query(Message).filter(
            Message.conversation_id == conv.id
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
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    获取对话历史
    """
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.created_at.asc()).all()

    return {
        "conversation_id": conversation_id,
        "messages": messages
    }


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    删除对话
    """
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db.delete(conversation)
    db.commit()

    return None
