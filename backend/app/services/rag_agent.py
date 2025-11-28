"""
RAG Agent (使用 LangChain + LangGraph)
"""
from typing import AsyncGenerator, Dict, Any, List, Optional
from uuid import UUID
import json

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, RemoveMessage
from langchain.agents import create_agent, AgentState
from langchain.agents.middleware import before_model
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime
from langchain_core.runnables import RunnableConfig

from app.config import settings
from app.services.rag_tools import search_knowledge_base


class RAGAgent:
    """基于 LangChain Agent 的 RAG 对话引擎"""

    def __init__(self):
        # 初始化 LLM
        self.llm = init_chat_model(
            model=settings.LLM_MODEL,
            model_provider="openai",  # 支持 OpenAI 兼容接口
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES
        )

        # 初始化 Checkpoint (PostgreSQL)
        self.checkpointer = self._init_checkpointer()

        # 定义消息裁剪中间件
        @before_model
        def trim_messages(state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
            """保留最近的消息以适应上下文窗口"""
            messages = state["messages"]

            # 保留系统消息 + 最近 10 条消息（5轮对话）
            if len(messages) <= 11:  # 1 system + 10 messages
                return None

            system_msg = messages[0] if isinstance(messages[0], SystemMessage) else None
            recent_messages = messages[-10:]

            new_messages = []
            if system_msg:
                new_messages.append(system_msg)

            return {
                "messages": [
                    RemoveMessage(id=REMOVE_ALL_MESSAGES),
                    *([system_msg] if system_msg else []),
                    *recent_messages
                ]
            }

        # 创建 Agent
        self.agent = create_agent(
            self.llm,
            tools=[search_knowledge_base],
            checkpointer=self.checkpointer,
            middleware=[trim_messages]
        )

        # 系统提示词
        self.system_prompt = """你是 MimirQ 知识库助手，一个专业、友好的 AI 助手。

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

记住：你可以记住对话历史，理解上下文和代词（如"它"、"这个"）。"""

    def _init_checkpointer(self):
        """初始化 Checkpoint（对话记忆持久化）"""
        try:
            # 尝试使用 PostgreSQL Checkpoint
            checkpointer = PostgresSaver.from_conn_string(
                settings.DATABASE_URL
            )
            checkpointer.setup()  # 自动创建表
            print("✅ Using PostgreSQL checkpoint for conversation memory")
            return checkpointer

        except Exception as e:
            # 降级到内存 Checkpoint
            print(f"⚠️  Failed to init PostgreSQL checkpoint: {str(e)}")
            print("⚠️  Falling back to InMemorySaver (conversations won't persist)")
            return InMemorySaver()

    async def stream_chat(
        self,
        question: str,
        conversation_id: Optional[UUID] = None,
        document_ids: Optional[List[UUID]] = None,
        top_k: int = 5,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式对话接口

        Args:
            question: 用户问题
            conversation_id: 对话 ID（用作 thread_id）
            document_ids: 限定文档范围
            top_k: 检索数量

        Yields:
            流式事件
        """
        try:
            # 配置
            config: RunnableConfig = {
                "configurable": {
                    "thread_id": str(conversation_id) if conversation_id else "default"
                }
            }

            # 构建用户消息
            user_message = HumanMessage(content=question)

            # 获取对话状态（包含历史消息）
            state = self.agent.get_state(config)

            # 如果是新对话，添加系统提示
            if not state or not state.values.get("messages"):
                messages = [SystemMessage(content=self.system_prompt), user_message]
            else:
                messages = [user_message]

            # 调用 Agent（流式）
            citations = []
            full_response = ""

            async for event in self.agent.astream(
                {"messages": messages},
                config=config
            ):
                # 解析事件
                if "agent" in event:
                    agent_output = event["agent"]

                    # 提取 AI 消息
                    if "messages" in agent_output:
                        for msg in agent_output["messages"]:
                            if isinstance(msg, AIMessage):
                                # 流式输出 token
                                content = msg.content
                                if content and content not in full_response:
                                    new_content = content[len(full_response):]
                                    full_response = content

                                    yield {
                                        "type": "token",
                                        "data": {"content": new_content}
                                    }

                # 工具调用（检索）
                if "tools" in event:
                    tool_output = event["tools"]

                    if "messages" in tool_output:
                        for msg in tool_output["messages"]:
                            # 提取检索结果作为引用
                            if hasattr(msg, 'content') and '[文档' in str(msg.content):
                                # 解析引用信息
                                citations.append({
                                    "source": "知识库检索",
                                    "content": str(msg.content)[:200] + "..."
                                })

            # 发送引用信息
            if citations:
                yield {
                    "type": "citations",
                    "data": citations
                }

            # 发送完成信号
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


# 全局实例
rag_agent = RAGAgent()
