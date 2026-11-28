"""Dataset pointers to immutable ontology versions."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.datasets.records import Dataset
from app.models.knowledge_graph.enterprise_ontology import (
    EnterpriseOntology,
    EnterpriseOntologyDataset,
    EnterpriseOntologyVersion,
)
from app.rag.kg.enterprise_ontology.documents import require_dataset_evidence


def active_version_id(db: Session, tenant_id: UUID, dataset_id: UUID) -> UUID | None:
    return db.scalar(
        select(EnterpriseOntologyDataset.version_id).where(
            EnterpriseOntologyDataset.tenant_id == tenant_id, EnterpriseOntologyDataset.dataset_id == dataset_id
        )
    )


def published_version(db: Session, tenant_id: UUID, version_id: UUID) -> EnterpriseOntologyVersion | None:
    return db.scalar(
        select(EnterpriseOntologyVersion)
        .join(EnterpriseOntology, EnterpriseOntology.id == EnterpriseOntologyVersion.ontology_id)
        .where(EnterpriseOntology.tenant_id == tenant_id, EnterpriseOntologyVersion.id == version_id)
    )


def switch_dataset_version(
    db: Session,
    dataset: Dataset,
    workspace: EnterpriseOntology,
    version: EnterpriseOntologyVersion,
    *,
    account_id: str,
) -> EnterpriseOntologyDataset:
    if dataset.tenant_id != workspace.tenant_id or version.ontology_id != workspace.id:
        raise HTTPException(status_code=409, detail="Ontology version is outside this dataset's tenant")
    locked = db.scalar(
        select(Dataset.id).where(Dataset.id == dataset.id, Dataset.tenant_id == workspace.tenant_id).with_for_update()
    )
    if locked is None:
        raise HTTPException(status_code=409, detail="Dataset is unavailable")
    require_dataset_evidence(
        db, tenant_id=dataset.tenant_id, dataset_id=dataset.id, version_id=version.id, account_id=account_id
    )
    row = db.get(EnterpriseOntologyDataset, dataset.id, populate_existing=True)
    if row is None:
        row = EnterpriseOntologyDataset(dataset_id=dataset.id, tenant_id=dataset.tenant_id)
        db.add(row)
    row.version_id = version.id
    row.updated_by = account_id
    row.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return row
