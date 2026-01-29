"""
User feedback models (evaluation loop).

Records ratings, reasons, and expected answers for assistant messages to support
quality analysis, regression sets, A/B comparisons, and model iteration.
"""

 
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base


class MessageFeedback(Base):
    """Feedback record for an assistant message (tenant isolated)."""

    __tablename__ = "message_feedback"
    __table_args__ = (
        # Keep one feedback per user/message (duplicate submits update).
        UniqueConstraint("tenant_id", "message_id", "account_id", name="uq_message_feedback_once"),
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
    extra = Column(JSONB, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
