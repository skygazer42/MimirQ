import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, ForeignKey, String, Text, DateTime, JSON, Numeric
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.config import settings


def _default_tenant() -> uuid.UUID:
    return settings.DEFAULT_TENANT_ID


class SagEntity(Base):
    """Entity table used by KG pipelines (legacy: SAG)."""

    __tablename__ = "sag_entities"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(PGUUID(as_uuid=True), nullable=False, default=_default_tenant, index=True)

    name = Column(String(500), nullable=False)
    type = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=True)
    normalized_name = Column(String(500), nullable=False, index=True)
    vector = Column(JSON, nullable=True)  # list[float]
    extra_data = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    associations = relationship("SagEventEntity", back_populates="entity", cascade="all, delete-orphan")


class SagSourceEvent(Base):
    """Event table extracted from document chunks."""

    __tablename__ = "sag_source_events"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(PGUUID(as_uuid=True), nullable=False, default=_default_tenant, index=True)

    document_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)
    chunk_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)

    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    content_vector = Column(JSON, nullable=True)  # list[float]

    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    references = Column(JSON, nullable=True)
    extra_data = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    associations = relationship("SagEventEntity", back_populates="event", cascade="all, delete-orphan")


class SagEventEntity(Base):
    """Join table: event to entity with weight."""

    __tablename__ = "sag_event_entities"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(PGUUID(as_uuid=True), ForeignKey("sag_source_events.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id = Column(PGUUID(as_uuid=True), ForeignKey("sag_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    weight = Column(Numeric(5, 2), nullable=False, default=1.00)
    role = Column(String(100), nullable=True)
    extra_data = Column(JSON, nullable=True)

    event = relationship("SagSourceEvent", back_populates="associations")
    entity = relationship("SagEntity", back_populates="associations")
