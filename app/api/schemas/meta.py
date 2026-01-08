"""
Backend metadata schemas.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class BuildMeta(BaseModel):
    sha: Optional[str] = None
    time: Optional[str] = None


class FeatureFlags(BaseModel):
    auth_mode: str
    vector_backend: str
    task_queue_enabled: bool
    embedding_cache_enabled: bool
    minio_enabled: bool
    use_langgraph_pipeline: bool


class RuntimeMeta(BaseModel):
    python: str
    platform: str


class MetaResponse(BaseModel):
    name: str
    api_version: str
    time: str
    build: BuildMeta
    features: FeatureFlags
    runtime: RuntimeMeta
