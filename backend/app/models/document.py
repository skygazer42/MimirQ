"""
文档相关数据库模型
"""
from sqlalchemy import Column, String, Integer, BigInteger, DateTime, Text, ARRAY, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.database import Base


class Document(Base):
    """文档表"""
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=True)  # 暂时可为空，后续添加用户系统

    # 文件基本信息
    filename = Column(String(500), nullable=False)
    file_type = Column(String(10), nullable=False)  # pdf, md, txt
    file_size = Column(BigInteger, nullable=False)
    file_path = Column(String(1000), nullable=False)

    # 处理状态
    status = Column(String(20), nullable=False, default='pending')  # pending | processing | completed | failed
    processing_progress = Column(Integer, default=0)  # 0-100
    current_stage = Column(String(50), nullable=True)  # parsing | chunking | embedding | completed
    error_message = Column(Text, nullable=True)

    # 统计信息
    chunk_count = Column(Integer, default=0)
    total_characters = Column(Integer, default=0)

    # 元数据
    metadata = Column(JSONB, default={})

    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)

    # 关系
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    """文档块表"""
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey('documents.id', ondelete='CASCADE'), nullable=False)

    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)

    # 位置信息
    page_number = Column(Integer, nullable=True)
    start_char = Column(Integer, nullable=True)
    end_char = Column(Integer, nullable=True)

    # 元数据
    metadata = Column(JSONB, default={})

    # ChromaDB 向量 ID
    vector_id = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    document = relationship("Document", back_populates="chunks")
