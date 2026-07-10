"""
Conversation summaries (persistent summary memory).

Used to keep long conversations usable without stuffing the entire history into prompts.
"""


import uuid

from sqlalchemy import Column, DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "conversation_id", name="uq_conversation_summary_once"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Summary text (system-style). Keep compact.
    summary = Column(Text, nullable=False, default="")

    # Track the message_count that this summary was generated from (best-effort).
    last_message_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

