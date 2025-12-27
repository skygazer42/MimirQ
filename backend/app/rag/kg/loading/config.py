from typing import List, Optional
from uuid import UUID

from app.rag.kg.schemas import KGBaseModel


class LoadBaseConfig(KGBaseModel):
    """Placeholder for compatibility."""
    path: str | None = None


class LoadResult(KGBaseModel):
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
