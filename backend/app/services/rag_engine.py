"""
RAG 对话引擎
"""
from typing import AsyncGenerator, Dict, Any, List, Optional
from uuid import UUID
import json
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate

from app.config import settings
from app.services.milvus_store import milvus_store


class RAGEngine:
    """RAG 对话引擎"""

    def __init__(self):
        # LLM 配置
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE,
            temperature=settings.LLM_TEMPERATURE,
            streaming=True,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES
        )

        # Prompt 模板
        self.prompt_template = PromptTemplate(
            input_variables=["context", "question"],
            template="""你是一个专业的知识库助手。请基于以下参考资料回答用户问题。

【参考资料】
{context}

【用户问题】
{question}

【回答要求】
1. 仅基于参考资料回答，不要编造信息
2. 如果参考资料中没有相关信息，请明确告知用户"根据现有资料无法回答该问题"
3. 回答要准确、简洁、专业
4. 引用资料时可以提及来源文件名

【回答】"""
        )

    async def stream_chat(
        self,
        question: str,
        conversation_id: Optional[UUID] = None,
        document_ids: Optional[List[UUID]] = None,
        top_k: int = 5,
        score_threshold: float = 0.7
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式对话接口

        Args:
            question: 用户问题
            conversation_id: 对话 ID
            document_ids: 限定文档范围
            top_k: 检索 Top-K
            score_threshold: 相似度阈值

        Yields:
            流式事件: {"type": "citations|token|done|error", "data": ...}
        """
        try:
            # Step 1: 在 Milvus 中检索相关文档片段
            search_results = milvus_store.search(
                query=question,
                top_k=top_k,
                score_threshold=score_threshold,
                document_ids=document_ids
            )

            # 构建引用信息
            citations = []
            for result in search_results:
                citations.append({
                    "document_id": result['metadata'].get('document_id'),
                    "document_name": result['metadata'].get('source', 'Unknown'),
                    "chunk_content": result['content'][:200] + "...",
                    "page_number": result['metadata'].get('page'),
                    "relevance_score": round(result['score'], 2)
                })

            # 发送引用信息
            yield {
                "type": "citations",
                "data": citations
            }

            # Step 2: 构建上下文
            if not search_results:
                context = "没有找到相关的参考资料。"
            else:
                context_parts = []
                for idx, result in enumerate(search_results, 1):
                    source = result['metadata'].get('source', 'Unknown')
                    page = result['metadata'].get('page', 'N/A')
                    context_parts.append(
                        f"[来源 {idx}: {source} - 第 {page} 页]\n{result['content']}"
                    )
                context = "\n\n".join(context_parts)

            # 构建 Prompt
            prompt = self.prompt_template.format(
                context=context,
                question=question
            )

            # Step 3: 流式生成回答
            full_response = ""
            async for chunk in self.llm.astream(prompt):
                token = chunk.content

                if token:
                    full_response += token

                    yield {
                        "type": "token",
                        "data": {"content": token}
                    }

            # Step 4: 发送完成信号
            yield {
                "type": "done",
                "data": {
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "total_tokens": len(full_response),
                    "citations_count": len(citations)
                }
            }

        except Exception as e:
            # 错误处理
            yield {
                "type": "error",
                "data": {"message": str(e)}
            }


# 全局实例
rag_engine = RAGEngine()
