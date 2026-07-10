"""
Dataset health dashboard schemas.

This is a thin aggregation layer over existing dataset profile/precheck/ingestion signals.
"""


from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.schemas.dataset_profile import DatasetProfileSummary


class DatasetHealthIngestionSummary(BaseModel):
    total_documents: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)

    pending: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    quarantined: int = 0
    cancelled: int = 0


class DatasetHealthResponse(BaseModel):
    dataset_id: UUID
    generated_at: datetime
    profile: DatasetProfileSummary
    ingestion: DatasetHealthIngestionSummary

