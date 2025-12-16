"""
对话相关 Pydantic Schema
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class Citation(BaseModel):
    """引用信息"""
    document_id: UUID
    document_name: str
    chunk_id: UUID
    chunk_content: str
    page_number: Optional[int] = None
    relevance_score: float = 0.0


class MessageSchema(BaseModel):
    """消息"""
    id: UUID
    role: str  # user | assistant
    content: str
    citations: List[Citation] = []
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationCreate(BaseModel):
    """创建对话"""
    title: Optional[str] = None
    document_ids: Optional[List[UUID]] = []


class ConversationSchema(BaseModel):
    """对话会话"""
    id: UUID
    title: Optional[str] = None
    last_message: Optional[str] = None
    message_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationDetail(BaseModel):
    """对话详情"""
    conversation_id: UUID
    messages: List[MessageSchema]


class ConversationList(BaseModel):
    """对话列表"""
    total: int
    items: List[ConversationSchema]


class HistoryMessage(BaseModel):
    """历史消息"""
    role: str  # user | assistant
    content: str


class ChatRequest(BaseModel):
    """聊天请求"""
    conversation_id: Optional[UUID] = None
    message: str
    history: Optional[List[HistoryMessage]] = []  # 对话历史
    document_ids: Optional[List[UUID]] = []
    stream: bool = True
    structured_output: bool = False  # 是否要求结构化(JSON)输出
    structured_preset: Optional[str] = None  # faq | summary | action_items | custom
    enable_long_term_memory: bool = False  # 是否启用长期记忆召回
    prompt_template_id: Optional[UUID] = None  # 自定义提示词模板 ID
    rag_config: Optional[Dict[str, Any]] = {
        "top_k": 5,
        "score_threshold": 0.7,
        "max_tokens": 2000,
        "retrieval_mode": "hybrid",  # hybrid | vector | keyword | mmr
        "alpha": 0.6,  # hybrid merge weight: vector vs keyword
        "enable_weight_rerank": True,
        "vector_weight": 0.6,
        "keyword_weight": 0.4,
        "mmr_lambda": 0.7,  # MMR 多样性权重
        "use_graph": False,  # 使用 LangGraph 编排（非流式快捷路径）
    }


class StreamEvent(BaseModel):
    """流式事件"""
    type: str  # citations | token | done | error
    data: Any
