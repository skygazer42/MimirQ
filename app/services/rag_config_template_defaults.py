"""
RAG config template defaults helpers.

We treat dataset default selectors as *fallbacks*:
- If a request explicitly provided a selector field (even null), keep it.
- Otherwise, apply the dataset default (if present).
"""


from collections.abc import Iterable
from typing import Any
from uuid import UUID

from app.rag.core.logging import get_logger

logger = get_logger(__name__)


def merge_rag_config_template_defaults_with_dataset(
    *,
    rag_config_template_id: UUID | None,
    rag_config_template_key: str | None,
    rag_config_ab_experiment_key: str | None,
    request_fields_set: Iterable[str] | None,
    dataset_meta: Any,
) -> tuple[UUID | None, str | None, str | None, list[str]]:
    """
    Merge dataset-level RAG config template defaults into request fields.

    Dataset keys:
      - default_rag_config_template_id (str UUID)
      - default_rag_config_template_key (str)
      - default_rag_config_ab_experiment_key (str)
    """
    provided = set(request_fields_set or [])
    meta = dataset_meta if isinstance(dataset_meta, dict) else {}

    applied: list[str] = []

    eff_id = rag_config_template_id
    eff_key = rag_config_template_key
    eff_ab = rag_config_ab_experiment_key

    # Prefer template id over key when applying defaults.
    if "rag_config_template_id" not in provided and eff_id is None:
        raw = meta.get("default_rag_config_template_id")
        if isinstance(raw, str) and raw.strip():
            try:
                eff_id = UUID(raw.strip())
                applied.append("rag_config_template_id")
            except Exception as exc:
                logger.debug("Ignoring malformed default rag config template id: %s", exc)

    if eff_id is None and "rag_config_template_key" not in provided and not (eff_key or "").strip():
        raw = meta.get("default_rag_config_template_key")
        if isinstance(raw, str) and raw.strip():
            eff_key = raw.strip()
            applied.append("rag_config_template_key")

    if "rag_config_ab_experiment_key" not in provided and not (eff_ab or "").strip():
        raw = meta.get("default_rag_config_ab_experiment_key")
        if isinstance(raw, str) and raw.strip():
            eff_ab = raw.strip()
            applied.append("rag_config_ab_experiment_key")

    return eff_id, eff_key, eff_ab, applied


__all__ = ["merge_rag_config_template_defaults_with_dataset"]
