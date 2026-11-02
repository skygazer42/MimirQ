from typing import Any


def evaluate_tenant_token_quota(
    *,
    tenant_id: str,
    monthly_token_limit: int,
    monthly_token_used: int,
    mode: str = "warn",
    warning_ratio: float = 0.9,
) -> dict[str, Any]:
    limit = max(0, monthly_token_limit)
    used = max(0, monthly_token_used)
    warning_ratio = max(0.0, min(1.0, warning_ratio))
    mode_norm = mode.strip().lower() or "warn"

    status = "ok"
    if limit > 0 and used >= limit:
        status = "block" if mode_norm == "block" else "warn"
    elif limit > 0 and used >= int(limit * warning_ratio):
        status = "warn"

    remaining = max(0, limit - used) if limit > 0 else 0
    return {
        "schema": "mimirq.tenant_token_quota.v1",
        "tenant_id": tenant_id.strip(),
        "monthly_token_limit": limit,
        "monthly_token_used": used,
        "remaining_tokens": remaining,
        "status": status,
        "hard_block": status == "block",
        "mode": mode_norm,
        "warning_ratio": round(warning_ratio, 4),
    }


__all__ = ["evaluate_tenant_token_quota"]
