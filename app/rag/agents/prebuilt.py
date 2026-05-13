"""
Prebuilt Agent Integration for LangGraph.

"""

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, create_react_agent
from langgraph.prebuilt.tool_node import tools_condition

from app.core.config import settings
from app.rag.checkpointer.factory import get_checkpointer
from app.rag.core.logging import get_logger

logger = get_logger("rag.agents.prebuilt")

# Configuration
AGENT_MAX_ITERATIONS = getattr(settings, "AGENT_MAX_ITERATIONS", 10)
AGENT_RECURSION_LIMIT = getattr(settings, "AGENT_RECURSION_LIMIT", 25)


def create_rag_agent(
    model: str | BaseChatModel,
    tools: Sequence[BaseTool | Callable],
    *,
    system_prompt: str | None = None,
    checkpointer: Any | None = None,
    store: Any | None = None,
    max_iterations: int | None = None,
    **kwargs,
) -> CompiledStateGraph:
    """
    Create a prebuilt ReAct agent for RAG workflows.

    This wraps LangGraph's create_react_agent with sensible defaults
    for RAG use cases.

    Args:
        model: Model name (e.g., "openai:gpt-4") or BaseChatModel instance
        tools: List of tools for the agent to use
        system_prompt: Optional system prompt for the agent
        checkpointer: Optional checkpointer for state persistence
        store: Optional store for long-term memory
        max_iterations: Maximum number of tool-calling iterations
        **kwargs: Additional arguments passed to create_react_agent

    Returns:
        Compiled LangGraph agent

    Example:
        from langchain_core.tools import tool

        @tool
        def search(query: str) -> str:
            \"\"\"Search for documents.\"\"\"
            return "Found: ..."

        agent = create_rag_agent(
            model="openai:gpt-4o",
            tools=[search],
            system_prompt="You are a RAG assistant.",
        )

        result = agent.invoke({"messages": [HumanMessage(content="Find docs about AI")]})
    """
    # Use default checkpointer if not provided
    if checkpointer is None:
        checkpointer = get_checkpointer()

    # Build prompt
    prompt = system_prompt
    if prompt is None:
        prompt = _get_default_rag_prompt()

    # Set recursion limit based on max_iterations
    if max_iterations is not None:
        kwargs.setdefault("recursion_limit", max_iterations * 2 + 5)
    else:
        kwargs.setdefault("recursion_limit", AGENT_RECURSION_LIMIT)

    logger.info(
        "Creating RAG agent with %d tools, checkpointer=%s",
        len(tools), type(checkpointer).__name__
    )

    return create_react_agent(
        model=model,
        tools=list(tools),
        prompt=prompt,
        checkpointer=checkpointer,
        store=store,
        **kwargs,
    )


def _get_default_rag_prompt() -> str:
    """Get the default system prompt for RAG agents."""
    return """You are a helpful RAG (Retrieval-Augmented Generation) assistant.

Your role is to:
1. Understand the user's question
2. Use the available tools to retrieve relevant information
3. Synthesize the retrieved information into a clear, accurate answer
4. Cite sources when possible

Guidelines:
- Always search for information before answering factual questions
- If you can't find relevant information, say so honestly
- Provide concise but complete answers
- When multiple sources agree, that increases confidence in the answer
"""


def create_rag_tool_node(
    tools: Sequence[BaseTool | Callable],
    *,
    handle_tool_errors: bool = True,
    messages_key: str = "messages",
) -> ToolNode:
    """
    Create a ToolNode for RAG tool execution.

    Args:
        tools: List of tools to execute
        handle_tool_errors: Whether to catch and return tool errors
        messages_key: Key in state for messages

    Returns:
        Configured ToolNode
    """
    return ToolNode(
        tools=list(tools),
        handle_tool_errors=handle_tool_errors,
        messages_key=messages_key,
    )


def create_retriever_tool(
    retriever_func: Callable[[str], list[dict[str, Any]]],
    name: str = "retrieve",
    description: str = "Retrieve relevant documents for a query",
) -> BaseTool:
    """
    Create a retriever tool from a retrieval function.

    Args:
        retriever_func: Function that takes a query and returns documents
        name: Tool name
        description: Tool description

    Returns:
        LangChain tool

    Example:
        async def my_retriever(query: str) -> List[Dict]:
            # Your retrieval logic
            return [{"content": "...", "metadata": {...}}]

        tool = create_retriever_tool(my_retriever)
    """
    from langchain_core.tools import tool as tool_decorator

    @tool_decorator(name=name, description=description)
    def retrieve(query: str) -> str:
        """Retrieve documents for the given query."""
        try:
            import asyncio
            # Handle both sync and async retrieval
            if asyncio.iscoroutinefunction(retriever_func):
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(asyncio.run, retriever_func(query))
                        results = future.result()
                else:
                    results = loop.run_until_complete(retriever_func(query))
            else:
                results = retriever_func(query)

            if not results:
                return "No relevant documents found."

            # Format results
            output_parts = []
            for i, doc in enumerate(results[:5], 1):
                content = doc.get("content", doc.get("page_content", ""))[:500]
                source = doc.get("metadata", {}).get("source", "Unknown")
                output_parts.append(f"[{i}] Source: {source}\n{content}")

            return "\n\n".join(output_parts)

        except Exception as e:
            logger.error("Retrieval failed: %s", e)
            return f"Error during retrieval: {str(e)[:200]}"

    return retrieve


def create_search_tool(
    search_func: Callable[[str], list[dict[str, Any]]],
    name: str = "search",
    description: str = "Search for information in the knowledge base",
) -> BaseTool:
    """
    Create a search tool from a search function.

    Similar to create_retriever_tool but named differently for semantic clarity.
    """
    return create_retriever_tool(
        retriever_func=search_func,
        name=name,
        description=description,
    )


class RAGAgentConfig:
    """Configuration for RAG agents."""

    def __init__(
        self,
        model: str | BaseChatModel = "openai:gpt-4o",
        system_prompt: str | None = None,
        max_iterations: int = AGENT_MAX_ITERATIONS,
        enable_checkpointing: bool = True,
        enable_memory: bool = False,
    ):
        self.model = model
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.enable_checkpointing = enable_checkpointing
        self.enable_memory = enable_memory


class RAGAgent:
    """
    High-level wrapper for RAG agents.

    Provides a simpler interface for common RAG agent operations.

    Usage:
        agent = RAGAgent(config=RAGAgentConfig())
        agent.add_tool(retrieve_tool)
        agent.add_tool(search_tool)

        # Build and run
        graph = agent.build()
        result = await agent.query("What is RAG?")
    """

    def __init__(self, config: RAGAgentConfig | None = None):
        self.config = config or RAGAgentConfig()
        self._tools: list[BaseTool | Callable] = []
        self._graph: CompiledStateGraph | None = None

    def add_tool(self, tool: BaseTool | Callable) -> "RAGAgent":
        """Add a tool to the agent."""
        self._tools.append(tool)
        self._graph = None  # Reset compiled graph
        return self

    def add_retriever(
        self,
        retriever_func: Callable[[str], list[dict[str, Any]]],
        name: str = "retrieve",
        description: str = "Retrieve relevant documents",
    ) -> "RAGAgent":
        """Add a retriever as a tool."""
        tool = create_retriever_tool(retriever_func, name, description)
        return self.add_tool(tool)

    def build(self) -> CompiledStateGraph:
        """Build the agent graph."""
        if self._graph is not None:
            return self._graph

        checkpointer = None
        if self.config.enable_checkpointing:
            checkpointer = get_checkpointer()

        store = None
        if self.config.enable_memory:
            from langgraph.store.memory import InMemoryStore
            store = InMemoryStore()

        self._graph = create_rag_agent(
            model=self.config.model,
            tools=self._tools,
            system_prompt=self.config.system_prompt,
            checkpointer=checkpointer,
            store=store,
            max_iterations=self.config.max_iterations,
        )

        return self._graph

    async def aquery(
        self,
        query: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Async query the agent.

        Args:
            query: User query
            thread_id: Optional thread ID for conversation continuity

        Returns:
            Agent response
        """
        graph = self.build()

        config = {}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}

        messages = [HumanMessage(content=query)]
        result = await graph.ainvoke({"messages": messages}, config)

        return result

    def query(
        self,
        query: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Sync query the agent.

        Args:
            query: User query
            thread_id: Optional thread ID for conversation continuity

        Returns:
            Agent response
        """
        graph = self.build()

        config = {}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}

        messages = [HumanMessage(content=query)]
        result = graph.invoke({"messages": messages}, config)

        return result

    def stream(
        self,
        query: str,
        thread_id: str | None = None,
        stream_mode: str = "updates",
    ):
        """
        Stream agent responses.

        Args:
            query: User query
            thread_id: Optional thread ID
            stream_mode: Stream mode ("updates", "values")

        Yields:
            Stream events
        """
        graph = self.build()

        config = {}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}

        messages = [HumanMessage(content=query)]

        for event in graph.stream(
            {"messages": messages},
            config,
            stream_mode=stream_mode,
        ):
            yield event


# Re-export LangGraph prebuilt components
__all__ = [
    "create_rag_agent",
    "create_rag_tool_node",
    "create_retriever_tool",
    "create_search_tool",
    "RAGAgent",
    "RAGAgentConfig",
    "ToolNode",
    "tools_condition",
]
