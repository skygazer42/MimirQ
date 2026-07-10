"""
Simple knowledge base search tool (dataset-scoped).

Note: `app.rag.tools` is a package (MCP tools). This module lives under that
package to avoid the legacy `app/rag/tools.py` name collision.
"""


from uuid import UUID

from app.core.config import settings
from app.rag.retriever import hybrid_retriever


def search_knowledge_base(
    query: str,
    top_k: int = 5,
    *,
    dataset_id: str | None = None,
    document_ids: list[str] | None = None,
    tenant_id: str | None = None,
) -> str:
    """
    Search for relevant document chunks in the knowledge base.

    Enterprise semantics:
    - When `document_ids` is empty, `dataset_id` is required (no tenant-level open scope).
    """
    try:
        doc_uuids: list[UUID] | None = None
        if document_ids:
            doc_uuids = [UUID(str(doc_id)) for doc_id in document_ids if doc_id is not None]

        dataset_uuid: UUID | None = None
        if dataset_id is not None:
            dataset_uuid = UUID(str(dataset_id))

        if not doc_uuids and dataset_uuid is None:
            return "dataset_id is required when document_ids is empty."

        tenant_uuid: UUID | None = None
        if tenant_id:
            tenant_uuid = UUID(str(tenant_id))

        retriever = hybrid_retriever.model_copy(
            update={
                "k": int(top_k or 5),
                "score_threshold": settings.SIMILARITY_THRESHOLD,
                "alpha": 0.6,
                "tenant_id": tenant_uuid,
                "dataset_id": dataset_uuid,
                "document_ids": doc_uuids,
            }
        )
        docs = retriever.invoke(query)

        if not docs:
            return "No relevant documents found. The knowledge base may not contain content related to this query."

        formatted_results: list[str] = []
        for idx, doc in enumerate(docs, 1):
            meta = doc.metadata or {}
            source = meta.get("source", "Unknown")
            page = meta.get("page", meta.get("page_number", "N/A"))
            content = doc.page_content
            score = meta.get("score", 0.0)

            formatted_results.append(
                f"[Document {idx}] {source} - Page {page} (relevance {score:.2f})\n{content}"
            )

        return "\n\n".join(formatted_results)

    except Exception as e:  # noqa: BLE001
        return f"Error occurred during search: {str(e)}"

