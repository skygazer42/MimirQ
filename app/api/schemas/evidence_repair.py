"""Evidence repair schemas (PII-safe)."""


from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EvidenceReferenceRepairRequest(BaseModel):
    """
    Repair drifted evidence pointers (best-effort).

    Safety:
    - `apply=false` is a dry-run and will not modify any evidence items.
    - `allow_approved=false` prevents mutating approved items by default.
    """

    apply: bool = False
    allow_approved: bool = False
    include_archived_items: bool = False

    # Guardrails.
    max_items: int = Field(default=5000, ge=1, le=20_000)
    max_refs_per_item: int = Field(default=50, ge=1, le=500)
    max_changes: int = Field(default=500, ge=0, le=5000)


class EvidenceReferenceRepairChangeOut(BaseModel):
    suite_id: UUID
    item_id: UUID
    item_status: str
    document_id: UUID
    chunk_id_before: UUID
    chunk_id_after: UUID | None = None
    reason: str
    repaired: bool = False
    method: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class EvidenceReferenceRepairResponse(BaseModel):
    suite_id: UUID
    dataset_id: UUID
    applied: bool = False

    scanned_items: int = 0
    scanned_references: int = 0
    drifted_references: int = 0
    repaired_references: int = 0
    skipped_approved_items: int = 0
    skipped_archived_items: int = 0

    changes_truncated: bool = False
    changes: list[EvidenceReferenceRepairChangeOut] = Field(default_factory=list)

