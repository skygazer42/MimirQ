"""
Governance Profile (data governance "script") schemas.

Important:
- A "profile" is a declarative configuration (JSON) that defines pipeline option patches
  and optional regex cleanup rules. It must never contain executable code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RegexRuleModel(BaseModel):
    pattern: str = Field(..., min_length=1, max_length=2000)
    repl: str = Field(default="", max_length=2000)
    flags: int = Field(default=0, ge=0, le=10_000)


class GovernanceProfilePayload(BaseModel):
    """
    Declarative governance script payload.

    - pipeline_patch: a partial DocumentPipelineOptions object to be merged by the caller.
    - regex_rules: additional cleanup rules (applied after default rules by default).
    """

    version: str = Field(default="1", description="Payload schema version")
    input_formats: List[Literal["markdown", "html"]] = Field(
        default_factory=lambda: ["markdown"],
        description="Recommended input format(s) for preview tools",
    )
    pipeline_patch: Dict[str, Any] = Field(default_factory=dict)
    regex_rules: List[RegexRuleModel] = Field(default_factory=list)


class GovernanceProfileSummary(BaseModel):
    id: Optional[UUID] = None
    key: str
    name: str
    description: Optional[str] = None
    is_system: bool = False


class GovernanceProfileListResponse(BaseModel):
    total: int
    items: List[GovernanceProfileSummary] = Field(default_factory=list)


class GovernanceProfileOut(BaseModel):
    id: Optional[UUID] = None
    key: str
    name: str
    description: Optional[str] = None
    is_system: bool = False
    payload: GovernanceProfilePayload
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class GovernanceProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    key: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Optional stable key/slug for the profile (tenant-scoped).",
    )
    payload: GovernanceProfilePayload


class GovernanceProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    payload: Optional[GovernanceProfilePayload] = None


class GovernanceProfileImportResponse(BaseModel):
    created: int = 0
    updated: int = 0
    items: List[GovernanceProfileSummary] = Field(default_factory=list)
