"""
Governance Profile (data governance "script") schemas.

Important:
- A "profile" is a declarative configuration (JSON) that defines pipeline option patches
  and optional regex cleanup rules. It must never contain executable code.
"""


from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RegexRuleModel(BaseModel):
    pattern: str = Field(..., min_length=1, max_length=2000)
    repl: str = Field(default="", max_length=2000)
    flags: int = Field(default=0, ge=0, le=10_000)


class GovernanceProcessingScript(BaseModel):
    """
    Non-executable processing script attachment.

    Scripts are persisted with the profile for review/versioning only. The
    ingestion pipeline must not execute them unless a separate sandboxed runtime
    explicitly supports that in the future.
    """

    name: str = Field(..., min_length=1, max_length=160)
    language: Literal["javascript", "typescript", "python", "rust"]
    stage: Literal["post_parse", "post_governance"] = "post_governance"
    content: str = Field(..., min_length=1, max_length=200_000)
    enabled: bool = False
    description: str | None = Field(default=None, max_length=500)
    created_at: datetime | None = None


class GovernanceProfilePayload(BaseModel):
    """
    Declarative governance script payload.

    - pipeline_patch: a partial DocumentPipelineOptions object to be merged by the caller.
    - regex_rules: additional cleanup rules (applied after default rules by default).
    - processing_scripts: non-executable script attachments for review/audit.
    """

    version: str = Field(default="1", description="Payload schema version")
    extends: str | None = Field(
        default=None,
        max_length=120,
        description="Optional parent profile ref (builtin:<key> | UUID | tenant-scoped key).",
    )
    input_formats: list[Literal["markdown", "html"]] = Field(
        default_factory=lambda: ["markdown"],
        description="Recommended input format(s) for preview tools",
    )
    pipeline_patch: dict[str, Any] = Field(default_factory=dict)
    regex_rules: list[RegexRuleModel] = Field(default_factory=list)
    processing_scripts: list[GovernanceProcessingScript] = Field(default_factory=list, max_length=10)


class GovernanceProfileSummary(BaseModel):
    id: UUID | None = None
    key: str
    name: str
    description: str | None = None
    is_system: bool = False


class GovernanceProfileListResponse(BaseModel):
    total: int
    items: list[GovernanceProfileSummary] = Field(default_factory=list)


class GovernanceProfileOut(BaseModel):
    id: UUID | None = None
    key: str
    name: str
    description: str | None = None
    is_system: bool = False
    payload: GovernanceProfilePayload
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GovernanceProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    key: str | None = Field(
        default=None,
        max_length=100,
        description="Optional stable key/slug for the profile (tenant-scoped).",
    )
    payload: GovernanceProfilePayload


class GovernanceProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    payload: GovernanceProfilePayload | None = None


class GovernanceProfileImportResponse(BaseModel):
    created: int = 0
    updated: int = 0
    items: list[GovernanceProfileSummary] = Field(default_factory=list)


class GovernanceProfileResolvedResponse(BaseModel):
    """
    Governance profile resolution output (raw + effective) for UI preview.

    - profile: the selected profile (may include `payload.extends`)
    - chain: inheritance chain from root -> selected profile
    - effective: resolved payload to apply (merged pipeline_patch, concatenated regex_rules)
    """

    profile: GovernanceProfileOut
    chain: list[GovernanceProfileSummary] = Field(default_factory=list)
    effective: GovernanceProfilePayload


class BuiltinProcessingScriptOut(BaseModel):
    """
    Built-in processing script template exposed via the data-governance UI as
    "从模板库选择" on the 重复行学习 page.

    Mirrors :class:`GovernanceProcessingScript` so the UI can splice an instance
    straight into ``payload.processing_scripts`` after user selection.
    """

    key: str
    name: str
    description: str
    language: Literal["javascript", "typescript", "python", "rust"]
    stage: Literal["post_parse", "post_governance"]
    content: str
    tags: list[str] = Field(default_factory=list)


class BuiltinProcessingScriptListResponse(BaseModel):
    total: int
    items: list[BuiltinProcessingScriptOut] = Field(default_factory=list)
