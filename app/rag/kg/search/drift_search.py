from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"\w+|[\u4e00-\u9fff]{2,}", flags=re.ASCII)


def _tokenize(text: str) -> set[str]:
    return {str(token).casefold() for token in _TOKEN_RE.findall(str(text or "").strip()) if str(token).strip()}


def run_drift_search(
    *,
    query: str,
    community_reports: list[dict[str, Any]],
    top_k: int = 3,
) -> dict[str, Any]:
    query_tokens = _tokenize(str(query or ""))
    scored: list[tuple[float, dict[str, Any]]] = []
    for report in community_reports or []:
        if not isinstance(report, dict):
            continue
        summary = str(report.get("summary") or "").strip()
        overlap = len(query_tokens & _tokenize(summary))
        scored.append((float(overlap), dict(report)))

    scored.sort(key=lambda item: (-item[0], str((item[1] or {}).get("community_id") or "")))
    limit = max(1, int(top_k or 1))
    selected = [report for _score, report in scored[:limit]]

    reason_codes: list[str] = []
    if selected and all(score <= 0.0 for score, _report in scored[:limit]):
        reason_codes.append("fallback_first_community")

    entity_ids: list[str] = []
    seen_entities: set[str] = set()
    event_ids: list[str] = []
    seen_events: set[str] = set()
    for report in selected:
        for entity in report.get("entities") or []:
            if not isinstance(entity, dict):
                continue
            entity_id = str(entity.get("entity_id") or entity.get("id") or "").strip()
            if entity_id and entity_id not in seen_entities:
                seen_entities.add(entity_id)
                entity_ids.append(entity_id)
        for event in report.get("events") or []:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("id") or event.get("event_id") or "").strip()
            if event_id and event_id not in seen_events:
                seen_events.add(event_id)
                event_ids.append(event_id)

    return {
        "schema": "mimirq.kg_drift_search.v1",
        "selected_communities": selected,
        "expanded_entity_ids": entity_ids,
        "expanded_event_ids": event_ids,
        "reason_codes": reason_codes,
    }


__all__ = ["run_drift_search"]
