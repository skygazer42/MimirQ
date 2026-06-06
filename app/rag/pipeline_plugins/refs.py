from __future__ import annotations

import re
from typing import Any

from app.core.config import settings

PYTHON_PLUGIN_IMPORT_REF_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*(?::[A-Za-z_][A-Za-z0-9_]*)?$")
REGISTERED_PYTHON_PLUGIN_REF_RE = re.compile(
    r"^plugin:[a-z0-9][a-z0-9_.-]{0,63}@[A-Za-z0-9][A-Za-z0-9_.+-]{0,31}:(?P<stage>governance|chunk|kg)$"
)


def python_plugin_allow_prefixes() -> tuple[str, ...]:
    raw = str(getattr(settings, "PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES", "") or "").strip()
    return tuple(prefix.strip() for prefix in raw.split(",") if prefix.strip())


def registered_python_plugin_stage(plugin_ref: str) -> str | None:
    match = REGISTERED_PYTHON_PLUGIN_REF_RE.fullmatch(str(plugin_ref or "").strip())
    return match.group("stage") if match else None


def is_registered_python_plugin_ref(plugin_ref: str) -> bool:
    return registered_python_plugin_stage(plugin_ref) is not None


def clean_python_plugin_ref(
    raw: Any,
    *,
    field_name: str = "python plugin ref",
    expected_stage: str | None = None,
    invalid_message: str | None = None,
    file_path_message: str | None = None,
    disabled_import_message: str | None = None,
) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{field_name} must be a string")
    value = raw.strip()
    if not value:
        return None
    if len(value) > 240:
        raise ValueError(f"{field_name} too long (max=240)")
    if "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(file_path_message or f"{field_name} must be an import path or registered plugin ref, not a file path")

    registered_stage = registered_python_plugin_stage(value)
    if registered_stage is not None:
        if expected_stage and registered_stage != expected_stage:
            raise ValueError(f"{field_name} registered ref must target the {expected_stage} stage")
        return value

    if not PYTHON_PLUGIN_IMPORT_REF_RE.fullmatch(value):
        raise ValueError(invalid_message or f"{field_name} must be module:function or plugin:<id>@<version>:<stage>")

    module_name, _sep, _function_name = value.partition(":")
    allowed = python_plugin_allow_prefixes()
    if not allowed:
        raise ValueError(
            disabled_import_message
            or "python plugin import refs are disabled; use plugin:<id>@<version>:<stage>"
        )
    if not any(module_name.startswith(prefix) for prefix in allowed):
        raise ValueError(f"{field_name} module '{module_name}' is not allowed")
    return value


def sanitize_python_plugin_ref(
    raw: Any,
    *,
    expected_stage: str | None = None,
) -> str | None:
    try:
        return clean_python_plugin_ref(raw, expected_stage=expected_stage)
    except ValueError:
        return None


__all__ = [
    "PYTHON_PLUGIN_IMPORT_REF_RE",
    "REGISTERED_PYTHON_PLUGIN_REF_RE",
    "clean_python_plugin_ref",
    "is_registered_python_plugin_ref",
    "python_plugin_allow_prefixes",
    "registered_python_plugin_stage",
    "sanitize_python_plugin_ref",
]
