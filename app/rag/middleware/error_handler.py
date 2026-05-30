"""
Error Handler Middleware

Provides error handling, retry, and fallback mechanisms for LLM calls.
"""


import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("rag.middleware.error_handler")


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    retryable_exceptions: tuple = ()


class ErrorHandlerMiddleware:
    """
    Error handling middleware that provides:
    - Automatic retry with exponential backoff
    - Fallback to alternative models
    - Error logging and metrics
    """

    def __init__(
        self,
        max_retries: int = 3,
        fallback_model: str | None = None,
        retryable_errors: list[type[Exception]] | None = None,
    ):
        self.max_retries = max_retries
        self.fallback_model = fallback_model or getattr(settings, "LLM_MODEL_FAST", None)
        self.retryable_errors = tuple(retryable_errors or [
            ConnectionError,
            TimeoutError,
        ])

    def __call__(self, func: Callable) -> Callable:
        """Wrap a function with error handling."""

        @wraps(func)
        async def async_wrapper(state: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
            last_exception = None
            attempts = 0

            for attempt in range(self.max_retries + 1):
                attempts = attempt + 1
                try:
                    result = await func(state, *args, **kwargs)

                    # Add retry metrics
                    if "metrics" not in result:
                        result["metrics"] = {}
                    result["metrics"]["error_handler_attempts"] = attempts
                    result["metrics"]["error_handler_retries"] = max(0, attempts - 1)

                    return result

                except self.retryable_errors as e:
                    last_exception = e
                    logger.warning(
                        f"Attempt {attempts} failed with {type(e).__name__}: {e}"
                    )

                    if attempt < self.max_retries:
                        delay = min(
                            (2 ** attempt) * 1.0,
                            60.0
                        )
                        logger.info(f"Retrying in {delay:.1f}s...")
                        await asyncio.sleep(delay)

                        # Try fallback model on later attempts
                        if attempt >= 1 and self.fallback_model:
                            state["model_override"] = self.fallback_model
                            logger.info(f"Switching to fallback model: {self.fallback_model}")

                except Exception as e:
                    # Non-retryable error
                    logger.exception(f"Non-retryable error: {type(e).__name__}: {e}")
                    raise

            # All retries exhausted
            if last_exception:
                logger.error(f"All {self.max_retries + 1} attempts failed")
                raise last_exception

            return state

        @wraps(func)
        def sync_wrapper(state: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
            last_exception = None
            attempts = 0

            for attempt in range(self.max_retries + 1):
                attempts = attempt + 1
                try:
                    result = func(state, *args, **kwargs)

                    if "metrics" not in result:
                        result["metrics"] = {}
                    result["metrics"]["error_handler_attempts"] = attempts
                    result["metrics"]["error_handler_retries"] = max(0, attempts - 1)

                    return result

                except self.retryable_errors as e:
                    last_exception = e
                    logger.warning(f"Attempt {attempts} failed: {e}")

                    if attempt < self.max_retries:
                        delay = min((2 ** attempt) * 1.0, 60.0)
                        time.sleep(delay)

                        if attempt >= 1 and self.fallback_model:
                            state["model_override"] = self.fallback_model

            if last_exception:
                raise last_exception

            return state

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper


class RateLimitHandler:
    """
    Specialized handler for rate limit errors.

    Implements adaptive backoff and model switching.
    """

    def __init__(
        self,
        initial_delay: float = 1.0,
        max_delay: float = 120.0,
        fallback_models: list[str] | None = None,
    ):
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.fallback_models = fallback_models or []
        self._current_delay = initial_delay
        self._model_index = 0

    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(state: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
            try:
                result = await func(state, *args, **kwargs)
                # Reset delay on success
                self._current_delay = self.initial_delay
                return result

            except Exception as e:
                error_str = str(e).lower()
                if "rate limit" in error_str or "429" in error_str:
                    logger.warning(f"Rate limit hit, waiting {self._current_delay:.1f}s")
                    await asyncio.sleep(self._current_delay)

                    # Exponential backoff
                    self._current_delay = min(
                        self._current_delay * 2,
                        self.max_delay
                    )

                    # Try fallback model
                    if self.fallback_models and self._model_index < len(self.fallback_models):
                        fallback = self.fallback_models[self._model_index]
                        state["model_override"] = fallback
                        self._model_index += 1
                        logger.info(f"Switching to fallback model: {fallback}")

                    # Retry once with backoff
                    return await func(state, *args, **kwargs)

                raise

        return wrapper


class TimeoutHandler:
    """
    Handler for timeout errors.

    Implements timeout with fallback to simpler models.
    """

    def __init__(
        self,
        timeout: float = 60.0,
        fallback_model: str | None = None,
    ):
        self.timeout = timeout
        self.fallback_model = fallback_model

    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(state: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
            try:
                return await asyncio.wait_for(
                    func(state, *args, **kwargs),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"Request timed out after {self.timeout}s")

                if self.fallback_model:
                    state["model_override"] = self.fallback_model
                    logger.info(f"Retrying with fallback model: {self.fallback_model}")
                    return await func(state, *args, **kwargs)

                raise

        return wrapper


class FallbackModelHandler:
    """
    Handler that automatically switches to fallback models on failure.
    """

    def __init__(
        self,
        fallback_chain: list[str] | None = None,
    ):
        """
        Args:
            fallback_chain: List of model names to try in order.
                          If None, uses settings.LLM_MODEL_FAST as fallback.
        """
        self.fallback_chain = fallback_chain or []
        if not self.fallback_chain:
            fast = getattr(settings, "LLM_MODEL_FAST", None)
            if fast:
                self.fallback_chain.append(fast)

    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(state: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
            last_error = None

            # Try primary model first
            try:
                return await func(state, *args, **kwargs)
            except Exception as e:
                last_error = e
                logger.warning(f"Primary model failed: {e}")

            # Try fallback models
            for fallback in self.fallback_chain:
                try:
                    state["model_override"] = fallback
                    logger.info(f"Trying fallback model: {fallback}")
                    result = await func(state, *args, **kwargs)

                    if "metrics" not in result:
                        result["metrics"] = {}
                    result["metrics"]["used_fallback_model"] = fallback

                    return result
                except Exception as e:
                    last_error = e
                    logger.warning(f"Fallback model {fallback} failed: {e}")

            # All models failed
            if last_error:
                raise last_error

            return state

        return wrapper


# Convenience function to create a standard error handler
def create_error_handler(
    max_retries: int | None = None,
    fallback_model: str | None = None,
) -> ErrorHandlerMiddleware:
    """Create a standard error handler with sensible defaults."""
    return ErrorHandlerMiddleware(
        max_retries=max_retries or getattr(settings, "LLM_MAX_RETRIES", 3),
        fallback_model=fallback_model or getattr(settings, "LLM_MODEL_FAST", None),
    )
