import hashlib
import re

_WS_RE = re.compile(r"\s+")
_QUOTED_IDENT_RE = re.compile(r'"([^"]+)"')


def normalize_sql_for_fingerprint(sql: str) -> str:
    raw = sql.strip()
    if not raw:
        return ""
    unquoted = _QUOTED_IDENT_RE.sub(lambda match: match.group(1), raw)
    return _WS_RE.sub(" ", unquoted).strip().lower()


def fingerprint_sql(sql: str, *, length: int = 16) -> str:
    norm = normalize_sql_for_fingerprint(sql)
    if not norm:
        return ""
    digest = hashlib.sha256(norm.encode("utf-8", "ignore")).hexdigest()
    n = max(1, length or 16)
    return digest[:n]


__all__ = ["normalize_sql_for_fingerprint", "fingerprint_sql"]
