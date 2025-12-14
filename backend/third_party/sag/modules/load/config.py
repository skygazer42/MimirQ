from typing import List, Optional
from uuid import UUID

from third_party.sag.models.base import SAGBaseModel


class LoadBaseConfig(SAGBaseModel):
    """Placeholder for compatibility."""
    path: str | None = None


class LoadResult(SAGBaseModel):
    """Placeholder result."""
    success: bool = True


class DocumentLoadConfig(LoadBaseConfig):
    """Document load config (placeholder)."""
    path: Optional[str] = None
    tenant_id: Optional[UUID] = None


class ConversationLoadConfig(LoadBaseConfig):
    """Conversation load config (placeholder)."""
    conversation_ids: List[str] = []
    tenant_id: Optional[UUID] = None
