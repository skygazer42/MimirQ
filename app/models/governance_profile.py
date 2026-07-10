"""
Governance Profile database model.

Profiles are declarative "governance scripts" that store:
- pipeline option patches (DocumentPipelineOptions-like)
- optional regex cleanup rules

They must never contain executable code.
"""


import uuid

from sqlalchemy import Boolean, Column, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base


class GovernanceProfile(Base):
    __tablename__ = "governance_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Optional stable key/slug for referencing in scripts or automation.
    key = Column(String(100), nullable=True, index=True)

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # Custom profiles only; built-ins live in code.
    is_system = Column(Boolean, default=False)

    # GovernanceProfilePayload (version/input_formats/pipeline_patch/regex_rules)
    payload = Column(JSONB, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_governance_profiles_tenant_name", "tenant_id", "name"),
        Index("ix_governance_profiles_tenant_key", "tenant_id", "key"),
    )

