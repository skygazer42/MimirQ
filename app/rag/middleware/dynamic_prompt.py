"""
Dynamic Prompt Middleware

Provides dynamic prompt injection capabilities:
- Time/date injection
- Context injection
- Style guide injection
- User preference injection
"""

from collections.abc import Callable
from datetime import datetime
from functools import wraps
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("rag.middleware.dynamic_prompt")


class ContextInjector:
    """
    Injects additional context into prompts.

    This can include:
    - File contents
    - Database records
    - External API data
    - User-specific context
    """

    def __init__(
        self,
        context_sources: dict[str, Callable] | None = None,
    ):
        """
        Args:
            context_sources: Dict of source_name -> callable that returns context string
        """
        self.context_sources = context_sources or {}

    def add_source(self, name: str, source: Callable) -> None:
        """Add a context source."""
        self.context_sources[name] = source

    def get_context(self, source_names: list[str] | None = None) -> str:
        """Get context from specified sources (or all if not specified)."""
        sources = source_names or list(self.context_sources.keys())
        parts = []

        for name in sources:
            if name not in self.context_sources:
                continue

            try:
                context = self.context_sources[name]()
                if context:
                    parts.append(f"[{name}]\n{context}")
            except Exception as e:
                logger.warning(f"Context source '{name}' failed: {e}")

        return "\n\n".join(parts)

    def __call__(self, func: Callable) -> Callable:
        """Wrap a function to inject context."""

        @wraps(func)
        def wrapper(state: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
            # Get requested context sources
            sources = state.get("context_sources", None)
            context = self.get_context(sources)

            if context:
                existing = state.get("additional_context", "")
                state["additional_context"] = f"{existing}\n\n{context}".strip()

            return func(state, *args, **kwargs)

        return wrapper


class StyleInjector:
    """
    Injects style guidelines into prompts.

    Supports:
    - Global style guides
    - Tenant-specific styles
    - User-specific preferences
    """

    DEFAULT_STYLES = {
        "professional": "Respond in a professional, formal tone. Use clear and precise language.",
        "casual": "Respond in a friendly, conversational tone. Keep it simple and approachable.",
        "technical": "Respond with technical precision. Include relevant technical details and terminology.",
        "concise": "Be brief and to the point. Avoid unnecessary elaboration.",
        "detailed": "Provide comprehensive, detailed responses with examples where helpful.",
    }

    def __init__(
        self,
        styles: dict[str, str] | None = None,
        default_style: str = "professional",
    ):
        self.styles = {**self.DEFAULT_STYLES, **(styles or {})}
        self.default_style = default_style

    def get_style_prompt(self, style_name: str | None = None) -> str:
        """Get the style prompt for a given style name."""
        name = style_name or self.default_style
        return self.styles.get(name, self.styles.get(self.default_style, ""))

    def __call__(self, func: Callable) -> Callable:
        """Wrap a function to inject style."""

        @wraps(func)
        def wrapper(state: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
            style = state.get("response_style")
            if style:
                style_prompt = self.get_style_prompt(style)
                if style_prompt:
                    existing = state.get("style_instructions", "")
                    state["style_instructions"] = f"{existing}\n\n{style_prompt}".strip()

            return func(state, *args, **kwargs)

        return wrapper


class TimeInjector:
    """
    Injects current time/date information into prompts.

    Useful for:
    - Time-sensitive queries
    - Date-aware responses
    - Scheduling-related tasks
    """

    def __init__(
        self,
        format_string: str = "%Y-%m-%d %H:%M:%S %Z",
        include_day_of_week: bool = True,
    ):
        self.format_string = format_string
        self.include_day_of_week = include_day_of_week

    def get_time_context(self) -> str:
        """Get the current time context string."""
        now = datetime.now()
        time_str = now.strftime(self.format_string)

        parts = [f"Current date and time: {time_str}"]

        if self.include_day_of_week:
            day = now.strftime("%A")
            parts.append(f"Day of week: {day}")

        return "\n".join(parts)

    def __call__(self, func: Callable) -> Callable:
        """Wrap a function to inject time context."""

        @wraps(func)
        def wrapper(state: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
            # Only inject if time context is requested or query seems time-related
            inject_time = state.get("inject_time_context", False)
            query = state.get("question", "").lower()

            time_keywords = ["today", "now", "current", "时间", "日期", "今天", "现在"]
            if inject_time or any(kw in query for kw in time_keywords):
                time_context = self.get_time_context()
                existing = state.get("time_context", "")
                state["time_context"] = f"{existing}\n\n{time_context}".strip()

            return func(state, *args, **kwargs)

        return wrapper


class DynamicPromptMiddleware:
    """
    Comprehensive dynamic prompt middleware.

    Combines:
    - Context injection
    - Style injection
    - Time injection
    - Custom prompt transformations
    """

    def __init__(
        self,
        enabled: bool = True,
        inject_time: bool = True,
        default_style: str | None = None,
        context_sources: dict[str, Callable] | None = None,
    ):
        self.enabled = enabled
        self.inject_time = inject_time
        self.default_style = default_style

        self.context_injector = ContextInjector(context_sources)
        self.style_injector = StyleInjector(default_style=default_style or "professional")
        self.time_injector = TimeInjector()

        self._custom_transformers: list[Callable] = []

    def add_transformer(self, transformer: Callable) -> None:
        """Add a custom prompt transformer."""
        self._custom_transformers.append(transformer)

    def transform(self, state: dict[str, Any]) -> dict[str, Any]:
        """Apply all prompt transformations."""
        if not self.enabled:
            return state

        # Apply time injection
        if self.inject_time:
            state = self.time_injector(lambda s: s)(state)

        # Apply style injection
        state = self.style_injector(lambda s: s)(state)

        # Apply context injection
        state = self.context_injector(lambda s: s)(state)

        # Apply custom transformers
        for transformer in self._custom_transformers:
            try:
                state = transformer(state)
            except Exception as e:
                logger.warning(f"Custom transformer failed: {e}")

        # Build final system prompt additions
        additions = []

        if state.get("time_context"):
            additions.append(state["time_context"])

        if state.get("style_instructions"):
            additions.append(state["style_instructions"])

        if state.get("additional_context"):
            additions.append(state["additional_context"])

        if additions:
            system_additions = "\n\n".join(additions)
            existing_system = state.get("system_prompt_additions", "")
            state["system_prompt_additions"] = f"{existing_system}\n\n{system_additions}".strip()

        return state

    def __call__(self, func: Callable) -> Callable:
        """Wrap a function with dynamic prompt injection."""

        @wraps(func)
        def wrapper(state: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
            state = self.transform(state)
            return func(state, *args, **kwargs)

        return wrapper


# Pre-configured middleware instances
def create_dynamic_prompt_middleware(
    enabled: bool | None = None,
    inject_time: bool | None = None,
    default_style: str | None = None,
) -> DynamicPromptMiddleware:
    """Create a dynamic prompt middleware with settings from config."""
    return DynamicPromptMiddleware(
        enabled=enabled if enabled is not None else bool(
            getattr(settings, "DYNAMIC_PROMPT_ENABLED", True)
        ),
        inject_time=inject_time if inject_time is not None else bool(
            getattr(settings, "DYNAMIC_PROMPT_INJECT_TIME", True)
        ),
        default_style=default_style or getattr(settings, "DEFAULT_RESPONSE_STYLE", None),
    )


# Decorator for adding time context
def inject_time_context(func: Callable) -> Callable:
    """Decorator to inject time context into prompts."""
    injector = TimeInjector()
    return injector(func)


# Decorator for adding style
def inject_style(style: str) -> Callable:
    """Decorator factory to inject a specific style."""
    def decorator(func: Callable) -> Callable:
        injector = StyleInjector(default_style=style)

        @wraps(func)
        def wrapper(state: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
            if not state.get("response_style"):
                state["response_style"] = style
            return injector(func)(state, *args, **kwargs)

        return wrapper
    return decorator
