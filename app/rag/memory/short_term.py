"""
Short-term memory management for RAG pipelines.

Provides message trimming, conversation summarization, and automatic cleanup
to manage context window efficiently.

Features:
- trim_messages(): Prune messages to fit within token limits
- SummarizationMiddleware: Automatic conversation summarization
- ShortTermMemoryManager: Unified short-term memory interface
"""


from collections.abc import Callable
from functools import wraps
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.messages import (
    trim_messages as lc_trim_messages,
)

from app.core.async_bridge import run_coroutine_sync
from app.core.config import settings
from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger

logger = get_logger("rag.memory.short_term")
MessageLike = BaseMessage | dict[str, Any]


# Configuration defaults
SHORT_TERM_MEMORY_MAX_TOKENS = getattr(settings, "SHORT_TERM_MEMORY_MAX_TOKENS", 4000)
SUMMARIZATION_THRESHOLD = getattr(settings, "SUMMARIZATION_THRESHOLD", 10)
CHAT_HISTORY_WINDOW = getattr(settings, "CHAT_HISTORY_WINDOW", 5)


def _estimate_tokens(text: str) -> int:
    """
    Estimate token count for text (rough approximation).

    Uses a simple heuristic: ~4 characters per token for English,
    ~2 characters per token for Chinese.
    """
    if not text:
        return 0

    # Count CJK characters
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    non_cjk_count = len(text) - cjk_count

    # CJK: ~2 chars/token, English: ~4 chars/token
    return int(cjk_count / 2 + non_cjk_count / 4)


def _message_to_tokens(message: MessageLike) -> int:
    """Estimate tokens for a message."""
    if isinstance(message, BaseMessage):
        content = message.content or ""
    elif isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = str(message)

    # Handle list content (multimodal)
    if isinstance(content, list):
        text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
        content = " ".join(text_parts)

    return _estimate_tokens(str(content))


def trim_messages(
    messages: list[MessageLike],
    max_tokens: int = SHORT_TERM_MEMORY_MAX_TOKENS,
    strategy: str = "last",
    include_system: bool = True,
    allow_partial: bool = False,
    start_on: str | None = None,
    end_on: str | None = None,
) -> list[MessageLike]:
    """
    Trim messages to fit within token limit.

    Args:
        messages: List of messages to trim
        max_tokens: Maximum token count
        strategy: Trimming strategy - "first" or "last"
        include_system: Whether to always include system messages
        allow_partial: Whether to allow partial message content
        start_on: Message type to start on (e.g., "human")
        end_on: Message type to end on (e.g., "ai")

    Returns:
        Trimmed list of messages

    Examples:
        >>> messages = [SystemMessage(...), HumanMessage(...), AIMessage(...)]
        >>> trimmed = trim_messages(messages, max_tokens=1000, strategy="last")
    """
    if not messages:
        return []

    # Convert dicts to BaseMessage if needed
    converted = []
    for msg in messages:
        if isinstance(msg, BaseMessage):
            converted.append(msg)
        elif isinstance(msg, dict):
            role = msg.get("role", "human")
            content = msg.get("content", "")
            if role == "system":
                converted.append(SystemMessage(content=content))
            elif role == "assistant" or role == "ai":
                converted.append(AIMessage(content=content))
            else:
                converted.append(HumanMessage(content=content))
        else:
            converted.append(HumanMessage(content=str(msg)))

    # Use LangChain's trim_messages if available
    try:
        return lc_trim_messages(
            converted,
            max_tokens=max_tokens,
            token_counter=_message_to_tokens,
            strategy=strategy,
            include_system=include_system,
            allow_partial=allow_partial,
            start_on=start_on,
            end_on=end_on,
        )
    except Exception as e:
        logger.warning("LangChain trim_messages failed: %s, using fallback", e)
        return _fallback_trim(converted, max_tokens, strategy, include_system)


def _fallback_trim(
    messages: list[BaseMessage],
    max_tokens: int,
    strategy: str,
    include_system: bool,
) -> list[BaseMessage]:
    """Fallback trimming implementation."""
    if not messages:
        return []

    # Extract system messages if needed
    system_msgs = []
    other_msgs = []
    for msg in messages:
        if isinstance(msg, SystemMessage) and include_system:
            system_msgs.append(msg)
        else:
            other_msgs.append(msg)

    # Calculate system message tokens
    system_tokens = sum(_message_to_tokens(m) for m in system_msgs)
    available_tokens = max_tokens - system_tokens

    if available_tokens <= 0:
        return system_msgs

    # Trim other messages
    if strategy == "first":
        # Keep first messages
        trimmed = []
        current_tokens = 0
        for msg in other_msgs:
            msg_tokens = _message_to_tokens(msg)
            if current_tokens + msg_tokens <= available_tokens:
                trimmed.append(msg)
                current_tokens += msg_tokens
            else:
                break
        return system_msgs + trimmed
    else:
        # Keep last messages (default)
        trimmed = []
        current_tokens = 0
        for msg in reversed(other_msgs):
            msg_tokens = _message_to_tokens(msg)
            if current_tokens + msg_tokens <= available_tokens:
                trimmed.insert(0, msg)
                current_tokens += msg_tokens
            else:
                break
        return system_msgs + trimmed


async def summarize_messages(
    messages: list[MessageLike],
    llm: Any | None = None,
    max_summary_tokens: int = 500,
) -> str:
    """
    Summarize a list of messages into a concise summary.

    Args:
        messages: Messages to summarize
        llm: Language model to use for summarization
        max_summary_tokens: Maximum tokens for the summary

    Returns:
        Summary string
    """
    if not messages:
        return ""

    # Convert messages to text
    conversation_text = []
    for msg in messages:
        if isinstance(msg, BaseMessage):
            role = msg.__class__.__name__.replace("Message", "")
            content = msg.content
        elif isinstance(msg, dict):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
        else:
            role = "unknown"
            content = str(msg)

        if isinstance(content, list):
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
            content = " ".join(text_parts)

        conversation_text.append(f"{role}: {content}")

    full_conversation = "\n".join(conversation_text)

    if llm is None:
        # Fallback: simple truncation-based summary
        logger.debug("No LLM provided for summarization, using truncation fallback")
        truncated = full_conversation[:max_summary_tokens * 4]  # ~4 chars per token
        if len(full_conversation) > len(truncated):
            truncated += "..."
        return f"[Previous conversation summary]\n{truncated}"

    try:
        # Use LLM for summarization
        summary_prompt = f"""Summarize the following conversation concisely, preserving key information:

{full_conversation}

Summary (be concise, focus on key facts and decisions):"""

        response = await llm.ainvoke(summary_prompt)
        summary = response.content if hasattr(response, 'content') else str(response)
        return f"[Conversation summary]\n{summary}"
    except Exception as e:
        logger.warning("LLM summarization failed: %s", e)
        return f"[Previous conversation]\n{full_conversation[:max_summary_tokens * 4]}..."


class ShortTermMemoryManager:
    """
    Manager for short-term conversation memory.

    Handles:
    - Message trimming to fit context window
    - Automatic summarization when history exceeds threshold
    - Message deduplication and cleanup

    Usage:
        manager = ShortTermMemoryManager(max_tokens=4000)
        trimmed = manager.process(messages)
    """

    def __init__(
        self,
        max_tokens: int = SHORT_TERM_MEMORY_MAX_TOKENS,
        summarization_threshold: int = SUMMARIZATION_THRESHOLD,
        strategy: str = "last",
        include_system: bool = True,
        enable_summarization: bool = True,
        llm: Any | None = None,
    ):
        """
        Initialize the short-term memory manager.

        Args:
            max_tokens: Maximum tokens allowed
            summarization_threshold: Number of messages before summarization
            strategy: Trimming strategy ("first" or "last")
            include_system: Whether to preserve system messages
            enable_summarization: Whether to enable automatic summarization
            llm: Language model for summarization (optional)
        """
        self.max_tokens = max_tokens
        self.summarization_threshold = summarization_threshold
        self.strategy = strategy
        self.include_system = include_system
        self.enable_summarization = enable_summarization
        self.llm = llm
        self._summary_cache: dict[str, str] = {}

    def process(
        self,
        messages: list[MessageLike],
        session_id: str | None = None,
    ) -> list[MessageLike]:
        """
        Process messages: trim and optionally summarize.

        Args:
            messages: Messages to process
            session_id: Optional session ID for caching summaries

        Returns:
            Processed messages within token limit
        """
        if not messages:
            return []

        # Check if summarization is needed
        if self.enable_summarization and len(messages) > self.summarization_threshold:
            # Split into old and recent messages
            split_point = len(messages) - self.summarization_threshold
            old_messages = messages[:split_point]
            recent_messages = messages[split_point:]

            # Get or create summary for old messages
            cache_key = session_id or f"msgs:{stable_hash(str(old_messages))}"
            if cache_key not in self._summary_cache:
                # Bridge to the async summarizer even when a loop is already
                # running (offloads to a worker thread) so sync callers get a
                # real LLM summary instead of the degraded simple fallback.
                try:
                    summary = run_coroutine_sync(
                        lambda: summarize_messages(old_messages, self.llm)
                    )
                except Exception:
                    summary = self._simple_summary(old_messages)

                self._summary_cache[cache_key] = summary

            summary = self._summary_cache.get(cache_key, "")

            # Combine summary with recent messages
            if summary:
                summary_msg = SystemMessage(content=summary)
                messages = [summary_msg] + list(recent_messages)

        # Apply trimming
        return trim_messages(
            messages,
            max_tokens=self.max_tokens,
            strategy=self.strategy,
            include_system=self.include_system,
        )

    async def aprocess(
        self,
        messages: list[MessageLike],
        session_id: str | None = None,
    ) -> list[MessageLike]:
        """
        Async version of process().
        """
        if not messages:
            return []

        if self.enable_summarization and len(messages) > self.summarization_threshold:
            split_point = len(messages) - self.summarization_threshold
            old_messages = messages[:split_point]
            recent_messages = messages[split_point:]

            cache_key = session_id or f"msgs:{stable_hash(str(old_messages))}"
            if cache_key not in self._summary_cache:
                summary = await summarize_messages(old_messages, self.llm)
                self._summary_cache[cache_key] = summary

            summary = self._summary_cache.get(cache_key, "")

            if summary:
                summary_msg = SystemMessage(content=summary)
                messages = [summary_msg] + list(recent_messages)

        return trim_messages(
            messages,
            max_tokens=self.max_tokens,
            strategy=self.strategy,
            include_system=self.include_system,
        )

    def _simple_summary(self, messages: list[MessageLike]) -> str:
        """Create a simple summary without LLM."""
        if not messages:
            return ""

        parts = []
        for msg in messages[-5:]:  # Last 5 messages only
            if isinstance(msg, BaseMessage):
                content = msg.content
            elif isinstance(msg, dict):
                content = msg.get("content", "")
            else:
                content = str(msg)

            if isinstance(content, str) and content:
                truncated = content[:200] + "..." if len(content) > 200 else content
                parts.append(truncated)

        return f"[Previous context: {len(messages)} messages]\n" + "\n".join(parts)

    def clear_cache(self, session_id: str | None = None):
        """Clear summary cache."""
        if session_id:
            self._summary_cache.pop(session_id, None)
        else:
            self._summary_cache.clear()


class SummarizationMiddleware:
    """
    Middleware for automatic conversation summarization.

    Integrates with the RAG middleware system to automatically
    manage conversation history.

    Usage:
        middleware = SummarizationMiddleware(max_tokens=4000)

        @middleware.wrap
        async def my_function(state):
            ...
    """

    def __init__(
        self,
        max_tokens: int = SHORT_TERM_MEMORY_MAX_TOKENS,
        summarization_threshold: int = SUMMARIZATION_THRESHOLD,
        history_key: str = "history",
        messages_key: str = "messages",
        llm: Any | None = None,
    ):
        """
        Initialize the summarization middleware.

        Args:
            max_tokens: Maximum tokens for history
            summarization_threshold: Messages before summarization
            history_key: State key for chat history
            messages_key: State key for messages
            llm: Language model for summarization
        """
        self.manager = ShortTermMemoryManager(
            max_tokens=max_tokens,
            summarization_threshold=summarization_threshold,
            llm=llm,
        )
        self.history_key = history_key
        self.messages_key = messages_key

    def before_model(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Pre-process state before model invocation.

        Trims history/messages to fit within token limits.
        """
        new_state = dict(state)

        # Process history
        if self.history_key in new_state:
            history = new_state[self.history_key]
            if isinstance(history, list) and history:
                new_state[self.history_key] = self.manager.process(history)

        # Process messages
        if self.messages_key in new_state:
            messages = new_state[self.messages_key]
            if isinstance(messages, list) and messages:
                new_state[self.messages_key] = self.manager.process(messages)

        return new_state

    async def abefore_model(self, state: dict[str, Any]) -> dict[str, Any]:
        """Async version of before_model."""
        new_state = dict(state)

        if self.history_key in new_state:
            history = new_state[self.history_key]
            if isinstance(history, list) and history:
                new_state[self.history_key] = await self.manager.aprocess(history)

        if self.messages_key in new_state:
            messages = new_state[self.messages_key]
            if isinstance(messages, list) and messages:
                new_state[self.messages_key] = await self.manager.aprocess(messages)

        return new_state

    def wrap(self, func: Callable) -> Callable:
        """
        Decorator to wrap a function with summarization middleware.
        """
        @wraps(func)
        async def async_wrapper(state: dict[str, Any], *args, **kwargs):
            state = await self.abefore_model(state)
            return await func(state, *args, **kwargs)

        @wraps(func)
        def sync_wrapper(state: dict[str, Any], *args, **kwargs):
            state = self.before_model(state)
            return func(state, *args, **kwargs)

        # Check if function is async
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper


def delete_old_messages(
    state: dict[str, Any],
    max_messages: int = CHAT_HISTORY_WINDOW,
    history_key: str = "history",
) -> dict[str, Any]:
    """
    Delete old messages from state, keeping only recent ones.

    This is a simple cleanup function that can be used as an
    @after_model middleware hook.

    Args:
        state: Current state
        max_messages: Maximum messages to keep
        history_key: State key for history

    Returns:
        Updated state with trimmed history
    """
    if history_key not in state:
        return state

    history = state[history_key]
    if not isinstance(history, list):
        return state

    if len(history) <= max_messages:
        return state

    new_state = dict(state)
    new_state[history_key] = history[-max_messages:]
    return new_state
