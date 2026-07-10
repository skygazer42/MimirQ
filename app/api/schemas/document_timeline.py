"""
Document timeline schemas.

The timeline is a user-facing aggregation of audit logs + a few synthetic document state events.
Keep it PII-minimal by default.
"""


from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DocumentTimelineItem(BaseModel):
    id: str
    action: str
    created_at: datetime

    source: Literal["audit", "synthetic"] = "audit"

    actor_id: str | None = None
    request_id: str | None = None

    stage: str | None = None
    status: str | None = None
    progress: int | None = None

    details: dict[str, Any] = Field(default_factory=dict)


class DocumentTimelineResponse(BaseModel):
    total: int = 0
    items: list[DocumentTimelineItem] = Field(default_factory=list)

