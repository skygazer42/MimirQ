"""
路径管理模块

统一管理项目中的路径定义，避免重复计算。
"""

import os
from pathlib import Path
from typing import Optional


# =============================================================================
# 项目根目录
# =============================================================================

def _find_project_root() -> Path:
    """
    查找项目根目录

    从当前文件向上查找，直到找到包含 app 目录的目录。

    Returns:
        项目根目录路径
    """
    current = Path(__file__).resolve()
    # app/core/paths.py -> app/core -> app -> repo root
    return current.parents[2]


# 项目根目录 (repo root)
PROJECT_ROOT: Path = _find_project_root()

# 应用目录 (app/)
APP_DIR: Path = PROJECT_ROOT / "app"


# =============================================================================
# 资源目录
# =============================================================================

# 模型目录
MODELS_DIR: Path = PROJECT_ROOT / "resources" / "models"

# 上传文件目录
UPLOAD_DIR: Path = PROJECT_ROOT / "uploads"

# 临时文件目录
TEMP_DIR: Path = PROJECT_ROOT / "temp"

# 日志目录
LOG_DIR: Path = PROJECT_ROOT / "logs"


# =============================================================================
# 配置文件路径
# =============================================================================

# .env 文件
ENV_FILE: Path = PROJECT_ROOT / ".env"

# alembic 配置
ALEMBIC_INI: Path = PROJECT_ROOT / "alembic.ini"


# =============================================================================
# 路径工具函数
# =============================================================================

def ensure_dir(path: Path) -> Path:
    """
    确保目录存在，不存在则创建

    Args:
        path: 目录路径

    Returns:
        目录路径
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_upload_path(filename: str, tenant_id: Optional[str] = None) -> Path:
    """
    获取上传文件的存储路径

    Args:
        filename: 文件名
        tenant_id: 租户 ID（可选）

    Returns:
        完整文件路径
    """
    if tenant_id:
        upload_dir = UPLOAD_DIR / tenant_id
    else:
        upload_dir = UPLOAD_DIR

    ensure_dir(upload_dir)
    return upload_dir / filename


def get_temp_path(filename: str) -> Path:
    """
    获取临时文件路径

    Args:
        filename: 文件名

    Returns:
        完整文件路径
    """
    ensure_dir(TEMP_DIR)
    return TEMP_DIR / filename


def get_model_path(model_name: str) -> Path:
    """
    获取模型文件路径

    Args:
        model_name: 模型名称

    Returns:
        模型目录路径
    """
    return MODELS_DIR / model_name


def resolve_path(path: str) -> Path:
    """
    解析路径，支持相对路径和绝对路径

    相对路径基于项目根目录解析。

    Args:
        path: 路径字符串

    Returns:
        解析后的 Path 对象
    """
    p = Path(path)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p


def get_relative_path(path: Path) -> str:
    """
    获取相对于项目根目录的路径

    Args:
        path: 绝对路径

    Returns:
        相对路径字符串
    """
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# =============================================================================
# 环境变量覆盖
# =============================================================================

def _get_path_from_env(env_key: str, default: Path) -> Path:
    """
    从环境变量获取路径，支持覆盖默认值

    Args:
        env_key: 环境变量名
        default: 默认路径

    Returns:
        路径
    """
    value = os.getenv(env_key)
    if value:
        return Path(value)
    return default


# 允许通过环境变量覆盖的路径
MODELS_DIR = _get_path_from_env("MODEL_BASE_DIR", MODELS_DIR)
UPLOAD_DIR = _get_path_from_env("UPLOAD_DIR", UPLOAD_DIR)
TEMP_DIR = _get_path_from_env("TEMP_DIR", TEMP_DIR)
LOG_DIR = _get_path_from_env("LOG_DIR", LOG_DIR)


__all__ = [
    # 目录常量
    "PROJECT_ROOT",
    "APP_DIR",
    "MODELS_DIR",
    "UPLOAD_DIR",
    "TEMP_DIR",
    "LOG_DIR",
    # 配置文件
    "ENV_FILE",
    "ALEMBIC_INI",
    # 工具函数
    "ensure_dir",
    "get_upload_path",
    "get_temp_path",
    "get_model_path",
    "resolve_path",
    "get_relative_path",
]
