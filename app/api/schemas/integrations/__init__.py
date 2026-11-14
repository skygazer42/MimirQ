"""Public external integration API contracts."""

from app.api.schemas.integrations.conversations import (
    ExternalConversationAsyncIngestResponse,
    ExternalConversationIngestRequest,
    ExternalConversationIngestResponse,
    ExternalConversationMessageIn,
)
from app.api.schemas.integrations.dify import (
    DifyConversationTurnRequest,
    DifyConversationTurnResponse,
    DifyExternalKnowledgeRecord,
    DifyExternalKnowledgeRequest,
    DifyExternalKnowledgeResponse,
    DifyRetrievalSetting,
)

__all__ = [
    "DifyConversationTurnRequest",
    "DifyConversationTurnResponse",
    "DifyExternalKnowledgeRecord",
    "DifyExternalKnowledgeRequest",
    "DifyExternalKnowledgeResponse",
    "DifyRetrievalSetting",
    "ExternalConversationAsyncIngestResponse",
    "ExternalConversationIngestRequest",
    "ExternalConversationIngestResponse",
    "ExternalConversationMessageIn",
]
