import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from app.core.config import settings
from app.core.database import Base

KG_ENTITIES_ID_FK = "kg_entities.id"


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

    # Pipeline/version scope (see docs/guides/document_versions.md).
    # Nullable for legacy rows; new extraction should populate it.
    pipeline_hash = Column(String(200), nullable=True, index=True)

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
        ForeignKey(KG_ENTITIES_ID_FK, ondelete="CASCADE"),
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

    # Pipeline/version scope (nullable for legacy rows).
    pipeline_hash = Column(String(200), nullable=True, index=True)

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
        ForeignKey(KG_ENTITIES_ID_FK, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    predicate = Column(String(200), nullable=False, index=True)
    predicate_raw = Column(String(200), nullable=True)
    object_entity_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(KG_ENTITIES_ID_FK, ondelete="CASCADE"),
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


class KgEntityAlias(Base):
    """
    Human-governed aliases for KG entities (entity resolution).

    Notes:
    - This is used to reduce entity fragmentation and to support alias-aware KG search.
    - Aliases are tenant-scoped and point at a canonical KgEntity.
    """

    __tablename__ = "kg_entity_aliases"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(PGUUID(as_uuid=True), nullable=False, default=_default_tenant, index=True)

    canonical_entity_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(KG_ENTITIES_ID_FK, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    alias = Column(String(500), nullable=False)
    normalized_alias = Column(String(500), nullable=False, index=True)

    created_by = Column(String(255), nullable=True, index=True)
    extra_data = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    canonical = relationship("KgEntity", foreign_keys=[canonical_entity_id])


class KgEntityResolutionAction(Base):
    """Append-only log of entity resolution actions (merge/split/undo)."""

    __tablename__ = "kg_entity_resolution_actions"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(PGUUID(as_uuid=True), nullable=False, default=_default_tenant, index=True)

    actor_id = Column(String(255), nullable=True, index=True)
    action_type = Column(String(32), nullable=False, index=True)  # merge|split|undo
    status = Column(String(32), nullable=False, default="applied", index=True)  # applied|reverted

    payload = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    reversed_at = Column(DateTime, nullable=True)
    reversed_by = Column(String(255), nullable=True)


class KgEntityRedirect(Base):
    """
    Map deprecated entity ids to canonical entities.

    This enables stable URLs and safe resolution after merges.
    """

    __tablename__ = "kg_entity_redirects"

    from_entity_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(KG_ENTITIES_ID_FK, ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id = Column(PGUUID(as_uuid=True), nullable=False, default=_default_tenant, index=True)

    to_entity_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(KG_ENTITIES_ID_FK, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("kg_entity_resolution_actions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_by = Column(String(255), nullable=True)
    extra_data = Column(JSONB, nullable=True)

    source = relationship("KgEntity", foreign_keys=[from_entity_id])
    target = relationship("KgEntity", foreign_keys=[to_entity_id])
    action = relationship("KgEntityResolutionAction", foreign_keys=[action_id])


class KgPredicateOntology(Base):
    """
    Predicate allowlist + metadata (lightweight ontology governance).

    Extraction and KG relation expansion can consult this table to keep predicates
    compact and consistent (avoid schema drift).
    """

    __tablename__ = "kg_predicate_ontology"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(PGUUID(as_uuid=True), nullable=False, default=_default_tenant, index=True)

    predicate = Column(String(200), nullable=False, index=True)
    display_name = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=True, index=True)

    extra_data = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True)
