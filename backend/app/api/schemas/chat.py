"""
对话相关 Pydantic Schema
"""
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from app.rag.core.text import normalize_retrieval_mode

from .base import OrmModel

class Citation(BaseModel):
    """引用信息"""
    document_id: UUID
    document_name: str
    chunk_id: UUID
    chunk_content: str
    matched_terms: Optional[List[str]] = None
    page_number: Optional[int] = None
    relevance_score: float = 0.0
    vector_score: Optional[float] = None
    bm25_score: Optional[float] = None
    keyword_score: Optional[float] = None
    rerank_score: Optional[float] = None
    retrieval_score: Optional[float] = None
    reranker_provider: Optional[str] = None
    rerank_elapsed_sec: Optional[float] = None
    rerank_model_used: Optional[str] = None
    retrieval_mode: Optional[str] = None
    vector_backend: Optional[str] = None
    retrieval_elapsed_sec: Optional[float] = None
    hit_type: Optional[str] = None  # vector | keyword | mmr | hybrid
    # 图片相关字段
    has_image: bool = Field(default=False, description="该引用是否包含图片")
    img_id: Optional[str] = Field(default=None, description="图片 ID（MinIO 格式：{tenant_id}:{dataset_id}:{document_id}:{chunk_index}）")
    img_url: Optional[str] = Field(default=None, description="图片访问 URL")


class MessageSchema(OrmModel):
    """消息"""
    id: UUID
    role: str  # user | assistant
    content: str
    citations: List[Citation] = []
    message_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime


class ConversationCreate(BaseModel):
    """创建对话"""
    title: Optional[str] = None
    document_ids: List[UUID] = Field(default_factory=list)


class ConversationSchema(OrmModel):
    """对话会话"""
    id: UUID
    title: Optional[str] = None
    last_message: Optional[str] = None
    message_count: int
    created_at: datetime
    updated_at: datetime


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


class ChatRAGConfig(BaseModel):
    """Chat 接口专用的 RAG 参数。"""

    top_k: int = Field(default=5, ge=1, le=100)
    score_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    max_tokens: int = Field(default=2000, ge=1, le=200_000)

    retrieval_mode: str = Field(default="hybrid")  # hybrid | vector | keyword | mmr | auto
    alpha: float = Field(default=0.6, ge=0.0, le=1.0)  # hybrid merge weight: vector vs keyword

    enable_weight_rerank: bool = True
    vector_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0)

    enable_reranker: bool = False  # optional: LLM/API rerank
    reranker_provider: str = "llm"  # llm | pc | none
    reranker_top_n: int = Field(default=20, ge=1, le=200)

    # LangGraph path toggles
    use_graph: bool = False

    # Optional: metadata filter for vector search / retrieval scoping
    metadata_filter: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="ignore")

    @field_validator("retrieval_mode", mode="before")
    @classmethod
    def _normalize_retrieval_mode(cls, v: Any) -> str:
        return normalize_retrieval_mode(str(v) if v is not None else None)

class ChatRequest(BaseModel):
    """聊天请求"""
    conversation_id: Optional[UUID] = None
    message: str
    history: List[HistoryMessage] = Field(default_factory=list)  # 对话历史
    document_ids: List[UUID] = Field(default_factory=list)
    stream: bool = True
    structured_output: bool = False  # 是否要求结构化(JSON)输出
    structured_preset: Optional[str] = None  # faq | summary | action_items | custom
    enable_long_term_memory: bool = False  # 是否启用长期记忆召回
    prompt_template_id: Optional[UUID] = None  # 自定义提示词模板 ID
    prompt_template_key: Optional[str] = None  # 按 key 选择最新版本（可选）
    prompt_ab_experiment_key: Optional[str] = None  # A/B 实验 key（可选，按用户稳定分流）
    rag_config: ChatRAGConfig = Field(default_factory=ChatRAGConfig)


class StreamEvent(BaseModel):
    """流式事件"""
    type: str  # citations | token | done | error
    data: Any
