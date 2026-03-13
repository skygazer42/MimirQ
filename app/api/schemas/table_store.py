"""
Structured table store (TAG) API schemas.
"""

from __future__ import annotations

from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TableColumnOut(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    dtype: Optional[str] = Field(default=None, max_length=100)


class TableAssetOut(BaseModel):
    table_id: str = Field(..., min_length=1, max_length=120)
    document_id: UUID
    document_filename: Optional[str] = Field(default=None, max_length=500)
    sheet_index: int = Field(default=0, ge=0, le=100_000)
    sheet_name: Optional[str] = Field(default=None, max_length=200)
    row_count: int = Field(default=0, ge=0, le=5_000_000)
    col_count: int = Field(default=0, ge=0, le=10_000)
    truncated: bool = False
    columns: List[TableColumnOut] = Field(default_factory=list)
    sample_rows: List[dict[str, Any]] = Field(default_factory=list)
    row_source_table: Optional[str] = Field(default=None, max_length=300)
    row_source_sync_token: Optional[str] = Field(default=None, max_length=300)
    row_source_pk_hash_col: Optional[str] = Field(default=None, max_length=120)


class DatasetTablesListResponse(BaseModel):
    total: int
    items: List[TableAssetOut]


class TableQueryRequest(BaseModel):
    sql: str = Field(..., min_length=1, max_length=20_000)
    max_rows: Optional[int] = Field(default=None, ge=1, le=5000)
    max_cols: Optional[int] = Field(default=None, ge=1, le=2000)


class TableQueryResponse(BaseModel):
    sql: str
    columns: List[str]
    rows: List[List[Any]]
    truncated: bool = False


class TableAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    # Advanced: allow overriding the default result row cap (still bounded by server hard caps).
    max_rows: Optional[int] = Field(default=None, ge=1, le=5000)


class PlannerJoinProvenanceOut(BaseModel):
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    confidence: Optional[float] = None
    reason: Optional[str] = None


class PlannerCandidateOut(BaseModel):
    candidate_id: Optional[str] = None
    score: Optional[float] = None
    confidence: Optional[float] = None
    penalty_score: Optional[float] = None
    penalties: List[str] = Field(default_factory=list)
    join: Optional[PlannerJoinProvenanceOut] = None
    selected_tables: List[str] = Field(default_factory=list)


class PlannerDiagnosticsOut(BaseModel):
    strategy: Optional[str] = None
    reason: Optional[str] = None
    joins: List[PlannerJoinProvenanceOut] = Field(default_factory=list)
    selected_tables: List[str] = Field(default_factory=list)
    candidates: List[PlannerCandidateOut] = Field(default_factory=list)
    ambiguous: Optional[bool] = None
    ambiguity_gap: Optional[float] = None
    strict_ambiguity: Optional[bool] = None
    aggregation: Optional[str] = None
    aggregation_column: Optional[str] = None
    group_by: Optional[dict[str, Any]] = None
    order_by: Optional[dict[str, Any]] = None
    limit: Optional[int] = None
    sql_fingerprint: Optional[str] = None


class TableAskResponse(BaseModel):
    answer: str
    sql: Optional[str] = None
    data: Optional[TableQueryResponse] = None
    sql_generation_mode: Optional[str] = Field(default=None, max_length=40)
    schema_link_diagnostics: Optional[dict[str, Any]] = None
    planner_diagnostics: Optional[PlannerDiagnosticsOut] = None
    join_provenance: Optional[List[PlannerJoinProvenanceOut]] = None
    sql_fingerprint: Optional[str] = Field(default=None, max_length=64)
    planner_execution_mismatch: Optional[dict[str, Any]] = None


class LotusSemFilterRequest(BaseModel):
    user_instruction: str = Field(..., min_length=1, max_length=2000)
    strategy: str = Field(default="cot", max_length=40)
    max_rows: Optional[int] = Field(default=None, ge=1, le=5000)
