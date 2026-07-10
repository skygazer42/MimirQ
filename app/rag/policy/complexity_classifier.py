
import re
from typing import Any

_STRUCTURED_RE = re.compile(r"schema|字段|表|列|节点|sql|字段名|column", flags=re.IGNORECASE)
_MULTIHOP_RE = re.compile(r"根据.+和.+|为什么|原因|compare|analyze|多跳|结合", flags=re.IGNORECASE)


def classify_query_complexity(query: str) -> dict[str, Any]:
    text = str(query or "").strip()
    label = "simple"
    reasons: list[str] = []
    if _STRUCTURED_RE.search(text):
        label = "structured"
        reasons.append("structured_pattern")
    elif _MULTIHOP_RE.search(text):
        label = "multi_hop"
        reasons.append("multi_hop_pattern")
    else:
        reasons.append("default_simple")
    return {
        "label": label,
        "reasons": reasons,
    }


__all__ = ["classify_query_complexity"]
