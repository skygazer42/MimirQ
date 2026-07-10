"""
Structured table store (TAG) API schemas.
"""


from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class TableColumnOut(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    dtype: str | None = Field(default=None, max_length=100)


class TableAssetOut(BaseModel):
    table_id: str = Field(..., min_length=1, max_length=120)
    document_id: UUID
    document_filename: str | None = Field(default=None, max_length=500)
    sheet_index: int = Field(default=0, ge=0, le=100_000)
    sheet_name: str | None = Field(default=None, max_length=200)
    row_count: int = Field(default=0, ge=0, le=5_000_000)
    col_count: int = Field(default=0, ge=0, le=10_000)
    truncated: bool = False
    columns: list[TableColumnOut] = Field(default_factory=list)
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
    row_source_table: str | None = Field(default=None, max_length=300)
    row_source_sync_token: str | None = Field(default=None, max_length=300)
    row_source_pk_hash_col: str | None = Field(default=None, max_length=120)


class DatasetTablesListResponse(BaseModel):
    total: int
    items: list[TableAssetOut]


class TableQueryRequest(BaseModel):
    sql: str = Field(..., min_length=1, max_length=20_000)
    max_rows: int | None = Field(default=None, ge=1, le=5000)
    max_cols: int | None = Field(default=None, ge=1, le=2000)


class TableQueryResponse(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool = False


class TableAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    # Advanced: allow overriding the default result row cap (still bounded by server hard caps).
    max_rows: int | None = Field(default=None, ge=1, le=5000)


class PlannerJoinProvenanceOut(BaseModel):
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    confidence: float | None = None
    reason: str | None = None


class PlannerCandidateOut(BaseModel):
    candidate_id: str | None = None
    score: float | None = None
    confidence: float | None = None
    penalty_score: float | None = None
    penalties: list[str] = Field(default_factory=list)
    join: PlannerJoinProvenanceOut | None = None
    selected_tables: list[str] = Field(default_factory=list)


class PlannerDiagnosticsOut(BaseModel):
    strategy: str | None = None
    reason: str | None = None
    joins: list[PlannerJoinProvenanceOut] = Field(default_factory=list)
    selected_tables: list[str] = Field(default_factory=list)
    candidates: list[PlannerCandidateOut] = Field(default_factory=list)
    ambiguous: bool | None = None
    ambiguity_gap: float | None = None
    strict_ambiguity: bool | None = None
    aggregation: str | None = None
    aggregation_column: str | None = None
    group_by: dict[str, Any] | None = None
    order_by: dict[str, Any] | None = None
    limit: int | None = None
    sql_fingerprint: str | None = None


class TableAskResponse(BaseModel):
    answer: str
    sql: str | None = None
    data: TableQueryResponse | None = None
    sql_generation_mode: str | None = Field(default=None, max_length=40)
    schema_link_diagnostics: dict[str, Any] | None = None
    planner_diagnostics: PlannerDiagnosticsOut | None = None
    join_provenance: list[PlannerJoinProvenanceOut] | None = None
    sql_fingerprint: str | None = Field(default=None, max_length=64)
    planner_execution_mismatch: dict[str, Any] | None = None


class LotusSemFilterRequest(BaseModel):
    user_instruction: str = Field(..., min_length=1, max_length=2000)
    strategy: str = Field(default="cot", max_length=40)
    max_rows: int | None = Field(default=None, ge=1, le=5000)
