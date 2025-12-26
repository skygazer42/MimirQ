from typing import List, Optional
from uuid import UUID

from app.rag.kg.schemas import SAGBaseModel


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
