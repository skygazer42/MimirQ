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

