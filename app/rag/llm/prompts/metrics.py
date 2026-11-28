"""Token budgets, context overflow and prompt preview metrics."""

from typing import Any

from app.infrastructure.tokens import num_tokens_from_string


def compute_context_cliff_metrics(*, context_tokens: int, threshold_tokens: int) -> dict[str, int | bool]:
    ctx = max(0, int(context_tokens or 0))
    threshold = max(0, int(threshold_tokens or 0))
    triggered = threshold > 0 and ctx > threshold
    overflow = ctx - threshold if triggered else 0
    return {
        "context_cliff_threshold_tokens": threshold,
        "context_cliff_triggered": triggered,
        "context_cliff_overflow_tokens": overflow,
    }


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

    for section, text in (("prompt", prompt_text), ("context", context), ("history", history)):
        metrics[f"{section}_chars"] = len(text)
        metrics[f"{section}_tokens"] = num_tokens_from_string(text)

    for key, elapsed in (
        ("elapsed_sec", elapsed_sec),
        ("context_build_elapsed_sec", context_build_elapsed_sec),
        ("prompt_render_elapsed_sec", prompt_render_elapsed_sec),
    ):
        if elapsed is not None:
            metrics[key] = round(float(elapsed), 3)

    return metrics


__all__ = ["compute_context_cliff_metrics", "compute_prompt_preview_metrics"]
