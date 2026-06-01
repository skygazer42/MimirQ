"""
Path management module.

Centralizes project path definitions to avoid repeated computation.
"""

import os
from pathlib import Path

# =============================================================================
# Project root
# =============================================================================

def _find_project_root() -> Path:
    """
    Find project root.

    Walk upward from this file until a directory containing app/ is found.

    Returns:
        Project root path.
    """
    current = Path(__file__).resolve()
    # app/core/paths.py -> app/core -> app -> repo root
    return current.parents[2]


# Project root (repo root)
PROJECT_ROOT: Path = _find_project_root()

# App directory (app/)
APP_DIR: Path = PROJECT_ROOT / "app"


# =============================================================================
# Resource directories
# =============================================================================

# Models directory
MODELS_DIR: Path = PROJECT_ROOT / "resources" / "models"

# Upload directory
UPLOAD_DIR: Path = PROJECT_ROOT / "uploads"

# Temp directory
TEMP_DIR: Path = PROJECT_ROOT / "temp"

# Logs directory
LOG_DIR: Path = PROJECT_ROOT / "logs"


# =============================================================================
# Config file paths
# =============================================================================

# .env file
ENV_FILE: Path = PROJECT_ROOT / ".env"

# Alembic config
ALEMBIC_INI: Path = PROJECT_ROOT / "alembic.ini"


# =============================================================================
# Path utilities
# =============================================================================

def ensure_dir(path: Path) -> Path:
    """
    Ensure directory exists, create if needed.

    Args:
        path: Directory path.

    Returns:
        Directory path.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_safe_child(base: Path, child: str, *, label: str) -> Path:
    """
    Resolve a caller-provided child path under `base`.

    Public path helpers are sometimes used at API boundaries. Keeping this
    guard here prevents accidental absolute-path or traversal use when a caller
    passes an untrusted filename/model name.
    """
    raw = str(child or "").strip()
    if not raw:
        raise ValueError(f"{label} is required")
    candidate = (base / raw).resolve(strict=False)
    base_resolved = base.resolve(strict=False)
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(f"{label} must stay under {base_resolved}") from exc
    return candidate


def get_upload_path(filename: str, tenant_id: str | None = None) -> Path:
    """
    Get storage path for uploaded file.

    Args:
        filename: File name.
        tenant_id: Tenant ID (optional).

    Returns:
        Full file path.
    """
    upload_dir = _resolve_safe_child(UPLOAD_DIR, tenant_id, label="tenant_id") if tenant_id else UPLOAD_DIR

    ensure_dir(upload_dir)
    return _resolve_safe_child(upload_dir, filename, label="filename")


def get_temp_path(filename: str) -> Path:
    """
    Get temp file path.

    Args:
        filename: File name.

    Returns:
        Full file path.
    """
    ensure_dir(TEMP_DIR)
    return _resolve_safe_child(TEMP_DIR, filename, label="filename")


def get_model_path(model_name: str) -> Path:
    """
    Get model file path.

    Args:
        model_name: Model name.

    Returns:
        Model directory path.
    """
    return _resolve_safe_child(MODELS_DIR, model_name, label="model_name")


def resolve_path(path: str) -> Path:
    """
    Resolve a path (relative or absolute).

    Relative paths are resolved from project root.

    Args:
        path: Path string.

    Returns:
        Resolved Path object.
    """
    p = Path(path)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p


def get_relative_path(path: Path) -> str:
    """
    Get path relative to project root.

    Args:
        path: Absolute path.

    Returns:
        Relative path string.
    """
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# =============================================================================
# Environment overrides
# =============================================================================

def _get_path_from_env(env_key: str, default: Path) -> Path:
    """
    Get path from environment variable, overriding default if set.

    Args:
        env_key: Environment variable name.
        default: Default path.

    Returns:
        Path.
    """
    value = os.getenv(env_key)
    if value:
        return Path(value)
    return default


# Paths that can be overridden via environment variables
MODELS_DIR = _get_path_from_env("MODEL_BASE_DIR", MODELS_DIR)
UPLOAD_DIR = _get_path_from_env("UPLOAD_DIR", UPLOAD_DIR)
TEMP_DIR = _get_path_from_env("TEMP_DIR", TEMP_DIR)
LOG_DIR = _get_path_from_env("LOG_DIR", LOG_DIR)


__all__ = [
    # Directory constants
    "PROJECT_ROOT",
    "APP_DIR",
    "MODELS_DIR",
    "UPLOAD_DIR",
    "TEMP_DIR",
    "LOG_DIR",
    # Config files
    "ENV_FILE",
    "ALEMBIC_INI",
    # Utilities
    "ensure_dir",
    "get_upload_path",
    "get_temp_path",
    "get_model_path",
    "resolve_path",
    "get_relative_path",
]
