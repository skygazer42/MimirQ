"""
Backend metadata schemas.
"""


from pydantic import BaseModel, Field


class BuildMeta(BaseModel):
    sha: str | None = None
    time: str | None = None


class MetaFeatureFlags(BaseModel):
    auth_mode: str
    vector_backend: str
    kg_enabled: bool
    task_queue_enabled: bool
    embedding_cache_enabled: bool
    minio_enabled: bool
    use_langgraph_pipeline: bool
    gzip_enabled: bool = True
    rate_limit_enabled: bool = False
    cors_origins: list[str] = Field(default_factory=list)


class PublicMetaFeatureFlags(BaseModel):
    auth_mode: str


class RuntimeMeta(BaseModel):
    python: str
    platform: str


class MetaResponse(BaseModel):
    name: str
    api_version: str
    build: BuildMeta
    features: PublicMetaFeatureFlags


class MetaDetailsResponse(MetaResponse):
    time: str
    features: MetaFeatureFlags
    runtime: RuntimeMeta
