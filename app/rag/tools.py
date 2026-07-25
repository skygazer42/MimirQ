"""
RAG retrieval helpers (tenant aware).
"""
from contextvars import ContextVar
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.config import settings
from app.rag.retriever import hybrid_retriever

# Current tenant context, set by rag_agent before tool execution
current_tenant_id: ContextVar[UUID | None] = ContextVar("tenant_id", default=None)


class RetrievalInput(BaseModel):
    """Retrieval tool input parameters"""
    query: str = Field(
        min_length=1,
        max_length=settings.RETRIEVAL_QUERY_MAX_CHARS,
        description="User query or keywords",
    )
    top_k: int = Field(
        default=5,
        description="Number of relevant document chunks to return",
        ge=1,
        le=20
    )
    document_ids: list[str] | None = Field(
        default=None,
        description="List of document IDs to limit search scope (optional)"
    )
    tenant_id: str | None = Field(
        default=None,
        description="Tenant ID (optional)"
    )


def search_knowledge_base(
    query: str,
    top_k: int = 5,
    document_ids: list[str] | None = None,
    tenant_id: str | None = None
) -> str:
    """
    Search for relevant document chunks in the knowledge base.
    """
    try:
        doc_uuids = None
        if document_ids:
            doc_uuids = [UUID(doc_id) for doc_id in document_ids]

        tenant_uuid = UUID(tenant_id) if tenant_id else current_tenant_id.get()

        retriever = hybrid_retriever.model_copy(
            update={
                "k": top_k,
                "score_threshold": settings.SIMILARITY_THRESHOLD,
                "alpha": 0.6,
                "tenant_id": tenant_uuid,
                "document_ids": doc_uuids,
            }
        )
        docs = retriever.invoke(query)

        if not docs:
            return "No relevant documents found. The knowledge base may not contain content related to this query."

        formatted_results = []
        for idx, doc in enumerate(docs, 1):
            meta = doc.metadata or {}
            source = meta.get("source", "Unknown")
            page = meta.get("page", "N/A")
            content = doc.page_content
            score = meta.get("score", 0.0)

            formatted_results.append(
                f"[Document {idx}] {source} - Page {page} (relevance {score:.2f})\n{content}"
            )

        return "\n\n".join(formatted_results)

    except Exception as e:
        return f"Error occurred during search: {str(e)}"
