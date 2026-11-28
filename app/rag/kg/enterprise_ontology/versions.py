"""Revision compare-and-swap and immutable ontology release snapshots."""

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.knowledge_graph.enterprise_ontology import EnterpriseOntology, EnterpriseOntologyVersion
from app.rag.kg.enterprise_ontology.definition import OntologyDefinition


class StaleDraftError(ValueError):
    """The editor's draft revision no longer matches the stored draft."""


def get_ontology(db: Session, tenant_id: UUID, ontology_id: UUID) -> EnterpriseOntology | None:
    return db.scalar(
        select(EnterpriseOntology).where(
            EnterpriseOntology.tenant_id == tenant_id, EnterpriseOntology.id == ontology_id
        )
    )


def list_ontologies(db: Session, tenant_id: UUID) -> list[EnterpriseOntology]:
    return list(
        db.scalars(
            select(EnterpriseOntology)
            .where(EnterpriseOntology.tenant_id == tenant_id)
            .order_by(EnterpriseOntology.code)
        )
    )


def create_ontology(
    db: Session, tenant_id: UUID, definition: OntologyDefinition, *, account_id: str
) -> EnterpriseOntology:
    workspace = EnterpriseOntology(
        tenant_id=tenant_id,
        code=definition.ontology,
        draft=definition.model_dump(mode="json", by_alias=True),
        created_by=account_id,
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


def update_draft(
    db: Session, workspace: EnterpriseOntology, definition: OntologyDefinition, *, expected_revision: int
) -> EnterpriseOntology:
    if definition.ontology != workspace.code:
        raise ValueError("The ontology code is the identity of the workspace")
    revision = db.scalar(
        update(EnterpriseOntology)
        .where(
            EnterpriseOntology.id == workspace.id,
            EnterpriseOntology.tenant_id == workspace.tenant_id,
            EnterpriseOntology.draft_revision == expected_revision,
        )
        .values(draft=definition.model_dump(mode="json", by_alias=True), draft_revision=expected_revision + 1)
        .returning(EnterpriseOntology.draft_revision)
    )
    if revision is None:
        raise StaleDraftError("Ontology draft changed")
    db.commit()
    db.refresh(workspace)
    return workspace


def publish_version(
    db: Session,
    workspace: EnterpriseOntology,
    *,
    expected_revision: int,
    account_id: str,
    frozen_definition: OntologyDefinition | None = None,
) -> EnterpriseOntologyVersion:
    locked = db.scalar(
        select(EnterpriseOntology)
        .where(EnterpriseOntology.id == workspace.id, EnterpriseOntology.tenant_id == workspace.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or locked.draft_revision != expected_revision:
        raise StaleDraftError("Ontology draft changed")
    previous = db.scalar(
        select(EnterpriseOntologyVersion).where(
            EnterpriseOntologyVersion.ontology_id == locked.id,
            EnterpriseOntologyVersion.draft_revision == expected_revision,
        )
    )
    if previous is not None:
        db.commit()
        return previous
    definition = frozen_definition if frozen_definition is not None else OntologyDefinition.model_validate(locked.draft)
    definition.validate_rules_for_publication()
    highest = db.scalar(
        select(func.max(EnterpriseOntologyVersion.number)).where(EnterpriseOntologyVersion.ontology_id == locked.id)
    )
    row = EnterpriseOntologyVersion(
        ontology_id=locked.id,
        number=1 if highest is None else highest + 1,
        draft_revision=expected_revision,
        definition=definition.model_dump(mode="json", by_alias=True),
        created_by=account_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_versions(db: Session, workspace: EnterpriseOntology) -> list[EnterpriseOntologyVersion]:
    return list(
        db.scalars(
            select(EnterpriseOntologyVersion)
            .where(EnterpriseOntologyVersion.ontology_id == workspace.id)
            .order_by(EnterpriseOntologyVersion.number.desc())
        )
    )


def get_version(db: Session, workspace: EnterpriseOntology, version_id: UUID) -> EnterpriseOntologyVersion | None:
    return db.scalar(
        select(EnterpriseOntologyVersion).where(
            EnterpriseOntologyVersion.ontology_id == workspace.id, EnterpriseOntologyVersion.id == version_id
        )
    )
