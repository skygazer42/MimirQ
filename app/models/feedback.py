"""
User feedback models (evaluation loop).

Records ratings, reasons, and expected answers for assistant messages to support
quality analysis, regression sets, A/B comparisons, and model iteration.
"""


import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base


class MessageFeedback(Base):
    """Feedback record for an assistant message (tenant isolated)."""

    __tablename__ = "message_feedback"
    __table_args__ = (
        # Keep one feedback per user/message (duplicate submits update).
        UniqueConstraint("tenant_id", "message_id", "account_id", name="uq_message_feedback_once"),
        CheckConstraint(
            "category IS NULL OR category IN ('retrieval_miss', 'wrong_answer', 'out_of_scope', 'other')",
            name="ck_message_feedback_category",
        ),
        CheckConstraint(
            "category_source IS NULL OR category_source IN ('user', 'llm_auto', 'reviewer')",
            name="ck_message_feedback_category_source",
        ),
        Index("ix_message_feedback_tenant_category", "tenant_id", "category"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    account_id = Column(String(255), nullable=False, index=True)

    # Rating: 1-5 recommended (higher is better).
    rating = Column(Integer, nullable=False)
    reason = Column(Text, nullable=True)
    tags = Column(JSONB, default=list)
    expected_answer = Column(Text, nullable=True)
    category = Column(String(32), nullable=True)
    category_source = Column(String(32), nullable=True)
    query_hash = Column(String(64), nullable=True)
    retrieval_trace_ref = Column(String(255), nullable=True)
    profile = Column(String(64), nullable=True)
    judge_score_ref = Column(String(255), nullable=True)
    extra = Column(JSONB, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
