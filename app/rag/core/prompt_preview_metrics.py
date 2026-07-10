"""
Prompt preview metrics helpers.

The /rag/prompt-preview endpoint (and UI diagnostics tooling) needs a small,
stable set of token + latency breakdown fields. Keep this module pure and
dependency-light so it can be unit-tested without DB/LLM/vector backends.
"""


from typing import Any

from app.core.token_utils import num_tokens_from_string


def compute_prompt_preview_metrics(
    *,
    prompt_text: str,
    context: str,
    history: str,
    base_metrics: dict[str, Any] | None = None,
    elapsed_sec: float | None = None,
    context_build_elapsed_sec: float | None = None,
    prompt_render_elapsed_sec: float | None = None,
) -> dict[str, Any]:
    """
    Augment a metrics dict with chars/tokens breakdown for prompt preview.

    Notes:
    - Uses `num_tokens_from_string()` which is best-effort and falls back to a
      conservative estimate when tiktoken is not available.
    - Rounds elapsed fields to 3 decimals for UI readability.
    """
    metrics: dict[str, Any] = dict(base_metrics or {})

    prompt_text = prompt_text or ""
    context = context or ""
    history = history or ""

    metrics["prompt_chars"] = len(prompt_text)
    metrics["prompt_tokens"] = num_tokens_from_string(prompt_text)

    metrics["context_chars"] = len(context)
    metrics["context_tokens"] = num_tokens_from_string(context)

    metrics["history_chars"] = len(history)
    metrics["history_tokens"] = num_tokens_from_string(history)

    if elapsed_sec is not None:
        metrics["elapsed_sec"] = round(float(elapsed_sec), 3)
    if context_build_elapsed_sec is not None:
        metrics["context_build_elapsed_sec"] = round(float(context_build_elapsed_sec), 3)
    if prompt_render_elapsed_sec is not None:
        metrics["prompt_render_elapsed_sec"] = round(float(prompt_render_elapsed_sec), 3)

    return metrics


__all__ = ["compute_prompt_preview_metrics"]

