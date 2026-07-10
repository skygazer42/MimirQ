"""
RAG config template patch application helpers.

We apply template patches as *fallback overrides*:
- If a request explicitly provided a rag_config field, keep it.
- Otherwise, apply the template patch field (if any).

This keeps debug/probe callers in control while enabling safe rollout for default traffic.
"""


from collections.abc import Iterable
from typing import Any

from app.api.schemas.chat import ChatRAGConfig


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
        key = str(k or "").strip()
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
    return ChatRAGConfig(**merged), applied


__all__ = ["apply_rag_config_patch"]

