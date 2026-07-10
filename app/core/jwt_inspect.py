"""
Lightweight helpers to inspect JWTs without verifying signatures.

Used for best-effort diagnostics (e.g., token expiry warnings) for third-party
services where we do not have the signing key.
"""


import base64
import json
from datetime import UTC, datetime
from typing import Any


def _base64url_decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def try_get_jwt_claims(token: str) -> dict[str, Any] | None:
    """
    Parse JWT payload claims without validating the signature.

    Returns None if the token does not look like a JWT or payload decoding fails.
    """
    parts = str(token or "").strip().split(".")
    if len(parts) != 3:
        return None
    payload_b64 = parts[1]
    if not payload_b64:
        return None
    try:
        payload = _base64url_decode(payload_b64)
        obj = json.loads(payload.decode("utf-8"))
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def try_get_jwt_exp(token: str) -> int | None:
    """Return the `exp` claim as unix seconds if present, else None."""
    claims = try_get_jwt_claims(token)
    if not claims:
        return None
    exp = claims.get("exp")
    if isinstance(exp, bool):
        return None
    if isinstance(exp, (int, float)):
        try:
            return int(exp)
        except (TypeError, ValueError):
            return None
    return None


def format_unix_ts_utc(ts: int) -> str:
    """Format unix seconds as an ISO-8601 UTC string."""
    return datetime.fromtimestamp(int(ts), tz=UTC).isoformat().replace("+00:00", "Z")
