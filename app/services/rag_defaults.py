"""
RAG defaults merge helpers.

We treat dataset defaults as *fallbacks*:
- If a request explicitly provided a rag_config field, we keep it.
- Otherwise, apply the dataset's override (if any).
"""

from collections.abc import Iterable
from typing import Any

from app.api.schemas.conversations import ChatRAGConfig
from app.api.schemas.datasets import DatasetRAGDefaults
from app.services.rag_config_template_apply import apply_rag_config_patch


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

    if isinstance(raw_dataset_defaults, DatasetRAGDefaults):
        defaults = raw_dataset_defaults
    elif isinstance(raw_dataset_defaults, dict):
        defaults = DatasetRAGDefaults(
            **{key: value for key, value in raw_dataset_defaults.items() if key not in provided}
        )
    else:
        raise TypeError("dataset RAG defaults must be an object")

    overrides = defaults.model_dump(exclude_none=True)
    contract_mode = overrides.get("retrieval_contract_mode")
    if (
        contract_mode is not None
        and contract_mode.strip().lower() == "evidence_strict"
        and "visible_evidence_only" not in overrides
    ):
        overrides["visible_evidence_only"] = True
    if not overrides:
        return rag_config, []

    return apply_rag_config_patch(rag_config=rag_config, patch=overrides, request_fields_set=provided)
