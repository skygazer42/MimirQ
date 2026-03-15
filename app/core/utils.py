"""
Core utility functions.

Provides common data conversion and validation helpers.
"""

import os
from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel

from .constants import ProxyEnvKeys

T = TypeVar("T", bound=BaseModel)


# =============================================================================
# UUID conversion
# =============================================================================

def to_uuid(value: Any) -> UUID:
    """
    Safely convert a value to UUID.

    Args:
        value: Value to convert (UUID, string, or other).

    Returns:
        UUID object.

    Raises:
        ValueError: If conversion fails.

    Example:
        >>> to_uuid("123e4567-e89b-12d3-a456-426614174000")
        UUID('123e4567-e89b-12d3-a456-426614174000')
        >>> to_uuid(some_uuid_object)
        UUID('...')
    """
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def to_uuid_or_none(value: Any) -> UUID | None:
    """
    Safely convert to UUID, return None on failure.

    Args:
        value: Value to convert.

    Returns:
        UUID object or None.
    """
    if value is None:
        return None
    try:
        return to_uuid(value)
    except (ValueError, AttributeError):
        return None


def uuid_list(values: list[Any]) -> list[UUID]:
    """
    Convert list values to a list of UUIDs.

    Args:
        values: List of values.

    Returns:
        List of UUIDs.
    """
    return [to_uuid(v) for v in values]


# =============================================================================
# Pydantic model conversion
# =============================================================================

def models_to_dicts(models: list[T]) -> list[dict[str, Any]]:
    """
    Convert a list of Pydantic models to a list of dicts.

    Args:
        models: List of Pydantic models.

    Returns:
        List of dicts.

    Example:
        >>> messages = [MessageSchema(...), MessageSchema(...)]
        >>> models_to_dicts(messages)
        [{'role': 'user', ...}, {'role': 'assistant', ...}]
    """
    return [m.model_dump() for m in models]


def model_to_dict(model: T, **kwargs) -> dict[str, Any]:
    """
    Convert a Pydantic model to dict.

    Args:
        model: Pydantic model.
        **kwargs: Arguments passed to model_dump.

    Returns:
        Dict output.
    """
    return model.model_dump(**kwargs)


# =============================================================================
# Proxy configuration
# =============================================================================

def get_proxy_url() -> str | None:
    """
    Get proxy URL.

    Checks proxy env vars by priority and returns the first match.

    Returns:
        Proxy URL or None.

    Example:
        >>> os.environ["HTTPS_PROXY"] = "http://proxy:8080"
        >>> get_proxy_url()
        'http://proxy:8080'
    """
    for key in ProxyEnvKeys.KEYS:
        value = os.getenv(key)
        if value:
            return value
    return None


def has_proxy_configured() -> bool:
    """
    Check whether a proxy is configured.

    Returns:
        Whether a proxy is configured.
    """
    return get_proxy_url() is not None


# =============================================================================
# String utilities
# =============================================================================

def truncate_string(s: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate a string to a maximum length.

    Args:
        s: Original string.
        max_length: Maximum length.
        suffix: Suffix appended after truncation.

    Returns:
        Truncated string.
    """
    if len(s) <= max_length:
        return s
    return s[:max_length - len(suffix)] + suffix


def safe_str(value: Any, default: str = "") -> str:
    """
    Safely convert a value to string.

    Args:
        value: Value to convert.
        default: Default if value is None.

    Returns:
        String value.
    """
    if value is None:
        return default
    return str(value)


# =============================================================================
# Config utilities
# =============================================================================

def parse_csv(value: str | None) -> list[str]:
    """
    Parse a comma-separated env/config value into a list of non-empty strings.

    - Strips whitespace around items
    - Ignores empty items
    - Preserves literal "*" when provided
    """
    if value is None:
        return []
    raw = str(value).strip()
    if not raw:
        return []
    if raw == "*":
        return ["*"]
    return [part.strip() for part in raw.split(",") if part.strip()]


def get_env_bool(key: str, default: bool = False) -> bool:
    """
    Get a boolean env var.

    Args:
        key: Environment variable name.
        default: Default value.

    Returns:
        Boolean value.

    Example:
        >>> os.environ["DEBUG"] = "true"
        >>> get_env_bool("DEBUG")
        True
    """
    value = os.getenv(key, "").lower()
    if value in ("true", "1", "yes", "on"):
        return True
    if value in ("false", "0", "no", "off"):
        return False
    return default


def get_env_int(key: str, default: int = 0) -> int:
    """
    Get an integer env var.

    Args:
        key: Environment variable name.
        default: Default value.

    Returns:
        Integer value.
    """
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def get_env_float(key: str, default: float = 0.0) -> float:
    """
    Get a float env var.

    Args:
        key: Environment variable name.
        default: Default value.

    Returns:
        Float value.
    """
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


# =============================================================================
# List utilities
# =============================================================================

def chunk_list(lst: list[T], chunk_size: int) -> list[list[T]]:
    """
    Split a list into fixed-size chunks.

    Args:
        lst: Original list.
        chunk_size: Chunk size.

    Returns:
        Chunked list.

    Example:
        >>> chunk_list([1, 2, 3, 4, 5], 2)
        [[1, 2], [3, 4], [5]]
    """
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def flatten_list(nested: list[list[T]]) -> list[T]:
    """
    Flatten a nested list.

    Args:
        nested: Nested list.

    Returns:
        Flattened list.

    Example:
        >>> flatten_list([[1, 2], [3, 4], [5]])
        [1, 2, 3, 4, 5]
    """
    return [item for sublist in nested for item in sublist]


__all__ = [
    # UUID
    "to_uuid",
    "to_uuid_or_none",
    "uuid_list",
    # Model
    "models_to_dicts",
    "model_to_dict",
    # Proxy
    "get_proxy_url",
    "has_proxy_configured",
    # String
    "truncate_string",
    "safe_str",
    # Config
    "parse_csv",
    "get_env_bool",
    "get_env_int",
    "get_env_float",
    # List
    "chunk_list",
    "flatten_list",
]
