"""
Prompt defaults helpers.

We treat dataset prompt settings as *fallbacks*:
- If a request explicitly provided a field (even null), keep it.
- Otherwise, apply the dataset default (if present).
"""


from collections.abc import Iterable
from typing import Any
from uuid import UUID

from app.rag.core.logging import get_logger

logger = get_logger(__name__)


def merge_prompt_defaults_with_dataset(
    *,
    prompt_template_id: UUID | None,
    prompt_template_key: str | None,
    prompt_ab_experiment_key: str | None,
    request_fields_set: Iterable[str] | None,
    dataset_meta: Any,
) -> tuple[UUID | None, str | None, str | None, list[str]]:
    """
    Merge dataset-level prompt defaults into request prompt fields.

    Dataset keys:
      - default_prompt_template_id (str UUID)
      - default_prompt_template_key (str)
      - default_prompt_ab_experiment_key (str)
    """
    provided = set(request_fields_set or [])
    meta = dataset_meta if isinstance(dataset_meta, dict) else {}

    applied: list[str] = []

    eff_id = prompt_template_id
    eff_key = prompt_template_key
    eff_ab = prompt_ab_experiment_key

    # Prefer template id over key when applying defaults.
    if "prompt_template_id" not in provided and eff_id is None:
        raw = meta.get("default_prompt_template_id")
        if isinstance(raw, str) and raw.strip():
            try:
                eff_id = UUID(raw.strip())
                applied.append("prompt_template_id")
            except Exception as exc:
                logger.debug("Ignoring malformed default prompt template id: %s", exc)

    if (
        eff_id is None
        and "prompt_template_key" not in provided
        and not (eff_key or "").strip()
    ):
        raw = meta.get("default_prompt_template_key")
        if isinstance(raw, str) and raw.strip():
            eff_key = raw.strip()
            applied.append("prompt_template_key")

    if "prompt_ab_experiment_key" not in provided and not (eff_ab or "").strip():
        raw = meta.get("default_prompt_ab_experiment_key")
        if isinstance(raw, str) and raw.strip():
            eff_ab = raw.strip()
            applied.append("prompt_ab_experiment_key")

    return eff_id, eff_key, eff_ab, applied
