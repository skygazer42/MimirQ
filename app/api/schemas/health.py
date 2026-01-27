"""
Health check response schemas.
"""

from typing import Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    ok: bool
    time: str
    vector_backend: Optional[str] = None
    use_langgraph_pipeline: Optional[bool] = None


class DatabaseStatus(BaseModel):
    status: str
    error: Optional[str] = None


class VectorStatus(BaseModel):
    backend: str
    status: str
    error: Optional[str] = None


class RedisStatus(BaseModel):
    status: str
    enabled: bool
    required: bool
    embedding_cache_enabled: bool = Field(default=False, alias="embedding_cache_enabled")
    error: Optional[str] = None


class MinioStatus(BaseModel):
    status: str
    enabled: bool
    bucket: Optional[str] = None
    error: Optional[str] = None


class ReadyResponse(BaseModel):
    ok: bool
    database: DatabaseStatus
    vector: VectorStatus
    redis: RedisStatus
    minio: MinioStatus
