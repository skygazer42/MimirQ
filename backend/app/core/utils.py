"""
核心工具函数

提供常用的数据转换和验证工具函数。
"""

import os
from typing import Any, Dict, List, Optional, TypeVar, Union
from uuid import UUID

from pydantic import BaseModel

from .constants import ProxyEnvKeys


T = TypeVar("T", bound=BaseModel)


# =============================================================================
# UUID 转换
# =============================================================================

def to_uuid(value: Any) -> UUID:
    """
    安全地将值转换为 UUID

    Args:
        value: 要转换的值（UUID、字符串或其他）

    Returns:
        UUID 对象

    Raises:
        ValueError: 如果无法转换为 UUID

    Example:
        >>> to_uuid("123e4567-e89b-12d3-a456-426614174000")
        UUID('123e4567-e89b-12d3-a456-426614174000')
        >>> to_uuid(some_uuid_object)
        UUID('...')
    """
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def to_uuid_or_none(value: Any) -> Optional[UUID]:
    """
    安全地将值转换为 UUID，失败返回 None

    Args:
        value: 要转换的值

    Returns:
        UUID 对象或 None
    """
    if value is None:
        return None
    try:
        return to_uuid(value)
    except (ValueError, AttributeError):
        return None


def uuid_list(values: List[Any]) -> List[UUID]:
    """
    将列表中的值转换为 UUID 列表

    Args:
        values: 值列表

    Returns:
        UUID 列表
    """
    return [to_uuid(v) for v in values]


# =============================================================================
# Pydantic 模型转换
# =============================================================================

def models_to_dicts(models: List[T]) -> List[Dict[str, Any]]:
    """
    将 Pydantic 模型列表转换为字典列表

    Args:
        models: Pydantic 模型列表

    Returns:
        字典列表

    Example:
        >>> messages = [MessageSchema(...), MessageSchema(...)]
        >>> models_to_dicts(messages)
        [{'role': 'user', ...}, {'role': 'assistant', ...}]
    """
    return [m.model_dump() for m in models]


def model_to_dict(model: T, **kwargs) -> Dict[str, Any]:
    """
    将 Pydantic 模型转换为字典

    Args:
        model: Pydantic 模型
        **kwargs: 传递给 model_dump 的参数

    Returns:
        字典
    """
    return model.model_dump(**kwargs)


# =============================================================================
# 代理配置
# =============================================================================

def get_proxy_url() -> Optional[str]:
    """
    获取代理 URL

    按优先级检查代理环境变量，返回第一个找到的值。

    Returns:
        代理 URL 或 None

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
    检查是否配置了代理

    Returns:
        是否配置了代理
    """
    return get_proxy_url() is not None


# =============================================================================
# 字符串工具
# =============================================================================

def truncate_string(s: str, max_length: int, suffix: str = "...") -> str:
    """
    截断字符串到指定长度

    Args:
        s: 原始字符串
        max_length: 最大长度
        suffix: 截断后添加的后缀

    Returns:
        截断后的字符串
    """
    if len(s) <= max_length:
        return s
    return s[:max_length - len(suffix)] + suffix


def safe_str(value: Any, default: str = "") -> str:
    """
    安全地将值转换为字符串

    Args:
        value: 要转换的值
        default: 如果值为 None 时返回的默认值

    Returns:
        字符串
    """
    if value is None:
        return default
    return str(value)


# =============================================================================
# 配置工具
# =============================================================================

def get_env_bool(key: str, default: bool = False) -> bool:
    """
    获取布尔类型环境变量

    Args:
        key: 环境变量名
        default: 默认值

    Returns:
        布尔值

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
    获取整数类型环境变量

    Args:
        key: 环境变量名
        default: 默认值

    Returns:
        整数值
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
    获取浮点数类型环境变量

    Args:
        key: 环境变量名
        default: 默认值

    Returns:
        浮点数值
    """
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


# =============================================================================
# 列表工具
# =============================================================================

def chunk_list(lst: List[T], chunk_size: int) -> List[List[T]]:
    """
    将列表分割成固定大小的块

    Args:
        lst: 原始列表
        chunk_size: 每块大小

    Returns:
        分块后的列表

    Example:
        >>> chunk_list([1, 2, 3, 4, 5], 2)
        [[1, 2], [3, 4], [5]]
    """
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def flatten_list(nested: List[List[T]]) -> List[T]:
    """
    展平嵌套列表

    Args:
        nested: 嵌套列表

    Returns:
        展平后的列表

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
    "get_env_bool",
    "get_env_int",
    "get_env_float",
    # List
    "chunk_list",
    "flatten_list",
]
