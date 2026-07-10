
import hashlib
import re

_WS_RE = re.compile(r"\s+")
_QUOTED_IDENT_RE = re.compile(r'"([^"]+)"')


def normalize_sql_for_fingerprint(sql: str) -> str:
    raw = str(sql or "").strip()
    if not raw:
        return ""
    # Keep literals as-is, but normalize whitespace and quoted identifiers.
    s = _QUOTED_IDENT_RE.sub(lambda m: m.group(1), raw)
    s = _WS_RE.sub(" ", s).strip().lower()
    return s


def fingerprint_sql(sql: str, *, length: int = 16) -> str:
    norm = normalize_sql_for_fingerprint(sql)
    if not norm:
        return ""
    digest = hashlib.sha256(norm.encode("utf-8", "ignore")).hexdigest()
    n = max(1, int(length or 16))
    return digest[:n]


__all__ = ["normalize_sql_for_fingerprint", "fingerprint_sql"]
