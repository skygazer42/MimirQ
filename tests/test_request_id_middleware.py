
import re

_UUID_HEX_RE = re.compile(r"^[0-9a-f]{32}$")


def test_normalize_request_id_accepts_valid() -> None:
    from app.api.middleware.request_id import _normalize_request_id

    assert _normalize_request_id("abc-123") == "abc-123"
    assert _normalize_request_id("  abc_123  ") == "abc_123"
    assert _normalize_request_id("a" * 128) == "a" * 128


def test_normalize_request_id_rejects_injection_and_invalid() -> None:
    from app.api.middleware.request_id import _normalize_request_id

    assert _UUID_HEX_RE.match(_normalize_request_id(None) or "")
    assert _UUID_HEX_RE.match(_normalize_request_id("") or "")

    # Header injection / control chars
    assert _UUID_HEX_RE.match(_normalize_request_id("abc\n123") or "")
    assert _UUID_HEX_RE.match(_normalize_request_id("abc\r123") or "")

    # Invalid leading char
    assert _UUID_HEX_RE.match(_normalize_request_id("-bad") or "")

    # Too long (max 128)
    assert _UUID_HEX_RE.match(_normalize_request_id("a" * 129) or "")

