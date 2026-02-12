"""Evidence audit schemas (PII-safe)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EvidenceDriftSliceBucketOut(BaseModel):
    total: int = 0
    ok: int = 0
    drift: int = 0
    drift_rate: float = 0.0
    reasons: Dict[str, int] = Field(default_factory=dict)


class EvidenceReferenceDriftDetailOut(BaseModel):
    suite_id: UUID
    item_id: UUID
    item_status: str
    dataset_id: UUID
    document_id: UUID
    chunk_id: UUID
    reason: str
    expected: Dict[str, Any] = Field(default_factory=dict)
    observed: Dict[str, Any] = Field(default_factory=dict)
    # Stable slice keys for drilldowns.
    slice: Dict[str, str] = Field(default_factory=dict)


class EvidenceReferenceDriftAuditOut(BaseModel):
    generated_at: datetime
    dataset_id: UUID
    suite_id: Optional[UUID] = None

    total_items: int = 0
    total_references: int = 0
    ok_references: int = 0
    drift_references: int = 0
    drift_rate: float = 0.0

    reasons: Dict[str, int] = Field(default_factory=dict)
    # slices[slice_name][bucket_key] = bucket metrics
    slices: Dict[str, Dict[str, EvidenceDriftSliceBucketOut]] = Field(default_factory=dict)

    # Optional PII-safe details (bounded).
    details_truncated: bool = False
    drifted_references: List[EvidenceReferenceDriftDetailOut] = Field(default_factory=list)

