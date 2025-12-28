"""
Document related database models with multi-tenant support.
"""
import uuid
from sqlalchemy import Column, String, Integer, BigInteger, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Document(Base):
    """Document table"""
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)  # Reserved for future user system

    # Basic file info
    filename = Column(String(500), nullable=False)
    file_type = Column(String(10), nullable=False)  # pdf, md, txt
    file_size = Column(BigInteger, nullable=False)
    file_path = Column(String(1000), nullable=False)

    # Processing status
    status = Column(String(20), nullable=False, default='pending')  # pending | processing | completed | failed
    processing_progress = Column(Integer, default=0)  # 0-100
    current_stage = Column(String(50), nullable=True)  # parsing | chunking | embedding | completed
    error_message = Column(Text, nullable=True)

    # Stats
    chunk_count = Column(Integer, default=0)
    total_characters = Column(Integer, default=0)

    # Metadata
    doc_metadata = Column("metadata", JSONB, default=dict)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)

    # Relations
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    """Document chunk table"""
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey('documents.id', ondelete='CASCADE'), nullable=False)

    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)

    # Position info
    page_number = Column(Integer, nullable=True)
    start_char = Column(Integer, nullable=True)
    end_char = Column(Integer, nullable=True)

    # Metadata
    doc_metadata = Column("metadata", JSONB, default=dict)

    # Vector ID
    vector_id = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relations
    document = relationship("Document", back_populates="chunks")
