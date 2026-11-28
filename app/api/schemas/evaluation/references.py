"""Evidence audit schemas (PII-safe)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EvidenceDriftSliceBucketOut(BaseModel):
    total: int = 0
    ok: int = 0
    drift: int = 0
    drift_rate: float = 0.0
    reasons: dict[str, int] = Field(default_factory=dict)


class EvidenceReferenceDriftDetailOut(BaseModel):
    suite_id: UUID
    item_id: UUID
    item_status: str
    dataset_id: UUID
    document_id: UUID
    chunk_id: UUID
    reason: str
    expected: dict[str, Any] = Field(default_factory=dict)
    observed: dict[str, Any] = Field(default_factory=dict)
    # Stable slice keys for drilldowns.
    slice: dict[str, str] = Field(default_factory=dict)


class EvidenceReferenceDriftAuditOut(BaseModel):
    generated_at: datetime
    dataset_id: UUID
    suite_id: UUID | None = None

    total_items: int = 0
    total_references: int = 0
    ok_references: int = 0
    drift_references: int = 0
    drift_rate: float = 0.0

    reasons: dict[str, int] = Field(default_factory=dict)
    # slices[slice_name][bucket_key] = bucket metrics
    slices: dict[str, dict[str, EvidenceDriftSliceBucketOut]] = Field(default_factory=dict)

    # Optional PII-safe details (bounded).
    details_truncated: bool = False
    drifted_references: list[EvidenceReferenceDriftDetailOut] = Field(default_factory=list)


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
