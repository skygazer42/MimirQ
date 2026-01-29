
from typing import Any, Dict, List, Sequence

from app.rag.kg.models import KgSourceEvent


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def format_events(
    events: Sequence[KgSourceEvent],
    scores: Dict[str, float],
    limit: int,
) -> List[Dict[str, Any]]:
    if not events or not scores:
        return []
    event_map = {str(ev.id): ev for ev in events}
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    results: List[Dict[str, Any]] = []
    for eid, score in ranked[:limit]:
        ev = event_map.get(str(eid))
        if not ev:
            continue
        results.append(
            {
                "id": str(ev.id),
                "title": ev.title,
                "summary": ev.summary,
                "content": ev.content,
                "document_id": str(ev.document_id) if ev.document_id else None,
                "chunk_id": str(ev.chunk_id) if ev.chunk_id else None,
                "score": score,
            }
        )
    return results
