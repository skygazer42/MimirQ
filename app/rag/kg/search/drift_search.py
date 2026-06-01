from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"\w+|[\u4e00-\u9fff]{2,}", flags=re.ASCII)


def _tokenize(text: str) -> set[str]:
    return {str(token).casefold() for token in _TOKEN_RE.findall(str(text or "").strip()) if str(token).strip()}


def _score_reports(query_tokens: set[str], community_reports: list[dict[str, Any]]) -> list[tuple[float, dict[str, Any]]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for report in community_reports or []:
        if isinstance(report, dict):
            summary = str(report.get("summary") or "").strip()
            scored.append((float(len(query_tokens & _tokenize(summary))), dict(report)))
    return sorted(scored, key=lambda item: (-item[0], str((item[1] or {}).get("community_id") or "")))


def _selected_reports(scored: list[tuple[float, dict[str, Any]]], top_k: int) -> list[dict[str, Any]]:
    return [report for _score, report in scored[: max(1, int(top_k or 1))]]


def _fallback_reason_codes(scored: list[tuple[float, dict[str, Any]]], selected: list[dict[str, Any]]) -> list[str]:
    selected_scores = scored[: len(selected)]
    if selected and all(score <= 0.0 for score, _report in selected_scores):
        return ["fallback_first_community"]
    return []


def _append_unique_id(target: list[str], seen: set[str], value: Any) -> None:
    item_id = str(value or "").strip()
    if item_id and item_id not in seen:
        seen.add(item_id)
        target.append(item_id)


def _collect_report_ids(selected: list[dict[str, Any]], key: str, candidates: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for report in selected:
        for item in report.get(key) or []:
            if isinstance(item, dict):
                _append_unique_id(out, seen, next((item.get(candidate) for candidate in candidates if item.get(candidate)), ""))
    return out


def run_drift_search(
    *,
    query: str,
    community_reports: list[dict[str, Any]],
    top_k: int = 3,
) -> dict[str, Any]:
    query_tokens = _tokenize(str(query or ""))
    scored = _score_reports(query_tokens, community_reports)
    selected = _selected_reports(scored, top_k)

    return {
        "schema": "mimirq.kg_drift_search.v1",
        "selected_communities": selected,
        "expanded_entity_ids": _collect_report_ids(selected, "entities", ("entity_id", "id")),
        "expanded_event_ids": _collect_report_ids(selected, "events", ("id", "event_id")),
        "reason_codes": _fallback_reason_codes(scored, selected),
    }


__all__ = ["run_drift_search"]
