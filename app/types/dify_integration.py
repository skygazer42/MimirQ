"""Shared Dify request, response, and actor types."""

from dataclasses import dataclass
from uuid import UUID

from app.api.schemas.integrations import DifyConversationTurnRequest as DifyConversationTurnRequest
from app.api.schemas.integrations import DifyConversationTurnResponse as DifyConversationTurnResponse
from app.api.schemas.integrations import DifyExternalKnowledgeRecord as DifyExternalKnowledgeRecord
from app.api.schemas.integrations import DifyExternalKnowledgeRequest as DifyExternalKnowledgeRequest
from app.api.schemas.integrations import DifyExternalKnowledgeResponse as DifyExternalKnowledgeResponse
from app.api.schemas.integrations import DifyRetrievalSetting as DifyRetrievalSetting


@dataclass(frozen=True)
class DifyActor:
    tenant_id: UUID
    account_id: str


@dataclass(frozen=True)
class DifyKGFlags:
    enable_query_expansion: bool
    enable_chunk_injection: bool
    chunk_injection_max_chunks: int
    enable_chunk_boost: bool
    chunk_boost_weight: float
    chunk_boost_max_promoted: int

    @property
    def enabled(self) -> bool:
        return bool(self.enable_query_expansion or self.enable_chunk_injection or self.enable_chunk_boost)


__all__ = [
    "DifyActor",
    "DifyConversationTurnRequest",
    "DifyConversationTurnResponse",
    "DifyExternalKnowledgeRecord",
    "DifyExternalKnowledgeRequest",
    "DifyExternalKnowledgeResponse",
    "DifyKGFlags",
    "DifyRetrievalSetting",
]
