
from collections.abc import Sequence
from typing import Any

from app.rag.kg.models import KgSourceEvent


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def confidence_bucket(confidence: float, *, low_max: float = 0.4, mid_max: float = 0.7) -> str:
    """
    Coarse confidence buckets for KG relation/path provenance.

    Returns one of: low | mid | high
    """
    try:
        c = float(confidence or 0.0)
    except Exception:
        c = 0.0

    lo = float(low_max)
    mid = float(mid_max)
    if lo >= mid:
        lo, mid = 0.4, 0.7

    if c < lo:
        return "low"
    if c < mid:
        return "mid"
    return "high"


def format_events(
    events: Sequence[KgSourceEvent],
    scores: dict[str, float],
    limit: int,
    *,
    extra_by_event_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not events or not scores:
        return []
    event_map = {str(ev.id): ev for ev in events}
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    results: list[dict[str, Any]] = []
    for eid, score in ranked[:limit]:
        ev = event_map.get(str(eid))
        if not ev:
            continue
        item: dict[str, Any] = {
            "id": str(ev.id),
            "title": ev.title,
            "summary": ev.summary,
            "content": ev.content,
            "document_id": str(ev.document_id) if ev.document_id else None,
            "chunk_id": str(ev.chunk_id) if ev.chunk_id else None,
            "score": score,
        }
        if extra_by_event_id is not None:
            extra = extra_by_event_id.get(str(ev.id))
            if isinstance(extra, dict) and extra:
                item.update(extra)

        results.append(item)
    return results
