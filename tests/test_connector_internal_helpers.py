from __future__ import annotations

import base64

from tests.test_confluence_connector_unit import _import_connectors_with_lightweight_stubs


def test_schedule_interval_seconds_supports_supported_formats() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    assert connectors._schedule_interval_seconds("@hourly") == 60 * 60
    assert connectors._schedule_interval_seconds("@daily") == 60 * 60 * 24
    assert connectors._schedule_interval_seconds("*/15 * * * *") == 15 * 60
    assert connectors._schedule_interval_seconds("0 */6 * * *") == 6 * 60 * 60
    assert connectors._schedule_interval_seconds("0 0 */2 * *") == 2 * 24 * 60 * 60
    assert connectors._schedule_interval_seconds("bad-cron") is None


def test_connector_error_code_from_message_prefers_keywords_and_status() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    assert (
        connectors._connector_error_code_from_message(
            "request blocked by private ip policy",
            default="http_403",
            status_code=403,
        )
        == "ssrf"
    )
    assert (
        connectors._connector_error_code_from_message(
            "gateway timeout while crawling",
            default="http_504",
            status_code=504,
        )
        == "timeout"
    )
    assert (
        connectors._connector_error_code_from_message(
            "payload too large",
            default="http_413",
            status_code=413,
        )
        == "too_large"
    )
    assert (
        connectors._connector_error_code_from_message(
            "validation failed",
            default="http_400",
            status_code=400,
        )
        == "bad_request"
    )
    assert (
        connectors._connector_error_code_from_message(
            "mystery backend error",
            default="http_500",
            status_code=500,
        )
        == "http_500"
    )


def test_append_unique_limited_preserves_uniqueness_and_limit() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    items = ["a", "b"]
    connectors._append_unique_limited(items, "b", limit=3)
    connectors._append_unique_limited(items, "c", limit=3)
    connectors._append_unique_limited(items, "d", limit=3)

    assert items == ["a", "b", "c"]


def test_build_basic_auth_header_requires_both_credentials() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    expected = base64.b64encode(b"bot@example.com:secret").decode("ascii")
    assert connectors._build_basic_auth_header("bot@example.com", "secret") == {
        "Authorization": f"Basic {expected}"
    }
    assert connectors._build_basic_auth_header("bot@example.com", "") == {}
