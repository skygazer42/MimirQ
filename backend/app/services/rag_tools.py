"""
RAG tools definition (LangChain Tools) - tenant aware.
"""
from typing import List, Optional
from uuid import UUID
from contextvars import ContextVar
from pydantic import BaseModel, Field
from langchain.tools import tool

from app.services.hybrid_retriever import hybrid_retriever
from app.config import settings

# Current tenant context, set by rag_agent before tool execution
current_tenant_id: ContextVar[Optional[UUID]] = ContextVar("tenant_id", default=None)


class RetrievalInput(BaseModel):
    """检索工具输入参数"""
    query: str = Field(description="用户的查询问题或关键词")
    top_k: int = Field(
        default=5,
        description="返回的相关文档片段数量",
        ge=1,
        le=20
    )
    document_ids: Optional[List[str]] = Field(
        default=None,
        description="限定搜索的文档ID列表（可选）"
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="租户 ID（可选）"
    )


@tool(args_schema=RetrievalInput)
def search_knowledge_base(
    query: str,
    top_k: int = 5,
    document_ids: Optional[List[str]] = None,
    tenant_id: Optional[str] = None
) -> str:
    """
    在知识库中搜索相关文档片段。
    """
    try:
        doc_uuids = None
        if document_ids:
            doc_uuids = [UUID(doc_id) for doc_id in document_ids]

        tenant_uuid = UUID(tenant_id) if tenant_id else current_tenant_id.get()

        results = hybrid_retriever.hybrid_search(
            query=query,
            top_k=top_k,
            score_threshold=settings.SIMILARITY_THRESHOLD,
            document_ids=doc_uuids,
            tenant_id=tenant_uuid,
            alpha=0.6
        )

        if not results:
            return "未找到相关文档。知识库中可能没有与此查询相关的内容。"

        formatted_results = []
        for idx, result in enumerate(results, 1):
            source = result['metadata'].get('source', 'Unknown')
            page = result['metadata'].get('page', 'N/A')
            content = result['content']
            score = result.get('score', 0.0)

            formatted_results.append(
                f"[文档 {idx}] {source} - 第{page}页(相关度 {score:.2f})\n{content}"
            )

        return "\n\n".join(formatted_results)

    except Exception as e:
        return f"搜索过程中发生错误: {str(e)}"
