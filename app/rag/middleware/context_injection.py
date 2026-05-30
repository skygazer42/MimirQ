"""
Context engineering middleware for dynamic prompt assembly.

Provides context injection capabilities including:
- File content injection
- Style guide injection
- Time/date context
- User preferences injection
- RAG context formatting

Usage:
    from app.rag.middleware.context_injection import ContextInjectionMiddleware

    middleware = ContextInjectionMiddleware()
    state = await middleware.before_model(state)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("rag.middleware.context_injection")


# ============================================================================
# Configuration
# ============================================================================

INJECT_TIME_CONTEXT = getattr(settings, "MIDDLEWARE_INJECT_TIME_CONTEXT", True)
DEFAULT_RESPONSE_STYLE = getattr(settings, "MIDDLEWARE_DEFAULT_RESPONSE_STYLE", "")


# ============================================================================
# Context Providers
# ============================================================================


@dataclass
class ContextItem:
    """A single context item to inject."""
    content: str
    source: str
    priority: int = 0  # Higher priority = injected first
    category: str = "general"
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseContextProvider(ABC):
    """Base class for context providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        pass

    @property
    def priority(self) -> int:
        """Provider priority (higher = injected first)."""
        return 0

    @abstractmethod
    async def get_context(
        self,
        state: dict[str, Any],
        **kwargs,
    ) -> list[ContextItem]:
        """
        Get context items to inject.

        Args:
            state: Current state
            **kwargs: Additional arguments

        Returns:
            List of context items
        """
        pass


class TimeContextProvider(BaseContextProvider):
    """Provides current time/date context."""

    @property
    def name(self) -> str:
        return "time"

    @property
    def priority(self) -> int:
        return 100  # High priority

    async def get_context(
        self,
        state: dict[str, Any],
        **kwargs,
    ) -> list[ContextItem]:
        if not INJECT_TIME_CONTEXT:
            return []

        now = datetime.now(UTC)
        time_info = now.strftime("%Y-%m-%d %H:%M:%S")
        weekday = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][now.weekday()]

        return [
            ContextItem(
                content=f"Current time: {time_info} ({weekday})",
                source="system",
                priority=100,
                category="time",
            )
        ]


class StyleGuideProvider(BaseContextProvider):
    """Provides response style guidelines."""

    STYLE_GUIDES = {
        "professional": "Please respond in a professional, formal language style. Avoid colloquial expressions and use standard written language.",
        "casual": "Please respond in a friendly, relaxed language style. Feel free to use conversational expressions and maintain approachability.",
        "technical": "Please respond with technical precision. Include necessary technical details and professional terminology.",
        "concise": "Please respond concisely and clearly. Avoid redundant information and provide the core answer directly.",
        "detailed": "Please respond in detail and comprehensively. Include background information, examples, and relevant details.",
    }

    @property
    def name(self) -> str:
        return "style_guide"

    @property
    def priority(self) -> int:
        return 90

    async def get_context(
        self,
        state: dict[str, Any],
        **kwargs,
    ) -> list[ContextItem]:
        # Check for style in state or use default
        style = state.get("response_style") or DEFAULT_RESPONSE_STYLE
        if not style or style not in self.STYLE_GUIDES:
            return []

        return [
            ContextItem(
                content=self.STYLE_GUIDES[style],
                source="style_guide",
                priority=90,
                category="style",
                metadata={"style": style},
            )
        ]


class FileContentProvider(BaseContextProvider):
    """Provides file content injection."""

    def __init__(
        self,
        base_path: str | None = None,
        allowed_extensions: list[str] | None = None,
        max_file_size: int = 100_000,  # 100KB
    ):
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.allowed_extensions = allowed_extensions or [".txt", ".md", ".py", ".json", ".yaml", ".yml"]
        self.max_file_size = max_file_size

    @property
    def name(self) -> str:
        return "file_content"

    @property
    def priority(self) -> int:
        return 50

    async def get_context(
        self,
        state: dict[str, Any],
        **kwargs,
    ) -> list[ContextItem]:
        file_paths = state.get("inject_files", [])
        if not file_paths:
            return []

        items = []
        for file_path in file_paths:
            try:
                content = self._read_file(file_path)
                if content:
                    items.append(ContextItem(
                        content=f"[File: {file_path}]\n{content}",
                        source=file_path,
                        priority=50,
                        category="file",
                        metadata={"path": file_path},
                    ))
            except Exception as e:
                logger.warning("Failed to read file %s: %s", file_path, e)

        return items

    def _read_file(self, file_path: str) -> str | None:
        """Read file content with safety checks."""
        path = Path(file_path)

        # Resolve relative paths
        if not path.is_absolute():
            path = self.base_path / path

        # Safety checks
        if not path.exists():
            logger.warning("File not found: %s", path)
            return None

        if path.suffix not in self.allowed_extensions:
            logger.warning("File extension not allowed: %s", path.suffix)
            return None

        if path.stat().st_size > self.max_file_size:
            logger.warning("File too large: %s", path)
            return None

        try:
            return path.read_text(encoding="utf-8")
        except Exception as e:
            logger.exception("Failed to read file: %s", e)
            return None


class UserPreferencesProvider(BaseContextProvider):
    """Provides user preferences context."""

    @property
    def name(self) -> str:
        return "user_preferences"

    @property
    def priority(self) -> int:
        return 80

    async def get_context(
        self,
        state: dict[str, Any],
        **kwargs,
    ) -> list[ContextItem]:
        preferences = state.get("user_preferences", {})
        if not preferences:
            return []

        # Format preferences
        pref_lines = []
        if preferences.get("language"):
            pref_lines.append(f"User language preference: {preferences['language']}")
        if preferences.get("expertise_level"):
            pref_lines.append(f"User expertise level: {preferences['expertise_level']}")
        if preferences.get("industry"):
            pref_lines.append(f"User industry: {preferences['industry']}")
        if preferences.get("custom_instructions"):
            pref_lines.append(f"User custom instructions: {preferences['custom_instructions']}")

        if not pref_lines:
            return []

        return [
            ContextItem(
                content="\n".join(pref_lines),
                source="user_preferences",
                priority=80,
                category="user",
                metadata=preferences,
            )
        ]


class RAGContextProvider(BaseContextProvider):
    """Formats and provides RAG context."""

    def __init__(
        self,
        max_chars_per_chunk: int = 1500,
        max_total_chars: int = 12000,
    ):
        self.max_chars_per_chunk = max_chars_per_chunk
        self.max_total_chars = max_total_chars

    @property
    def name(self) -> str:
        return "rag_context"

    @property
    def priority(self) -> int:
        return 10  # Low priority, added last

    async def get_context(
        self,
        state: dict[str, Any],
        **kwargs,
    ) -> list[ContextItem]:
        documents = state.get("documents", [])
        if not documents:
            return []

        formatted_chunks = []
        total_chars = 0

        for i, doc in enumerate(documents, 1):
            # Handle both Document objects and dicts
            if hasattr(doc, "page_content"):
                content = doc.page_content
                metadata = getattr(doc, "metadata", {})
            else:
                content = doc.get("content", doc.get("page_content", ""))
                metadata = doc.get("metadata", {})

            # Truncate if needed
            if len(content) > self.max_chars_per_chunk:
                content = content[:self.max_chars_per_chunk] + "..."

            # Check total limit
            if total_chars + len(content) > self.max_total_chars:
                break

            # Format chunk
            source = metadata.get("source", "unknown")
            page = metadata.get("page", "")
            source_info = f"[{source}"
            if page:
                source_info += f", p.{page}"
            source_info += "]"

            formatted_chunks.append(f"--- Document chunk {i} {source_info} ---\n{content}")
            total_chars += len(content)

        if not formatted_chunks:
            return []

        return [
            ContextItem(
                content="\n\n".join(formatted_chunks),
                source="rag",
                priority=10,
                category="rag",
                metadata={"chunk_count": len(formatted_chunks)},
            )
        ]


class KnowledgeGraphProvider(BaseContextProvider):
    """Provides knowledge graph context."""

    def __init__(self, max_chars: int = 3000):
        self.max_chars = max_chars

    @property
    def name(self) -> str:
        return "knowledge_graph"

    @property
    def priority(self) -> int:
        return 20

    async def get_context(
        self,
        state: dict[str, Any],
        **kwargs,
    ) -> list[ContextItem]:
        kg_context = state.get("kg_context", "")
        if not kg_context:
            return []

        # Truncate if needed
        if len(kg_context) > self.max_chars:
            kg_context = kg_context[:self.max_chars] + "..."

        return [
            ContextItem(
                content=f"--- Knowledge graph context ---\n{kg_context}",
                source="knowledge_graph",
                priority=20,
                category="kg",
            )
        ]


# ============================================================================
# Context Injection Middleware
# ============================================================================


class ContextInjectionMiddleware:
    """
    Middleware for injecting context into prompts.

    Assembles context from multiple providers and injects
    it into the system message or user message.
    """

    def __init__(
        self,
        providers: list[BaseContextProvider] | None = None,
        inject_position: str = "system",  # system | user | both
    ):
        """
        Initialize the middleware.

        Args:
            providers: List of context providers
            inject_position: Where to inject context
        """
        self.providers = providers or self._default_providers()
        self.inject_position = inject_position

    def _default_providers(self) -> list[BaseContextProvider]:
        """Get default context providers."""
        return [
            TimeContextProvider(),
            StyleGuideProvider(),
            UserPreferencesProvider(),
            FileContentProvider(),
            KnowledgeGraphProvider(),
            RAGContextProvider(),
        ]

    def add_provider(self, provider: BaseContextProvider) -> "ContextInjectionMiddleware":
        """Add a context provider."""
        self.providers.append(provider)
        return self

    def remove_provider(self, name: str) -> "ContextInjectionMiddleware":
        """Remove a context provider by name."""
        self.providers = [p for p in self.providers if p.name != name]
        return self

    async def get_all_context(
        self,
        state: dict[str, Any],
        **kwargs,
    ) -> list[ContextItem]:
        """
        Gather context from all providers.

        Args:
            state: Current state
            **kwargs: Additional arguments

        Returns:
            Sorted list of context items
        """
        all_items = []

        for provider in self.providers:
            try:
                items = await provider.get_context(state, **kwargs)
                all_items.extend(items)
            except Exception as e:
                logger.exception("Context provider %s failed: %s", provider.name, e)

        # Sort by priority (descending)
        all_items.sort(key=lambda x: x.priority, reverse=True)

        return all_items

    def format_context(self, items: list[ContextItem]) -> str:
        """
        Format context items into a string.

        Args:
            items: Context items

        Returns:
            Formatted context string
        """
        if not items:
            return ""

        parts = []
        for item in items:
            parts.append(item.content)

        return "\n\n".join(parts)

    async def before_model(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Inject context before model invocation.

        Args:
            state: Current state

        Returns:
            Updated state with injected context
        """
        context_items = await self.get_all_context(state)
        if not context_items:
            return state

        context_str = self.format_context(context_items)

        # Get messages
        messages = state.get("messages", [])
        if not messages:
            return state

        # Inject based on position
        if self.inject_position in ("system", "both"):
            state = self._inject_to_system(state, context_str, messages)

        if self.inject_position in ("user", "both"):
            state = self._inject_to_user(state, context_str, messages)

        return state

    def _inject_to_system(
        self,
        state: dict[str, Any],
        context: str,
        messages: list[Any],
    ) -> dict[str, Any]:
        """Inject context into system message."""
        # Find or create system message
        has_system = False
        new_messages = []

        for msg in messages:
            if hasattr(msg, "type") and msg.type == "system":
                # Append context to existing system message
                new_content = msg.content + "\n\n" + context
                # Create new message with updated content
                msg_dict = {"type": "system", "content": new_content}
                new_messages.append(msg_dict)
                has_system = True
            elif isinstance(msg, dict) and msg.get("role") == "system":
                msg["content"] = msg["content"] + "\n\n" + context
                new_messages.append(msg)
                has_system = True
            else:
                new_messages.append(msg)

        if not has_system:
            # Insert system message at beginning
            system_msg = {"role": "system", "content": context}
            new_messages.insert(0, system_msg)

        state["messages"] = new_messages
        return state

    def _inject_to_user(
        self,
        state: dict[str, Any],
        context: str,
        messages: list[Any],
    ) -> dict[str, Any]:
        """Inject context into the last user message."""
        if not messages:
            return state

        new_messages = list(messages)

        # Find last user message
        for i in range(len(new_messages) - 1, -1, -1):
            msg = new_messages[i]
            if hasattr(msg, "type") and msg.type == "human":
                new_content = f"{context}\n\nUser question: {msg.content}"
                msg_dict = {"type": "human", "content": new_content}
                new_messages[i] = msg_dict
                break
            elif isinstance(msg, dict) and msg.get("role") == "user":
                msg["content"] = f"{context}\n\nUser question: {msg['content']}"
                break

        state["messages"] = new_messages
        return state


# ============================================================================
# Convenience Functions
# ============================================================================


def create_context_middleware(
    inject_time: bool = True,
    inject_style: bool = True,
    inject_user_prefs: bool = True,
    inject_files: bool = True,
    inject_kg: bool = True,
    inject_rag: bool = True,
    inject_position: str = "system",
) -> ContextInjectionMiddleware:
    """
    Create a context injection middleware with specified providers.

    Args:
        inject_time: Include time context
        inject_style: Include style guide
        inject_user_prefs: Include user preferences
        inject_files: Include file content
        inject_kg: Include knowledge graph
        inject_rag: Include RAG context
        inject_position: Where to inject

    Returns:
        Configured middleware
    """
    providers = []

    if inject_time:
        providers.append(TimeContextProvider())
    if inject_style:
        providers.append(StyleGuideProvider())
    if inject_user_prefs:
        providers.append(UserPreferencesProvider())
    if inject_files:
        providers.append(FileContentProvider())
    if inject_kg:
        providers.append(KnowledgeGraphProvider())
    if inject_rag:
        providers.append(RAGContextProvider())

    return ContextInjectionMiddleware(
        providers=providers,
        inject_position=inject_position,
    )


async def inject_context(
    state: dict[str, Any],
    middleware: ContextInjectionMiddleware | None = None,
) -> dict[str, Any]:
    """
    Inject context into state.

    Args:
        state: Current state
        middleware: Optional middleware instance

    Returns:
        Updated state
    """
    if middleware is None:
        middleware = ContextInjectionMiddleware()

    return await middleware.before_model(state)
