"""
Dataset Ingestion Policy schemas.

This feature configures *pre-processing before parsing* (file-level) and
per-file-type ingestion overrides (parser backend / chunk strategy / governance profile).

Security notes:
- Policies are declarative JSON only (no executable code).
- Validation and normalization is enforced in app/services/ingestion_policy.py.
"""


from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class IngestionPreprocessStep(BaseModel):
    """
    One pre-processing step applied to the raw file before parsing.

    The backend only supports a small allowlist of step ids; unknown steps are rejected.
    """

    id: str = Field(..., min_length=1, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)


class IngestionPreprocessConfig(BaseModel):
    enabled: bool = True
    steps: list[IngestionPreprocessStep] = Field(default_factory=list)


class IngestionRuleMatch(BaseModel):
    """
    Rule matching conditions.

    - extensions: file extensions like ".pdf", ".html". Empty means "match all".
    - filename_regex: optional regex applied to the *original filename*.
    """

    extensions: list[str] = Field(default_factory=list)
    filename_regex: str | None = Field(default=None, max_length=500)


class IngestionRule(BaseModel):
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    enabled: bool = True
    match: IngestionRuleMatch = Field(default_factory=IngestionRuleMatch)
    preprocess: IngestionPreprocessConfig = Field(default_factory=IngestionPreprocessConfig)

    # Optional overrides (applied when policy is enabled and matches).
    parser_backend: str | None = Field(default=None, max_length=50)
    chunk_strategy: str | None = Field(default=None, max_length=80)
    governance_profile_ref: str | None = Field(default=None, max_length=120)

    # Partial DocumentPipelineOptions shape (validated server-side).
    pipeline_patch: dict[str, Any] = Field(default_factory=dict)


class IngestionPolicy(BaseModel):
    version: str = Field(default="1", description="Policy schema version")
    rules: list[IngestionRule] = Field(default_factory=list)


class TableRoutingSettingAudit(BaseModel):
    value: bool
    source: Literal["rule_pipeline_patch", "dataset_pipeline_default", "global_default"]


class IngestionRuleTableRoutingAudit(BaseModel):
    rule_id: str
    rule_name: str
    enabled: bool
    match_extensions: list[str] = Field(default_factory=list)
    table_rule_match: bool = False
    table_store_enabled: TableRoutingSettingAudit
    table_store_auto_route: TableRoutingSettingAudit
    table_store_sidecar_exclusive_routing: TableRoutingSettingAudit


class DatasetTableRoutingPolicyAudit(BaseModel):
    version: str = Field(default="1")
    table_extensions: list[str] = Field(default_factory=lambda: [".csv", ".xls", ".xlsx"])
    global_defaults: dict[str, bool] = Field(default_factory=dict)
    dataset_pipeline_defaults: dict[str, bool] = Field(default_factory=dict)
    rules: list[IngestionRuleTableRoutingAudit] = Field(default_factory=list)


class IngestionPolicyWithAudit(IngestionPolicy):
    table_routing_policy_audit: DatasetTableRoutingPolicyAudit


class IngestionPolicyImportResponse(BaseModel):
    replaced: bool = False
    rule_count: int = 0


class IngestionPolicyVersion(BaseModel):
    """
    One version entry for a dataset ingestion policy (stored in dataset metadata).

    Note: This is best-effort "versioning for operators" rather than a full audit log.
    """

    id: str = Field(..., min_length=1, max_length=100)
    created_at: datetime
    created_by: str | None = None
    source: Literal["put", "import", "rollback"] = "put"
    policy: IngestionPolicy
    note: str | None = Field(default=None, max_length=200)
    rollback_from_version_id: str | None = None
    rollback_to_version_id: str | None = None


class IngestionPolicyVersionListResponse(BaseModel):
    current_version_id: str | None = None
    items: list[IngestionPolicyVersion] = Field(default_factory=list)


class IngestionPolicyRollbackRequest(BaseModel):
    version_id: str = Field(..., min_length=1, max_length=100)
