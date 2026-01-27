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


class TableAskResponse(BaseModel):
    answer: str
    sql: Optional[str] = None
    data: Optional[TableQueryResponse] = None


class LotusSemFilterRequest(BaseModel):
    user_instruction: str = Field(..., min_length=1, max_length=2000)
    strategy: str = Field(default="cot", max_length=40)
    max_rows: Optional[int] = Field(default=None, ge=1, le=5000)
