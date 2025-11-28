"""
RAG 工具定义 (LangChain Tools)
"""
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from langchain.tools import tool

from app.services.hybrid_retriever import hybrid_retriever
from app.config import settings


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


@tool(args_schema=RetrievalInput)
def search_knowledge_base(
    query: str,
    top_k: int = 5,
    document_ids: Optional[List[str]] = None
) -> str:
    """
    在知识库中搜索相关文档片段。

    使用混合检索（向量检索 + BM25 关键词检索）来找到最相关的内容。
    适用于：
    - 回答用户问题时查找参考资料
    - 搜索特定的技术文档或代码片段
    - 查找包含专有名词、代码、数字等精确内容

    Args:
        query: 搜索查询，可以是问题、关键词或代码片段
        top_k: 返回最相关的 K 个文档片段
        document_ids: 限定搜索范围到特定文档（可选）

    Returns:
        格式化的搜索结果，包含文档内容、来源和页码
    """
    try:
        # 转换 document_ids 为 UUID
        doc_uuids = None
        if document_ids:
            doc_uuids = [UUID(doc_id) for doc_id in document_ids]

        # 执行混合检索
        results = hybrid_retriever.hybrid_search(
            query=query,
            top_k=top_k,
            score_threshold=settings.SIMILARITY_THRESHOLD,
            document_ids=doc_uuids,
            alpha=0.6
        )

        if not results:
            return "未找到相关文档。知识库中可能没有与此查询相关的内容。"

        # 格式化结果
        formatted_results = []
        for idx, result in enumerate(results, 1):
            source = result['metadata'].get('source', 'Unknown')
            page = result['metadata'].get('page', 'N/A')
            content = result['content']
            score = result.get('score', 0.0)

            formatted_results.append(
                f"[文档 {idx}] {source} - 第 {page} 页 (相关度: {score:.2f})\n{content}"
            )

        return "\n\n".join(formatted_results)

    except Exception as e:
        return f"搜索过程中发生错误: {str(e)}"
