"""
RAG config template patch application helpers.

We apply template patches as *fallback overrides*:
- If a request explicitly provided a rag_config field, keep it.
- Otherwise, apply the template patch field (if any).

This keeps debug/probe callers in control while enabling safe rollout for default traffic.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from app.api.schemas.chat import ChatRAGConfig
from app.core.model_execution import validate_rag_execution_selection


def validate_rag_config_patch(patch: Mapping[str, Any]) -> None:
    """Reject retired selections before schema errors can be wrapped or discarded."""
    validate_rag_execution_selection(
        reranker_provider=patch.get("reranker_provider"),
        sparse_provider=patch.get("sparse_retrieval_provider"),
        retrieval_profile=patch.get("retrieval_profile"),
    )


def apply_rag_config_patch(
    *,
    rag_config: ChatRAGConfig,
    patch: Any,
    request_fields_set: Iterable[str] | None,
) -> tuple[ChatRAGConfig, list[str]]:
    provided = set(request_fields_set or [])
    raw_patch = patch if isinstance(patch, dict) else {}

    merged = dict(rag_config.model_dump())
    applied: list[str] = []

    for k, v in raw_patch.items():
        key = k.strip()
        if not key:
            continue
        if key in provided:
            continue
        if v is None:
            continue
        merged[key] = v
        applied.append(key)

    if not applied:
        return rag_config, []

    # Re-validate invariants after merge (normalizes retrieval_mode/fusion_strategy, etc).
    validate_rag_config_patch(merged)
    return ChatRAGConfig(**merged), applied


__all__ = ["apply_rag_config_patch", "validate_rag_config_patch"]
