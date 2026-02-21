import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from app.core.config import settings
from app.core.database import Base


def _default_tenant() -> uuid.UUID:
    """
    Provide a UUID default for tenant_id fields.

    NOTE: `settings.DEFAULT_TENANT_ID` is stored as a string, but SQLAlchemy's
    PG UUID columns expect an actual uuid.UUID object when `as_uuid=True`.
    """
    raw = str(getattr(settings, "DEFAULT_TENANT_ID", "") or "").strip()
    try:
        return uuid.UUID(raw)
    except Exception:
        return uuid.UUID("00000000-0000-0000-0000-000000000000")


class KgEntity(Base):
    """Entity table used by KG pipelines."""

    __tablename__ = "kg_entities"

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

    associations = relationship("KgEventEntity", back_populates="entity", cascade="all, delete-orphan")


class KgSourceEvent(Base):
    """Event table extracted from document chunks."""

    __tablename__ = "kg_source_events"

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

    associations = relationship("KgEventEntity", back_populates="event", cascade="all, delete-orphan")


class KgEventEntity(Base):
    """Join table: event to entity with weight."""

    __tablename__ = "kg_event_entities"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("kg_source_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("kg_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    weight = Column(Numeric(5, 2), nullable=False, default=1.00)
    role = Column(String(100), nullable=True)
    extra_data = Column(JSON, nullable=True)

    event = relationship("KgSourceEvent", back_populates="associations")
    entity = relationship("KgEntity", back_populates="associations")


class KgRelation(Base):
    """
    Entity -> Entity edges with provenance.

    This powers "triples" extraction (subject/predicate/object) and SkillNet-like
    relations for process knowledge (skills/tags/packages).
    """

    __tablename__ = "kg_relations"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(PGUUID(as_uuid=True), nullable=False, default=_default_tenant, index=True)

    # Provenance scope/evidence.
    document_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)
    chunk_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)
    event_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("kg_source_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    subject_entity_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("kg_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    predicate = Column(String(200), nullable=False, index=True)
    predicate_raw = Column(String(200), nullable=True)
    object_entity_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("kg_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    confidence = Column(Numeric(5, 2), nullable=False, default=0.50)

    qualifiers = Column(JSON, nullable=True)
    references = Column(JSON, nullable=True)
    extra_data = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    subject = relationship("KgEntity", foreign_keys=[subject_entity_id])
    object = relationship("KgEntity", foreign_keys=[object_entity_id])
    event = relationship("KgSourceEvent", foreign_keys=[event_id])
