"""
RAGAS evaluation schemas.

Defines data models for evaluation tasks and results.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from .base import OrmModel


class RagasRunCreateRequest(BaseModel):
    """Create a RAGAS evaluation run for a conversation."""

    conversation_id: UUID = Field(..., description="要评测的对话 ID")
    metrics: List[str] = Field(
        default_factory=lambda: ["faithfulness", "response_relevancy"],
        description="评测指标列表（默认: faithfulness, response_relevancy）",
    )
    max_turns: int = Field(default=20, ge=1, le=200, description="最多评测最近 N 轮问答")
    skip_empty_contexts: bool = Field(default=True, description="跳过没有引用/上下文的轮次")
    include_contexts_in_response: bool = Field(default=False, description="在明细中返回 contexts（可能较大）")


class RagasRunSchema(OrmModel):
    """Evaluation run metadata."""

    id: UUID
    conversation_id: Optional[UUID] = None
    status: str
    metrics: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class RagasItemSchema(OrmModel):
    """Per-turn evaluation item."""

    id: UUID
    run_id: UUID
    turn_index: int
    user_message_id: Optional[UUID] = None
    assistant_message_id: Optional[UUID] = None
    user_input: str
    response: str
    retrieved_contexts: Optional[List[str]] = None
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    scores: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RagasRunDetail(BaseModel):
    run: RagasRunSchema
    items: List[RagasItemSchema] = Field(default_factory=list)


class RagasRunList(BaseModel):
    total: int
    items: List[RagasRunSchema]


# ==================== Test question generation schemas ====================


class TestGenFromDocsRequest(BaseModel):
    """Request to generate test questions from documents."""
    
    dataset_id: Optional[UUID] = Field(default=None, description="知识库 ID（可选）")
    document_ids: List[UUID] = Field(default_factory=list, description="文档 ID 列表（优先于 dataset_id）")
    num_questions: int = Field(default=10, ge=1, le=50, description="生成问题数量")
    question_types: List[str] = Field(
        default_factory=lambda: ["factual", "reasoning", "comparison"],
        description="问题类型：factual（事实型）、reasoning（推理型）、comparison（对比型）"
    )
    auto_save_as_cases: bool = Field(default=True, description="自动保存为回归测试用例")


class TestGenFromConversationsRequest(BaseModel):
    """Request to generate test questions from conversation history."""
    
    conversation_ids: List[UUID] = Field(..., min_length=1, description="对话 ID 列表")
    num_questions: int = Field(default=10, ge=1, le=50, description="生成问题数量")
    quality_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="质量阈值")
    auto_save_as_cases: bool = Field(default=True, description="自动保存为回归测试用例")


class GeneratedQuestion(BaseModel):
    """Generated question."""
    
    question: str = Field(..., description="问题内容")
    expected_answer: Optional[str] = Field(default=None, description="期望答案")
    context: Optional[str] = Field(default=None, description="问题来源上下文")
    source_type: str = Field(..., description="来源类型：document 或 conversation")
    source_id: str = Field(..., description="来源 ID")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


class TestGenResponse(BaseModel):
    """Test question generation response."""
    
    status: str = Field(..., description="状态：completed 或 failed")
    generated_questions: List[GeneratedQuestion] = Field(default_factory=list, description="生成的问题列表")
    saved_case_ids: List[UUID] = Field(default_factory=list, description="已保存为用例的 ID 列表")
    error_message: Optional[str] = Field(default=None, description="错误信息（如果失败）")
