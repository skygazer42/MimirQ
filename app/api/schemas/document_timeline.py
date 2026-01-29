"""
Document timeline schemas.

The timeline is a user-facing aggregation of audit logs + a few synthetic document state events.
Keep it PII-minimal by default.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class DocumentTimelineItem(BaseModel):
    id: str
    action: str
    created_at: datetime

    source: Literal["audit", "synthetic"] = "audit"

    actor_id: Optional[str] = None
    request_id: Optional[str] = None

    stage: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[int] = None

    details: Dict[str, Any] = Field(default_factory=dict)


class DocumentTimelineResponse(BaseModel):
    total: int = 0
    items: List[DocumentTimelineItem] = Field(default_factory=list)

