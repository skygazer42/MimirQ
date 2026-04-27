from __future__ import annotations

import re
from collections import Counter
from typing import Any

_SCHEMA = "mimirq.llm_noise_miner.v1"

_TEMPLATE_LIBRARY: list[tuple[str, re.Pattern[str], str]] = [
    (
        "attachment_download_meta",
        re.compile(r"^\([\d\.]+\s*(MB|KB|GB),\s*下载次数:\s*\d+\)\s*$"),
        r"(?m)^\([\d\.]+\s*(MB|KB|GB),\s*下载次数:\s*\d+\)\s*$",
    ),
    (
        "reply_time",
        re.compile(r"^回复时间：.+$"),
        r"(?m)^\s*回复时间：.*$",
    ),
    (
        "forum_reply_title",
        re.compile(r"^【回复\s+\d+\s*-\s*.*】$"),
        r"(?m)^\s*【回复\s+\d+\s*-\s*.*】\s*$",
    ),
]


def _normalize_line(value: Any) -> str:
    return str(value or "").strip()


def mine_noise_rule_candidates(
    lines: list[str],
    *,
    existing_patterns: list[str] | None = None,
    top_k: int = 20,
    min_frequency: int = 2,
) -> dict[str, Any]:
    existing = {str(item or "").strip() for item in (existing_patterns or []) if str(item or "").strip()}
    normalized = [_normalize_line(line) for line in (lines or []) if _normalize_line(line)]
    min_freq = max(1, int(min_frequency or 1))

    exact_counts = Counter(normalized)
    template_hits: dict[str, dict[str, Any]] = {}
    for line in normalized:
        for key, matcher, pattern in _TEMPLATE_LIBRARY:
            if matcher.match(line):
                entry = template_hits.setdefault(
                    pattern,
                    {
                        "pattern_kind": "template",
                        "pattern_name": key,
                        "pattern": pattern,
                        "count": 0,
                        "examples": [],
                        "review_required": True,
                    },
                )
                entry["count"] = int(entry["count"] or 0) + 1
                examples = entry["examples"]
                if len(examples) < 3 and line not in examples:
                    examples.append(line)
                break

    candidates: list[dict[str, Any]] = []
    for line, count in exact_counts.items():
        if count < min_freq:
            continue
        pattern = rf"(?m)^\s*{re.escape(line)}\s*$"
        if pattern in existing:
            continue
        candidates.append(
            {
                "pattern_kind": "exact",
                "pattern_name": "repeated_line",
                "pattern": pattern,
                "count": int(count),
                "examples": [line],
                "review_required": True,
            }
        )

    for item in template_hits.values():
        if int(item["count"] or 0) < min_freq:
            continue
        if str(item["pattern"] or "") in existing:
            continue
        candidates.append(dict(item))

    candidates.sort(
        key=lambda item: (
            -int(item.get("count") or 0),
            str(item.get("pattern_kind") or ""),
            str(item.get("pattern") or ""),
        )
    )
    candidates = candidates[: max(1, int(top_k or 1))]

    return {
        "schema": _SCHEMA,
        "summary": {
            "input_lines": len(normalized),
            "candidate_count": len(candidates),
        },
        "candidates": candidates,
    }


__all__ = ["mine_noise_rule_candidates"]
