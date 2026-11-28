"""Tenant-owned enterprise ontology workspaces and published definitions."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB

from app.infrastructure.database.connection import Base

_definition_json = JSON().with_variant(JSONB(), "postgresql")


class EnterpriseOntology(Base):
    __tablename__ = "enterprise_ontologies"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_enterprise_ontology_tenant_code"),)

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(64), nullable=False)
    draft = Column(_definition_json, nullable=False)
    draft_revision = Column(Integer, nullable=False, default=1)
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))


class EnterpriseOntologyVersion(Base):
    __tablename__ = "enterprise_ontology_versions"
    __table_args__ = (
        UniqueConstraint("ontology_id", "number", name="uq_enterprise_ontology_version_number"),
        UniqueConstraint("ontology_id", "draft_revision", name="uq_enterprise_ontology_version_draft"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    ontology_id = Column(Uuid(as_uuid=True), ForeignKey("enterprise_ontologies.id", ondelete="CASCADE"), nullable=False)
    number = Column(Integer, nullable=False)
    draft_revision = Column(Integer, nullable=False)
    definition = Column(_definition_json, nullable=False)
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))


class EnterpriseOntologyDataset(Base):
    __tablename__ = "enterprise_ontology_datasets"

    dataset_id = Column(Uuid(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    tenant_id = Column(Uuid(as_uuid=True), nullable=False)
    version_id = Column(
        Uuid(as_uuid=True), ForeignKey("enterprise_ontology_versions.id", ondelete="CASCADE"), nullable=False
    )
    updated_by = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class EnterpriseOntologyDocument(Base):
    __tablename__ = "enterprise_ontology_documents"

    version_id = Column(
        Uuid(as_uuid=True), ForeignKey("enterprise_ontology_versions.id", ondelete="CASCADE"), primary_key=True
    )
    document_id = Column(Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    pipeline_hash = Column(String(64), primary_key=True)
    tenant_id = Column(Uuid(as_uuid=True), nullable=False)
    dataset_id = Column(Uuid(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    chunks = Column(_definition_json, nullable=False)


class EnterpriseOntologyDraftDocument(Base):
    __tablename__ = "enterprise_ontology_draft_documents"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(Uuid(as_uuid=True), nullable=False)
    owner_id = Column(String(255), nullable=False)
    version_id = Column(
        Uuid(as_uuid=True), ForeignKey("enterprise_ontology_versions.id", ondelete="CASCADE"), nullable=False
    )
    request = Column(_definition_json, nullable=False)
    answer = Column(_definition_json, nullable=False)


class EnterpriseOntologyActionRequest(Base):
    __tablename__ = "enterprise_ontology_action_requests"

    tenant_id = Column(Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    request_id = Column(Uuid(as_uuid=True), primary_key=True)
    version_id = Column(
        Uuid(as_uuid=True), ForeignKey("enterprise_ontology_versions.id", ondelete="CASCADE"), nullable=False
    )
    action_id = Column(String(64), nullable=False)
    owner_id = Column(String(255), nullable=False)
    inputs = Column(_definition_json, nullable=False)
    state = Column(String(32), nullable=False)
    dispatch_started_at = Column(DateTime(timezone=True))
    approved_by = Column(String(255))
    receipt = Column(_definition_json)
    workflow_request_id = Column(Uuid(as_uuid=True))


class EnterpriseOntologyWorkflowRequest(Base):
    __tablename__ = "enterprise_ontology_workflow_requests"

    tenant_id = Column(Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    request_id = Column(Uuid(as_uuid=True), primary_key=True)
    version_id = Column(
        Uuid(as_uuid=True), ForeignKey("enterprise_ontology_versions.id", ondelete="CASCADE"), nullable=False
    )
    workflow_id = Column(String(64), nullable=False)
    owner_id = Column(String(255), nullable=False)
    steps = Column(_definition_json, nullable=False)
    canceled_at = Column(DateTime(timezone=True))
