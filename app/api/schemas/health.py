"""
Health check response schemas.
"""


from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    ok: bool
    time: str
    vector_backend: str | None = None
    use_langgraph_pipeline: bool | None = None


class DatabaseStatus(BaseModel):
    status: str
    error: str | None = None


class VectorStatus(BaseModel):
    backend: str
    status: str
    error: str | None = None


class RedisStatus(BaseModel):
    status: str
    enabled: bool
    required: bool
    embedding_cache_enabled: bool = Field(default=False, alias="embedding_cache_enabled")
    error: str | None = None


class MinioStatus(BaseModel):
    status: str
    enabled: bool
    bucket: str | None = None
    error: str | None = None


class ReadyResponse(BaseModel):
    ok: bool
    database: DatabaseStatus
    vector: VectorStatus
    redis: RedisStatus
    minio: MinioStatus
    dify_external_knowledge: dict[str, object] | None = None
