"""Small ingestion-preview config/data helpers for the pipeline API.

Extracted verbatim from ``app/api/v1/pipeline.py``. Most ingestion-preview
helpers stay in ``app.api.v1.pipeline`` because tests monkeypatch them there.
Submodules must not import ``app.api.v1.pipeline`` (circular import).
"""
from dataclasses import dataclass, field

from app.core.config import settings


@dataclass
class _IngestionPreviewConfig:
    base_parser_backend: str
    base_chunk_strategy: str
    parser_backend_choice: str
    chunk_strategy_choice: str
    preprocess_steps: list[dict[str, object]] = field(default_factory=list)
    governance_profile_ref: str | None = None
    patch_dict: dict[str, object] = field(default_factory=dict)


def _empty_preprocess_summary() -> dict[str, object]:
    return {"changed": False, "size_before": 0, "size_after": 0, "steps": [], "warnings": []}


def _ingestion_preview_defaults(
    parser_backend: str | None,
    chunk_strategy: str | None,
) -> tuple[str, str, str, str]:
    default_pb = (getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto").strip().lower() or "auto"
    default_cs = (getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive").strip().lower()
    base_pb = (parser_backend or default_pb).strip().lower() or default_pb
    base_cs = (chunk_strategy or default_cs).strip().lower() or default_cs
    return default_pb, default_cs, base_pb, base_cs


def _ingestion_rule_preprocess_steps(matched_rule: object | None) -> list[dict[str, object]]:
    preprocess = getattr(matched_rule, "preprocess", None) if matched_rule is not None else None
    steps = getattr(preprocess, "steps", None) if preprocess is not None and bool(getattr(preprocess, "enabled", True)) else None
    if not isinstance(steps, list) or not steps:
        return []
    return [
        {
            "id": str(getattr(step, "id", "") or "").strip(),
            "params": dict(getattr(step, "params", {}) or {}),
        }
        for step in steps
    ]


def _effective_bool(effective: object, name: str, default: bool) -> bool:
    return bool(getattr(effective, name, default))


def _effective_int(effective: object, name: str, default: int) -> int:
    return int(getattr(effective, name, default) or default)


def _effective_float(effective: object, name: str, default: float) -> float:
    return float(getattr(effective, name, default) or default)


def _effective_str(effective: object, name: str, default: str) -> str:
    return str(getattr(effective, name, default) or default)
