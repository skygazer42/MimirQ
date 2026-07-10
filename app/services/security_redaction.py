"""
Security redaction helpers for API-safe responses.

Best-effort and fail-open: helpers should not raise for malformed payloads.
"""


import re
from typing import Any

_SQL_STRING_LITERAL_RE = re.compile(r"'(?:''|[^'])*'")
_SQL_LONG_NUMBER_RE = re.compile(r"(?<![\w.])[-+]?\d{5,}(?:\.\d+)?(?![\w.])")

_CONNECTION_KEYS = {
    "host",
    "hostname",
    "port",
    "database",
    "db",
    "username",
    "user",
    "dsn",
    "uri",
    "jdbc_url",
    "connection_string",
}


def redact_sql_literals(sql: str) -> str:
    """
    Mask sensitive SQL literal values while preserving query structure.
    """
    raw = str(sql or "")
    if not raw:
        return ""
    redacted = _SQL_STRING_LITERAL_RE.sub("'<redacted>'", raw)
    return _SQL_LONG_NUMBER_RE.sub("<redacted_num>", redacted)


def redact_connection_info(config: dict[str, Any], *, enabled: bool) -> dict[str, Any]:
    """
    Mask DB-connection fields inside a connector config payload.
    """
    if not isinstance(config, dict):
        return {}
    out: dict[str, Any] = dict(config)
    if not enabled:
        return out

    for key, value in list(out.items()):
        lowered = str(key or "").strip().lower()
        if lowered in _CONNECTION_KEYS and value not in (None, ""):
            out[key] = "<redacted_conn>"
            continue
        if isinstance(value, dict):
            out[key] = redact_connection_info(value, enabled=True)
    return out


__all__ = ["redact_connection_info", "redact_sql_literals"]
