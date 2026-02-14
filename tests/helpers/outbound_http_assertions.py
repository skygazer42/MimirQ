from __future__ import annotations

from collections.abc import Mapping


def assert_no_internal_context_headers(
    headers: Mapping[str, str],
    *,
    tenant_header_name: str | None = None,
) -> None:
    """
    Assert that outbound request headers do not include internal attribution headers.

    These headers are useful for internal service-to-service calls, but must not be
    propagated to third-party endpoints (compliance/privacy).
    """
    lowered = {str(k).lower(): str(v) for k, v in dict(headers).items()}

    assert "x-tenant-id" not in lowered
    assert "x-user-id" not in lowered

    if tenant_header_name:
        name = str(tenant_header_name).strip().lower()
        if name:
            assert name not in lowered

