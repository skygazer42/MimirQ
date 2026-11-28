"""SQLAlchemy conversations chat entities."""

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.infrastructure.database.connection import Base


class Conversation(Base):
    """Conversation table"""

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_tenant_owner_account_id", "tenant_id", "owner_account_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    owner_account_id = Column(String(255), nullable=True)
    # Optional dataset scope for the conversation. When NULL and document_ids is empty,
    # the conversation uses "open scope" (retrieve across all accessible docs in tenant).
    dataset_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    title = Column(String(500), nullable=True)
    title_source = Column(String(16), nullable=False, default="manual", server_default="manual")

    # knowledge scope (document ids)
    document_ids = Column(ARRAY(UUID(as_uuid=True)), default=list)

    message_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relations
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    """Message table"""

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_tenant_conversation_created_at", "tenant_id", "conversation_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)

    role = Column(String(20), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)

    # citations (assistant messages)
    citations = Column(JSONB, default=list)

    # Token stats
    token_count = Column(Integer, nullable=True)
    # Optional: store run metadata (retrieval mode/backend, timings, route, etc.)
    message_metadata = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relations
    conversation = relationship("Conversation", back_populates="messages")


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"
    __table_args__ = (UniqueConstraint("tenant_id", "conversation_id", name="uq_conversation_summary_once"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Summary text (system-style). Keep compact.
    summary = Column(Text, nullable=False, default="")

    # Track the message_count that this summary was generated from (best-effort).
    last_message_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


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
