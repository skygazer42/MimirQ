"""
Conversation and message data models (multi-tenant isolation support)

Defines conversation and message table structures.
"""
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Conversation(Base):
    """Conversation table"""
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_tenant_owner_account_id", "tenant_id", "owner_account_id"),
    )

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
    document_ids = Column(ARRAY(UUID(as_uuid=True)), default=[])

    message_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relations
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    """Message table"""
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)

    role = Column(String(20), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)

    # citations (assistant messages)
    citations = Column(JSONB, default=[])

    # Token stats
    token_count = Column(Integer, nullable=True)
    # Optional: store run metadata (retrieval mode/backend, timings, route, etc.)
    message_metadata = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relations
    conversation = relationship("Conversation", back_populates="messages")
