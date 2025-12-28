"""
Middleware Base Module

Provides the core infrastructure for the three-layer middleware system:
- before_model: Pre-processing hooks
- after_model: Post-processing hooks
- wrap_model_call: Wrapping hooks
- dynamic_prompt: Dynamic prompt injection
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

logger = logging.getLogger(__name__)

# Type aliases
StateDict = Dict[str, Any]
MiddlewareFunc = Callable[[StateDict], StateDict]
AsyncMiddlewareFunc = Callable[[StateDict], "asyncio.Future[StateDict]"]
WrapperFunc = Callable[[Callable], Callable]


class MiddlewarePhase(str, Enum):
    """Middleware execution phases."""
    BEFORE_MODEL = "before_model"
    AFTER_MODEL = "after_model"
    WRAP_MODEL = "wrap_model"
    DYNAMIC_PROMPT = "dynamic_prompt"


@dataclass
class MiddlewareConfig:
    """Configuration for a middleware."""
    name: str
    phase: MiddlewarePhase
    priority: int = 100  # Lower = earlier execution
    enabled: bool = True
    async_mode: bool = False


class MiddlewareRegistry:
    """
    Global registry for middlewares.

    Middlewares are registered per phase and executed in priority order.
    """

    _instance: Optional["MiddlewareRegistry"] = None

    def __new__(cls) -> "MiddlewareRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._middlewares: Dict[MiddlewarePhase, List[tuple]] = {
                phase: [] for phase in MiddlewarePhase
            }
        return cls._instance

    @classmethod
    def get_instance(cls) -> "MiddlewareRegistry":
        return cls()

    def register(
        self,
        func: Callable,
        phase: MiddlewarePhase,
        priority: int = 100,
        name: Optional[str] = None,
    ) -> None:
        """Register a middleware function."""
        name = name or func.__name__
        self._middlewares[phase].append((priority, name, func))
        self._middlewares[phase].sort(key=lambda x: x[0])
        logger.debug(f"Registered middleware '{name}' for phase {phase.value}")

    def get_middlewares(self, phase: MiddlewarePhase) -> List[Callable]:
        """Get all middlewares for a phase, sorted by priority."""
        return [func for _, _, func in self._middlewares[phase]]

    def clear(self, phase: Optional[MiddlewarePhase] = None) -> None:
        """Clear registered middlewares."""
        if phase:
            self._middlewares[phase] = []
        else:
            for p in MiddlewarePhase:
                self._middlewares[p] = []


# Global registry instance
_registry = MiddlewareRegistry()


def before_model(
    func: Optional[Callable] = None,
    *,
    priority: int = 100,
    name: Optional[str] = None,
) -> Callable:
    """
    Decorator for pre-model hooks.

    The decorated function receives the state dict and must return
    the (possibly modified) state dict.

    Usage:
        @before_model
        def inject_context(state):
            state["messages"].insert(0, SystemMessage(...))
            return state

        @before_model(priority=50)  # Higher priority (runs earlier)
        def validate_input(state):
            if not state.get("question"):
                raise ValueError("Question is required")
            return state
    """
    def decorator(f: Callable) -> Callable:
        _registry.register(f, MiddlewarePhase.BEFORE_MODEL, priority, name)

        @wraps(f)
        def wrapper(state: StateDict) -> StateDict:
            return f(state)

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def after_model(
    func: Optional[Callable] = None,
    *,
    priority: int = 100,
    name: Optional[str] = None,
) -> Callable:
    """
    Decorator for post-model hooks.

    The decorated function receives the state dict (with response)
    and must return the (possibly modified) state dict.

    Usage:
        @after_model
        def log_response(state):
            logger.info(f"Answer: {state.get('answer', '')[:100]}")
            return state

        @after_model(priority=50)
        def validate_output(state):
            if not state.get("answer"):
                state["answer"] = "I could not generate a response."
            return state
    """
    def decorator(f: Callable) -> Callable:
        _registry.register(f, MiddlewarePhase.AFTER_MODEL, priority, name)

        @wraps(f)
        def wrapper(state: StateDict) -> StateDict:
            return f(state)

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def wrap_model_call(
    func: Optional[Callable] = None,
    *,
    priority: int = 100,
    name: Optional[str] = None,
) -> Callable:
    """
    Decorator for wrapping model calls.

    The decorated function should be a wrapper factory that takes the
    original function and returns a wrapped version.

    Usage:
        @wrap_model_call
        def error_handler(func):
            async def wrapper(state, *args, **kwargs):
                try:
                    return await func(state, *args, **kwargs)
                except RateLimitError:
                    state["model"] = "fallback_model"
                    return await func(state, *args, **kwargs)
            return wrapper
    """
    def decorator(f: Callable) -> Callable:
        _registry.register(f, MiddlewarePhase.WRAP_MODEL, priority, name)
        return f

    if func is not None:
        return decorator(func)
    return decorator


def dynamic_prompt(
    func: Optional[Callable] = None,
    *,
    priority: int = 100,
    name: Optional[str] = None,
) -> Callable:
    """
    Decorator for dynamic prompt injection.

    The decorated function receives the state dict and should modify
    the prompt-related fields (messages, system_prompt, etc.).

    Usage:
        @dynamic_prompt
        def inject_time(state):
            from datetime import datetime
            time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            system = f"Current time: {time_str}\n\n"
            state["system_prompt"] = system + state.get("system_prompt", "")
            return state
    """
    def decorator(f: Callable) -> Callable:
        _registry.register(f, MiddlewarePhase.DYNAMIC_PROMPT, priority, name)

        @wraps(f)
        def wrapper(state: StateDict) -> StateDict:
            return f(state)

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


class MiddlewareChain:
    """
    Chain of middlewares that can be applied to a state.

    Usage:
        chain = MiddlewareChain()
        chain.add(before_func_1)
        chain.add(before_func_2)

        state = chain.run_before(state)
        # ... model call ...
        state = chain.run_after(state)
    """

    def __init__(self, registry: Optional[MiddlewareRegistry] = None):
        self._registry = registry or _registry
        self._custom_before: List[Callable] = []
        self._custom_after: List[Callable] = []
        self._custom_wrappers: List[Callable] = []

    def add_before(self, func: Callable) -> "MiddlewareChain":
        """Add a before-model middleware."""
        self._custom_before.append(func)
        return self

    def add_after(self, func: Callable) -> "MiddlewareChain":
        """Add an after-model middleware."""
        self._custom_after.append(func)
        return self

    def add_wrapper(self, wrapper: Callable) -> "MiddlewareChain":
        """Add a model call wrapper."""
        self._custom_wrappers.append(wrapper)
        return self

    def run_before(self, state: StateDict) -> StateDict:
        """Run all before-model middlewares."""
        # Run dynamic prompts first
        for func in self._registry.get_middlewares(MiddlewarePhase.DYNAMIC_PROMPT):
            try:
                state = func(state)
            except Exception as e:
                logger.warning(f"Dynamic prompt middleware failed: {e}")

        # Run before-model middlewares
        for func in self._registry.get_middlewares(MiddlewarePhase.BEFORE_MODEL):
            try:
                state = func(state)
            except Exception as e:
                logger.warning(f"Before-model middleware failed: {e}")

        # Run custom before middlewares
        for func in self._custom_before:
            try:
                state = func(state)
            except Exception as e:
                logger.warning(f"Custom before middleware failed: {e}")

        return state

    def run_after(self, state: StateDict) -> StateDict:
        """Run all after-model middlewares."""
        # Run registered after-model middlewares
        for func in self._registry.get_middlewares(MiddlewarePhase.AFTER_MODEL):
            try:
                state = func(state)
            except Exception as e:
                logger.warning(f"After-model middleware failed: {e}")

        # Run custom after middlewares
        for func in self._custom_after:
            try:
                state = func(state)
            except Exception as e:
                logger.warning(f"Custom after middleware failed: {e}")

        return state

    def wrap_call(self, func: Callable) -> Callable:
        """Wrap a function with all registered wrappers."""
        wrapped = func

        # Apply registered wrappers
        for wrapper in self._registry.get_middlewares(MiddlewarePhase.WRAP_MODEL):
            try:
                wrapped = wrapper(wrapped)
            except Exception as e:
                logger.warning(f"Wrap-model middleware failed: {e}")

        # Apply custom wrappers
        for wrapper in self._custom_wrappers:
            try:
                wrapped = wrapper(wrapped)
            except Exception as e:
                logger.warning(f"Custom wrapper failed: {e}")

        return wrapped


def apply_middlewares(
    func: Callable,
    *,
    before: Optional[List[Callable]] = None,
    after: Optional[List[Callable]] = None,
    wrappers: Optional[List[Callable]] = None,
) -> Callable:
    """
    Apply middlewares to a function.

    Usage:
        @apply_middlewares(
            before=[validate_input, inject_context],
            after=[log_response],
            wrappers=[error_handler],
        )
        async def generate(state):
            ...
    """
    chain = MiddlewareChain()

    for f in (before or []):
        chain.add_before(f)

    for f in (after or []):
        chain.add_after(f)

    for w in (wrappers or []):
        chain.add_wrapper(w)

    @wraps(func)
    async def async_wrapper(state: StateDict, *args, **kwargs) -> StateDict:
        state = chain.run_before(state)
        wrapped_func = chain.wrap_call(func)

        if asyncio.iscoroutinefunction(wrapped_func):
            state = await wrapped_func(state, *args, **kwargs)
        else:
            state = wrapped_func(state, *args, **kwargs)

        state = chain.run_after(state)
        return state

    @wraps(func)
    def sync_wrapper(state: StateDict, *args, **kwargs) -> StateDict:
        state = chain.run_before(state)
        wrapped_func = chain.wrap_call(func)
        state = wrapped_func(state, *args, **kwargs)
        state = chain.run_after(state)
        return state

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


# Convenience function to get the global registry
def get_middleware_registry() -> MiddlewareRegistry:
    """Get the global middleware registry."""
    return _registry
