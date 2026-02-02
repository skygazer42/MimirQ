"""
Backend metadata schemas.
"""

from typing import Optional

from pydantic import BaseModel, Field


class BuildMeta(BaseModel):
    sha: Optional[str] = None
    time: Optional[str] = None


class MetaFeatureFlags(BaseModel):
    auth_mode: str
    vector_backend: str
    task_queue_enabled: bool
    embedding_cache_enabled: bool
    minio_enabled: bool
    use_langgraph_pipeline: bool
    gzip_enabled: bool = True
    rate_limit_enabled: bool = False
    cors_origins: list[str] = Field(default_factory=list)


class RuntimeMeta(BaseModel):
    python: str
    platform: str


class MetaResponse(BaseModel):
    name: str
    api_version: str
    time: str
    build: BuildMeta
    features: MetaFeatureFlags
    runtime: RuntimeMeta
