from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.rag.preprocessing.pii_presidio import analyze_pii_text

_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("employee_id", re.compile(r"\bEMP-\d{3,}\b", re.IGNORECASE), r"EMP-\d{3,}"),
    ("customer_id", re.compile(r"\bCUST-\d{3,}\b", re.IGNORECASE), r"CUST-\d{3,}"),
    ("contract_id", re.compile(r"\bCONTRACT-\d{4}-\d{3,}\b", re.IGNORECASE), r"CONTRACT-\d{4}-\d{3,}"),
]

_KNOWN_LABELS = {"email_address", "phone_number", "cn_id"}


def discover_pii_candidates(samples: list[str], *, max_candidates: int = 20) -> dict[str, Any]:
    rows = [str(item or "") for item in list(samples or []) if str(item or "").strip()]
    counts: Counter[str] = Counter()
    examples: dict[str, str] = {}

    for text in rows:
        analyzed = analyze_pii_text(text)
        covered_spans = {
            (int(item["start"]), int(item["end"]))
            for item in list(analyzed.get("entities") or [])
            if isinstance(item, dict) and {"start", "end"} <= set(item.keys())
        }

        for label, pattern, _suggested_regex in _PATTERNS:
            for match in pattern.finditer(text):
                span = (int(match.start()), int(match.end()))
                if span in covered_spans:
                    continue
                counts[label] += 1
                examples.setdefault(label, str(match.group(0) or ""))

    candidates: list[dict[str, Any]] = []
    for label, count in counts.most_common(max(0, int(max_candidates or 0))):
        if label in _KNOWN_LABELS:
            continue
        suggested_regex = next((regex for key, _pattern, regex in _PATTERNS if key == label), "")
        candidates.append(
            {
                "label": label,
                "count": int(count),
                "example": examples.get(label),
                "suggested_regex": suggested_regex,
            }
        )

    return {
        "schema": "mimirq.pii_llm_discover.v1",
        "sample_count": int(len(rows)),
        "candidates": candidates,
    }


__all__ = ["discover_pii_candidates"]
