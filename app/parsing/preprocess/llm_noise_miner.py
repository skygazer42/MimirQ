
import re
from collections import Counter
from typing import Any

_SCHEMA = "mimirq.llm_noise_miner.v1"

def _is_attachment_download_meta(line: str) -> bool:
    text = line.strip()
    if not (text.startswith("(") and text.endswith(")") and "下载次数:" in text):
        return False
    size_part, _, count_part = text[1:-1].partition(",")
    unit = size_part.strip().split(" ")[-1].upper()
    count = count_part.replace("下载次数:", "", 1).strip()
    return unit in {"MB", "KB", "GB"} and count.isdigit()


def _is_reply_time(line: str) -> bool:
    return line.strip().startswith("回复时间：")


def _is_forum_reply_title(line: str) -> bool:
    text = line.strip()
    if not (text.startswith("【回复") and text.endswith("】") and "-" in text):
        return False
    number = text.removeprefix("【回复").split("-", 1)[0].strip()
    return number.isdigit()


_TEMPLATE_LIBRARY: list[tuple[str, Any, str]] = [
    (
        "attachment_download_meta",
        _is_attachment_download_meta,
        r"(?m)^\([\d\.]+\s*(MB|KB|GB),\s*下载次数:\s*\d+\)\s*$",
    ),
    (
        "reply_time",
        _is_reply_time,
        r"(?m)^\s*回复时间：.*$",
    ),
    (
        "forum_reply_title",
        _is_forum_reply_title,
        r"(?m)^\s*【回复\s+\d+\s*-\s*.*】\s*$",
    ),
]


def _normalize_line(value: Any) -> str:
    return str(value or "").strip()


def _collect_template_hits(normalized: list[str]) -> dict[str, dict[str, Any]]:
    template_hits: dict[str, dict[str, Any]] = {}
    for line in normalized:
        for key, matcher, pattern in _TEMPLATE_LIBRARY:
            if matcher(line):
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
    return template_hits


def _build_exact_candidates(
    *,
    exact_counts: Counter[str],
    existing: set[str],
    min_freq: int,
) -> list[dict[str, Any]]:
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
    return candidates


def _build_template_candidates(
    *,
    template_hits: dict[str, dict[str, Any]],
    existing: set[str],
    min_freq: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in template_hits.values():
        if int(item["count"] or 0) < min_freq:
            continue
        if str(item["pattern"] or "") in existing:
            continue
        candidates.append(dict(item))
    return candidates


def _sort_and_limit_candidates(candidates: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
    candidates.sort(
        key=lambda item: (
            -int(item.get("count") or 0),
            str(item.get("pattern_kind") or ""),
            str(item.get("pattern") or ""),
        )
    )
    return candidates[: max(1, int(top_k or 1))]


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
    template_hits = _collect_template_hits(normalized)
    candidates = _build_exact_candidates(
        exact_counts=exact_counts,
        existing=existing,
        min_freq=min_freq,
    )
    candidates.extend(
        _build_template_candidates(
            template_hits=template_hits,
            existing=existing,
            min_freq=min_freq,
        )
    )
    candidates = _sort_and_limit_candidates(candidates, top_k=top_k)

    return {
        "schema": _SCHEMA,
        "summary": {
            "input_lines": len(normalized),
            "candidate_count": len(candidates),
        },
        "candidates": candidates,
    }


__all__ = ["mine_noise_rule_candidates"]
