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
    path: str | None = None
    tenant_id: UUID | None = None


class ConversationLoadConfig(LoadBaseConfig):
    """Conversation load config (placeholder)."""
    conversation_ids: list[str] = []
    tenant_id: UUID | None = None
