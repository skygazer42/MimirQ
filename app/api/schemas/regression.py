"""
RAGAS 回归集（Regression Suite）相关 Schema。

目标：把"固定的一组问题"沉淀为可复用回归用例，支持在不同 prompt/模型/检索策略下重复跑评测，
并将结果落表，形成持续迭代闭环。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from .base import OrmModel

class RagasRegressionCaseCreateRequest(BaseModel):
    question: str = Field(..., min_length=1, description="问题（回归用例的 user_input）")
    dataset_id: Optional[UUID] = Field(default=None, description="知识库/数据集 ID（可选）")
    document_ids: List[UUID] = Field(default_factory=list, description="限制文档范围（可选，优先于 dataset_id）")
    expected_answer: Optional[str] = Field(default=None, description="期望答案（可选，用于人工对比/监督）")
    tags: List[str] = Field(default_factory=list, description="标签（可选）")
    extra: Dict[str, Any] = Field(default_factory=dict, description="扩展字段（可选）")


class RagasRegressionCaseOut(OrmModel):
    id: UUID
    tenant_id: UUID
    dataset_id: Optional[UUID] = None
    document_ids: List[UUID] = Field(default_factory=list)
    question: str
    expected_answer: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class RagasRegressionCaseList(BaseModel):
    total: int
    items: List[RagasRegressionCaseOut]


class RagasRegressionRunCreateRequest(BaseModel):
    case_ids: List[UUID] = Field(default_factory=list, description="要运行的 case id 列表（为空则按过滤条件选择）")
    dataset_id: Optional[UUID] = Field(default=None, description="仅运行某个 dataset 下的用例（可选）")
    metrics: List[str] = Field(
        default_factory=lambda: ["faithfulness", "response_relevancy"],
        description="RAGAS 指标列表",
    )
    skip_empty_contexts: bool = Field(default=True, description="跳过无 contexts 的用例（默认 true）")
    max_cases: int = Field(default=50, ge=1, le=500, description="最多跑多少条用例（默认 50）")

    # 检索配置（与 chat.rag_config 对齐，便于对比）
    top_k: int = Field(default=5, ge=1, le=50)
    score_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    retrieval_mode: str = Field(default="hybrid", description="hybrid | vector | keyword | mmr")
    alpha: float = Field(default=0.6, ge=0.0, le=1.0)
    enable_weight_rerank: bool = Field(default=True)
    vector_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0)
    enable_reranker: bool = Field(default=False, description="是否启用 LLM reranker 精排")
    reranker_provider: str = Field(default="llm", description="reranker provider: llm | pc | none")
    reranker_top_n: int = Field(default=20, ge=1, le=200, description="精排候选数量（越大越慢）")

    # PromptTemplate 选择（可选：用于版本/A-B 对比）
    prompt_template_id: Optional[UUID] = None
    prompt_template_key: Optional[str] = None
    prompt_ab_experiment_key: Optional[str] = None


class RagasRegressionRunSchema(OrmModel):
    id: UUID
    tenant_id: UUID
    account_id: Optional[str] = None
    status: str
    metrics: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class RagasRegressionItemSchema(OrmModel):
    id: UUID
    run_id: UUID
    case_id: UUID
    question: str
    response: str
    retrieved_contexts: Optional[List[str]] = None
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    scores: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RagasRegressionRunDetail(BaseModel):
    run: RagasRegressionRunSchema
    items: List[RagasRegressionItemSchema] = Field(default_factory=list)


class RagasRegressionRunList(BaseModel):
    total: int
    items: List[RagasRegressionRunSchema]
