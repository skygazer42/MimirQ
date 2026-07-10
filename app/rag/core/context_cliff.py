

def compute_context_cliff_metrics(*, context_tokens: int, threshold_tokens: int) -> dict[str, int | bool]:
    ctx = max(0, int(context_tokens or 0))
    threshold = max(0, int(threshold_tokens or 0))
    triggered = bool(threshold > 0 and ctx > threshold)
    overflow = max(0, ctx - threshold) if triggered else 0
    return {
        "context_cliff_threshold_tokens": threshold,
        "context_cliff_triggered": triggered,
        "context_cliff_overflow_tokens": int(overflow),
    }


__all__ = ["compute_context_cliff_metrics"]
