"""
RAG Agent (LangChain + LangGraph) with tenant-aware retrieval.
"""
from __future__ import annotations

import os
from typing import AsyncGenerator, Dict, Any, List, Optional
from uuid import UUID

import httpx

from app.core.config import settings


class RAGAgent:
    """基于 LangChain Agent 的 RAG 对话引擎"""

    def __init__(self):
        # Import heavy/langgraph-dependent modules lazily so the FastAPI app
        # can start even if optional RAG deps are not installed yet.
        from langchain_core.messages import SystemMessage, RemoveMessage
        from langchain.agents import create_agent, AgentState
        from langchain.agents.middleware import before_model
        from langgraph.graph.message import REMOVE_ALL_MESSAGES
        from langgraph.runtime import Runtime
        from app.services.rag_tools import search_knowledge_base

        # Some environments set SOCKS proxies via HTTP(S)_PROXY/ALL_PROXY,
        # which LangChain/OpenAI clients don't support. Disable env proxies
        # in that case so the backend can start.
        proxy_candidates = [
            os.getenv("HTTPS_PROXY"),
            os.getenv("HTTP_PROXY"),
            os.getenv("ALL_PROXY"),
        ]
        proxy = next((p for p in proxy_candidates if p), None)
        trust_env = True
        if proxy and proxy.lower().startswith("socks"):
            print(f"[WARN] Unsupported SOCKS proxy for LLM detected: {proxy}. Ignoring env proxies.")
            trust_env = False

        http_client = httpx.Client(trust_env=trust_env)
        http_async_client = httpx.AsyncClient(trust_env=trust_env)

        try:
            from langchain_openai import ChatOpenAI
        except Exception as exc:
            raise RuntimeError(
                "langchain_openai ChatOpenAI is unavailable or incompatible. "
                "Please reinstall backend requirements in a clean venv."
            ) from exc

        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
            http_client=http_client,
            http_async_client=http_async_client,
        )

        self.checkpointer = self._init_checkpointer()

        @before_model
        def trim_messages(state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
            """保留最近的消息以适应上下文窗口"""
            messages = state["messages"]
            if len(messages) <= 11:  # 1 system + 10 messages
                return None
            system_msg = messages[0] if isinstance(messages[0], SystemMessage) else None
            recent_messages = messages[-10:]
            return {
                "messages": [
                    RemoveMessage(id=REMOVE_ALL_MESSAGES),
                    *([system_msg] if system_msg else []),
                    *recent_messages
                ]
            }

        self.agent = create_agent(
            self.llm,
            tools=[search_knowledge_base],
            checkpointer=self.checkpointer,
            middleware=[trim_messages]
        )

        self.system_prompt = """你是 MimirQ 知识库助手，一个专业友好的 AI 助手。

你的职责：
1. 使用 search_knowledge_base 工具在知识库中搜索相关信息
2. 基于搜索结果回答用户问题
3. 如果知识库中没有相关信息，明确告知用户
4. 引用资料时标注来源（文件名和页码）

回答要求：
- 准确：仅基于知识库内容回答
- 简洁：直接回答问题，避免冗余
- 专业：使用准确的术语
- 友好：保持对话的自然和连贯性
"""

    def _init_checkpointer(self):
        """初始化 Checkpoint（对话记忆持久化）"""
        from langgraph.checkpoint.memory import InMemorySaver
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except Exception as exc:
            print(f"[WARN]  Postgres checkpoint module unavailable: {exc}")
            print("[WARN]  Falling back to InMemorySaver (conversations won't persist)")
            return InMemorySaver()

        try:
            checkpointer = PostgresSaver.from_conn_string(
                settings.DATABASE_URL
            )
            checkpointer.setup()
            print("[OK] Using PostgreSQL checkpoint for conversation memory")
            return checkpointer
        except Exception as e:
            print(f"[WARN]  Failed to init PostgreSQL checkpoint: {str(e)}")
            print("[WARN]  Falling back to InMemorySaver (conversations won't persist)")
            return InMemorySaver()

    async def stream_chat(
        self,
        question: str,
        conversation_id: Optional[UUID] = None,
        document_ids: Optional[List[UUID]] = None,
        top_k: int = 5,
        tenant_id: Optional[UUID] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式对话接口"""
        try:
            from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
            from langchain_core.runnables import RunnableConfig

            config: RunnableConfig = {
                "configurable": {
                    "thread_id": str(conversation_id) if conversation_id else "default",
                    "tenant_id": str(tenant_id) if tenant_id else settings.DEFAULT_TENANT_ID
                }
            }

            user_message = HumanMessage(content=question)
            state = self.agent.get_state(config)

            if not state or not state.values.get("messages"):
                messages = [SystemMessage(content=self.system_prompt), user_message]
            else:
                messages = [user_message]

            citations: List[Dict[str, Any]] = []
            full_response = ""

            from app.services.rag_tools import current_tenant_id
            token_ctx = current_tenant_id.set(tenant_id)
            try:
                async for event in self.agent.astream(
                    {"messages": messages},
                    config=config
                ):
                    if "agent" in event:
                        agent_output = event["agent"]
                        if "messages" in agent_output:
                            for msg in agent_output["messages"]:
                                if isinstance(msg, AIMessage):
                                    content = msg.content
                                    if content and content not in full_response:
                                        new_content = content[len(full_response):]
                                        full_response = content
                                        yield {
                                            "type": "token",
                                            "data": {"content": new_content}
                                        }

                    if "tools" in event:
                        tool_output = event["tools"]
                        if "messages" in tool_output:
                            for msg in tool_output["messages"]:
                                if hasattr(msg, 'content') and '[文档' in str(msg.content):
                                    citations.append({
                                        "source": "知识库检索",
                                        "content": str(msg.content)[:200] + "..."
                                    })
            finally:
                current_tenant_id.reset(token_ctx)

            if citations:
                yield {
                    "type": "citations",
                    "data": citations
                }

            yield {
                "type": "done",
                "data": {
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "total_tokens": len(full_response),
                    "citations_count": len(citations)
                }
            }

        except Exception as e:
            yield {
                "type": "error",
                "data": {"message": str(e)}
            }

_rag_agent_instance: Optional[RAGAgent] = None


def get_rag_agent() -> RAGAgent:
    """Lazily initialize the RAG agent to avoid import-time crashes."""
    global _rag_agent_instance
    if _rag_agent_instance is None:
        _rag_agent_instance = RAGAgent()
    return _rag_agent_instance
