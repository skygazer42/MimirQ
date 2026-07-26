"""
Health check response schemas.
"""


from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    ok: bool
    status: str


class ReadyResponse(HealthResponse):
    pass


class HealthDetailsResponse(ReadyResponse):
    database: dict[str, Any]
    vector: dict[str, Any]
    milvus: dict[str, Any] | None = None
    redis: dict[str, Any]
    minio: dict[str, Any]
    rag_runtime_warmup: dict[str, object] | None = None
    dify_external_knowledge: dict[str, object] | None = None
    time: str
    vector_backend: str
    use_langgraph_pipeline: bool
    task_queue: dict[str, Any]
    uploads: dict[str, Any]
