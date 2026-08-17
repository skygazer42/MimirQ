"""
Document-related database models (multi-tenant support)

Defines document and document chunk table structures.
"""

import uuid

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base

DELETE_ORPHAN_CASCADE = "all, delete-orphan"


class Document(Base):
    """Document table"""

    __tablename__ = "documents"
    __table_args__ = (
        # Enforce that dataset_id, when present, references a dataset within the same tenant.
        ForeignKeyConstraint(
            ["tenant_id", "dataset_id"],
            ["datasets.tenant_id", "datasets.id"],
            name="fk_documents_tenant_dataset",
        ),
        Index(
            "uq_documents_tenant_dataset_dedup_key_active",
            "tenant_id",
            "dataset_id",
            "dedup_key",
            unique=True,
            postgresql_where=text("archived_at IS NULL AND dataset_id IS NOT NULL AND dedup_key IS NOT NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)  # Reserved for future user system

    # Basic file info
    filename = Column(String(500), nullable=False)
    file_type = Column(String(10), nullable=False)  # pdf, md, txt
    file_size = Column(BigInteger, nullable=False)
    file_path = Column(String(1000), nullable=False)

    # Document-level access control (enterprise-style "security trimming").
    # - owner_id: account/user id that "owns" the document (typically uploader/connector requester).
    # - access_mode:
    #   - NULL / "inherit": use dataset permissions only (default)
    #   - "only_me": owner only
    #   - "partial_members": owner + allowlist in `document_permissions`
    #   - "all_team_members": allow all tenant members (still bounded by dataset permission)
    owner_id = Column(String(255), nullable=True)
    access_mode = Column(String(50), nullable=True)

    # Content lifecycle metadata (ops/governance workflows).
    #
    # Note: this is separate from ACL `owner_id` above.
    lifecycle_owner = Column(String(255), nullable=True)
    review_due_at = Column(DateTime(timezone=True), nullable=True)
    authority_level = Column(Integer, nullable=True)
    supersedes_document_id = Column(UUID(as_uuid=True), nullable=True)

    # Publication/approval workflow state (governance).
    # Keep separate from processing `status` below.
    publication_status = Column(
        String(20), nullable=False, default="published", index=True
    )  # draft|published|deprecated

    # Processing status
    status = Column(
        String(20), nullable=False, default="pending"
    )  # pending|processing|completed|failed|quarantined|cancelled|deleting
    processing_progress = Column(Integer, default=0)  # 0-100
    current_stage = Column(String(50), nullable=True)  # parsing | chunking | embedding | vector_write | completed
    failed_stage = Column(String(50), nullable=True)
    error_code = Column(String(100), nullable=True)
    processing_attempts = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    # Stats
    chunk_count = Column(Integer, default=0)
    total_characters = Column(Integer, default=0)

    # Metadata
    doc_metadata = Column("metadata", JSONB, default=dict)
    dedup_key = Column(String(255), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    disabled_at = Column(DateTime(timezone=True), nullable=True)

    # Relations
    chunks = relationship("DocumentChunk", back_populates="document", cascade=DELETE_ORPHAN_CASCADE)
    parsed_content = relationship(
        "DocumentParsedContent",
        back_populates="document",
        cascade=DELETE_ORPHAN_CASCADE,
        uselist=False,
    )
    permissions = relationship("DocumentPermission", back_populates="document", cascade=DELETE_ORPHAN_CASCADE)
    index_channels = relationship(
        "DocumentIndexChannel",
        cascade=DELETE_ORPHAN_CASCADE,
    )


class DocumentPermission(Base):
    """Document partial member permissions (document-level ACL allowlist)."""

    __tablename__ = "document_permissions"
    __table_args__ = (UniqueConstraint("document_id", "account_id", name="uq_document_permission_member"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="permissions")


class DocumentChunk(Base):
    """Document chunk table"""

    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)

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
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    disabled_at = Column(DateTime(timezone=True), nullable=True)

    # Relations
    document = relationship("Document", back_populates="chunks")


class DocumentParsedContent(Base):
    """
    Persisted parsed markdown content for a document.

    This keeps large markdown out of JSONB metadata while still allowing
    enterprise-grade persistence across restarts.
    """

    __tablename__ = "document_parsed_contents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    document_id = Column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    markdown_content = Column(Text, nullable=False, default="")
    original_markdown_content = Column(Text, nullable=False, default="")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    document = relationship("Document", back_populates="parsed_content")
