"""
RAG defaults merge helpers.

We treat dataset defaults as *fallbacks*:
- If a request explicitly provided a rag_config field, we keep it.
- Otherwise, apply the dataset's override (if any).
"""


from collections.abc import Iterable
from typing import Any

from app.api.schemas.chat import ChatRAGConfig
from app.api.schemas.dataset import DatasetRAGDefaults


def _coerce_dataset_defaults(raw_dataset_defaults: Any) -> DatasetRAGDefaults | None:
    if isinstance(raw_dataset_defaults, DatasetRAGDefaults):
        return raw_dataset_defaults
    if isinstance(raw_dataset_defaults, dict):
        try:
            return DatasetRAGDefaults(**raw_dataset_defaults)
        except Exception:
            return None
    return None


def _normalized_dataset_overrides(defaults: DatasetRAGDefaults) -> dict[str, Any]:
    overrides = defaults.model_dump(exclude_none=True)
    if (
        str(overrides.get("retrieval_contract_mode") or "").strip().lower() == "evidence_strict"
        and "visible_evidence_only" not in overrides
    ):
        overrides["visible_evidence_only"] = True
    return overrides


def _merge_dataset_rag_overrides(
    *,
    rag_config: ChatRAGConfig,
    provided: set[str],
    overrides: dict[str, Any],
) -> tuple[ChatRAGConfig, list[str]]:
    merged = dict(rag_config.model_dump())
    applied: list[str] = []
    for key, value in overrides.items():
        if key in provided:
            continue
        merged[key] = value
        applied.append(str(key))
    if not applied:
        return rag_config, []
    return ChatRAGConfig(**merged), applied


def merge_rag_config_with_dataset_defaults(
    *,
    rag_config: ChatRAGConfig,
    request_fields_set: Iterable[str] | None,
    raw_dataset_defaults: Any,
) -> tuple[ChatRAGConfig, list[str]]:
    """
    Merge dataset-level defaults into an existing ChatRAGConfig.

    Args:
        rag_config: The request RAG config (already validated).
        request_fields_set: Fields explicitly provided by the request body. If rag_config was omitted
            entirely, pass an empty iterable.
        raw_dataset_defaults: The dataset metadata value (dict) or DatasetRAGDefaults or None.

    Returns:
        (effective_rag_config, applied_field_names)
    """
    provided = set(request_fields_set or [])

    if raw_dataset_defaults is None:
        return rag_config, []

    defaults = _coerce_dataset_defaults(raw_dataset_defaults)
    if defaults is None:
        return rag_config, []

    overrides = _normalized_dataset_overrides(defaults)
    if not overrides:
        return rag_config, []

    return _merge_dataset_rag_overrides(rag_config=rag_config, provided=provided, overrides=overrides)
