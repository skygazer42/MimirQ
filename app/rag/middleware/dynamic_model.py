"""
Dynamic Model Middleware

Provides intelligent model routing based on query complexity,
token count, and other factors.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("rag.middleware.dynamic_model")


@dataclass
class ModelConfig:
    """Configuration for a model."""
    name: str
    max_tokens: int = 4096
    supports_streaming: bool = True
    supports_functions: bool = True
    cost_per_1k_tokens: float = 0.0
    priority: int = 100  # Lower = higher priority


class ComplexityAnalyzer:
    """
    Analyzes query complexity to help with model routing.

    Factors considered:
    - Query length
    - Presence of complex reasoning patterns
    - Mathematical expressions
    - Code-related content
    - Multi-step instructions
    """

    # Patterns indicating complex queries
    COMPLEX_PATTERNS = [
        r'\b(analyze|compare|contrast|evaluate|synthesize)\b',
        r'\b(step[- ]by[- ]step|first.*then|multiple|several)\b',
        r'\b(calculate|compute|solve|prove|derive)\b',
        r'\b(code|function|algorithm|implement|debug)\b',
        r'\b(because|therefore|however|although|despite)\b',
        r'\$.*\$',  # Math expressions
        r'```',  # Code blocks
        r'\d+\.\s+',  # Numbered lists
    ]

    def __init__(
        self,
        length_threshold: int = 200,
        history_weight: float = 0.3,
    ):
        self.length_threshold = length_threshold
        self.history_weight = history_weight
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.COMPLEX_PATTERNS
        ]

    def analyze(
        self,
        query: str,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[float, str]:
        """
        Analyze query complexity.

        Returns:
            Tuple of (complexity_score, reason)
            - complexity_score: 0.0 (simple) to 1.0 (complex)
            - reason: Explanation for the score
        """
        score = 0.0
        reasons = []

        # Length factor
        query_len = len(query)
        if query_len > self.length_threshold:
            length_factor = min(1.0, query_len / (self.length_threshold * 3))
            score += length_factor * 0.3
            reasons.append(f"long_query({query_len})")

        # Pattern matching
        pattern_matches = 0
        for pattern in self._compiled_patterns:
            if pattern.search(query):
                pattern_matches += 1

        if pattern_matches > 0:
            pattern_factor = min(1.0, pattern_matches / 3)
            score += pattern_factor * 0.4
            reasons.append(f"complex_patterns({pattern_matches})")

        # History factor
        if history:
            history_len = len(history)
            if history_len > 5:
                history_factor = min(1.0, history_len / 15)
                score += history_factor * self.history_weight
                reasons.append(f"long_history({history_len})")

        # Normalize score
        score = min(1.0, score)
        reason = ", ".join(reasons) if reasons else "simple_query"

        return score, reason


class ModelRouter:
    """
    Routes requests to appropriate models based on complexity.
    """

    def __init__(
        self,
        default_model: str | None = None,
        fast_model: str | None = None,
        heavy_model: str | None = None,
        complexity_threshold: float = 0.5,
    ):
        self.default_model = default_model or getattr(settings, "LLM_MODEL", "gpt-4-turbo")
        self.fast_model = fast_model or getattr(settings, "LLM_MODEL_FAST", None)
        self.heavy_model = heavy_model or getattr(settings, "LLM_MODEL_HEAVY", None)
        self.complexity_threshold = complexity_threshold
        self.analyzer = ComplexityAnalyzer()

    def route(
        self,
        query: str,
        history: list[dict[str, str]] | None = None,
        prefer_fast: bool = False,
        require_heavy: bool = False,
    ) -> tuple[str, str, str]:
        """
        Route to appropriate model.

        Returns:
            Tuple of (model_name, route_type, reason)
        """
        if require_heavy and self.heavy_model:
            return self.heavy_model, "heavy", "explicitly_required"

        if prefer_fast and self.fast_model:
            return self.fast_model, "fast", "preferred"

        complexity, reason = self.analyzer.analyze(query, history)

        if complexity >= self.complexity_threshold and self.heavy_model:
            return self.heavy_model, "heavy", reason
        elif complexity < 0.3 and self.fast_model:
            return self.fast_model, "fast", reason
        else:
            return self.default_model, "default", reason


class DynamicModelMiddleware:
    """
    Middleware that dynamically selects models based on request characteristics.

    This integrates with the existing RAG engine's model selection logic.
    """

    def __init__(
        self,
        enabled: bool = True,
        router: ModelRouter | None = None,
    ):
        self.enabled = enabled and bool(
            getattr(settings, "ENABLE_DYNAMIC_MODEL_ROUTING", False)
        )
        self.router = router or ModelRouter()

    def __call__(self, func: Callable) -> Callable:
        """Wrap a function with dynamic model selection."""

        @wraps(func)
        def wrapper(state: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
            if not self.enabled:
                return func(state, *args, **kwargs)

            # Skip if model is already overridden
            if state.get("model_override"):
                return func(state, *args, **kwargs)

            # Analyze and route
            query = state.get("question", "")
            history = state.get("history", [])
            prefer_fast = state.get("prefer_fast_model", False)
            require_heavy = state.get("require_heavy_model", False)

            model, route, reason = self.router.route(
                query,
                history=history,
                prefer_fast=prefer_fast,
                require_heavy=require_heavy,
            )

            # Set model override
            state["model_override"] = model
            state["model_route"] = route
            state["model_route_reason"] = reason

            logger.debug(
                f"Dynamic model routing: {route} -> {model} ({reason})"
            )

            result = func(state, *args, **kwargs)

            # Add routing info to metrics
            if isinstance(result, dict):
                if "metrics" not in result:
                    result["metrics"] = {}
                result["metrics"]["dynamic_model_route"] = route
                result["metrics"]["dynamic_model_used"] = model
                result["metrics"]["dynamic_model_reason"] = reason

            return result

        return wrapper

    def select_model(
        self,
        query: str,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[str, str, str]:
        """
        Select appropriate model for a query.

        Returns:
            Tuple of (model_name, route_type, reason)
        """
        return self.router.route(query, history)


# Convenience function to create the middleware
def create_dynamic_model_middleware(
    enabled: bool | None = None,
) -> DynamicModelMiddleware:
    """Create a dynamic model middleware with settings from config."""
    return DynamicModelMiddleware(
        enabled=enabled if enabled is not None else bool(
            getattr(settings, "ENABLE_DYNAMIC_MODEL_ROUTING", False)
        )
    )
