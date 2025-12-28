"""
RAGAS evaluation run models (tenant isolated).
"""

import uuid
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class RagasEvaluationRun(Base):
    """RAGAS evaluation run record."""

    __tablename__ = "ragas_evaluation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    account_id = Column(String(255), nullable=True, index=True)
    conversation_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    status = Column(String(20), nullable=False, default="pending")  # pending|running|completed|failed
    metrics = Column(JSONB, default=list)  # metric names
    params = Column(JSONB, default=dict)  # request params snapshot
    summary = Column(JSONB, default=dict)  # aggregate scores
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    items = relationship(
        "RagasEvaluationItem",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class RagasEvaluationItem(Base):
    """Per-turn evaluation item."""

    __tablename__ = "ragas_evaluation_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ragas_evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    turn_index = Column(Integer, nullable=False)

    user_message_id = Column(UUID(as_uuid=True), nullable=True)
    assistant_message_id = Column(UUID(as_uuid=True), nullable=True)

    user_input = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    retrieved_contexts = Column(JSONB, default=list)  # list[str]
    citations = Column(JSONB, default=list)
    scores = Column(JSONB, default=dict)  # metric_name -> score

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    run = relationship("RagasEvaluationRun", back_populates="items")


class RagasRegressionCase(Base):
    """RAGAS 回归用例（固定问题集合）。"""

    __tablename__ = "ragas_regression_cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    # 限制检索范围（优先于 dataset_id）：存 UUID 字符串数组，避免 ARRAY 在跨库/迁移中变复杂
    document_ids = Column(JSONB, default=list)  # list[str]

    question = Column(Text, nullable=False)
    expected_answer = Column(Text, nullable=True)
    tags = Column(JSONB, default=list)
    extra = Column(JSONB, default=dict)

    created_by = Column(String(255), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RagasRegressionRun(Base):
    """RAGAS 回归运行记录（落表用于对比版本/A-B/策略）。"""

    __tablename__ = "ragas_regression_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    account_id = Column(String(255), nullable=True, index=True)

    status = Column(String(20), nullable=False, default="pending")  # pending|running|completed|failed
    metrics = Column(JSONB, default=list)
    params = Column(JSONB, default=dict)
    summary = Column(JSONB, default=dict)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class RagasRegressionItem(Base):
    """回归运行的单条结果（对应一个 case）。"""

    __tablename__ = "ragas_regression_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ragas_regression_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    case_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    question = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    retrieved_contexts = Column(JSONB, default=list)  # list[str]
    citations = Column(JSONB, default=list)
    scores = Column(JSONB, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
