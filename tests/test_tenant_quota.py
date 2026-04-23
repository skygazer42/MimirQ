from __future__ import annotations

from app.services.tenant_quota import evaluate_tenant_token_quota


def test_evaluate_tenant_token_quota_returns_warn_before_limit() -> None:
    out = evaluate_tenant_token_quota(
        tenant_id="tenant-a",
        monthly_token_limit=1000,
        monthly_token_used=920,
        mode="warn",
        warning_ratio=0.9,
    )

    assert out["schema"] == "mimirq.tenant_token_quota.v1"
    assert out["tenant_id"] == "tenant-a"
    assert out["status"] == "warn"
    assert out["hard_block"] is False


def test_evaluate_tenant_token_quota_returns_block_when_over_limit() -> None:
    out = evaluate_tenant_token_quota(
        tenant_id="tenant-a",
        monthly_token_limit=1000,
        monthly_token_used=1200,
        mode="block",
        warning_ratio=0.9,
    )

    assert out["status"] == "block"
    assert out["hard_block"] is True
    assert out["remaining_tokens"] == 0
