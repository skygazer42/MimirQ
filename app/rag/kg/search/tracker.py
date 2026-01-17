"""
Clue tracker with normalized node formats for query/entity/event.
"""
import uuid
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.rag.kg.search.config import SearchConfig


class Tracker:
    def __init__(self):
        self.clues: List[Dict[str, Any]] = []
        self.clues_dropped: int = 0
        self._clues_enabled: bool = bool(getattr(settings, "KG_SEARCH_CLUES_ENABLED", True))
        self._max_clues: int = max(0, int(getattr(settings, "KG_SEARCH_MAX_CLUES", 0) or 0))

    def extend_clues(self, clues: List[Dict[str, Any]]) -> None:
        if not self._clues_enabled:
            return
        if not clues:
            return
        if self._max_clues <= 0:
            self.clues.extend(clues)
            return

        remaining = self._max_clues - len(self.clues)
        if remaining <= 0:
            self.clues_dropped += len(clues)
            return

        if len(clues) <= remaining:
            self.clues.extend(clues)
            return

        self.clues.extend(clues[:remaining])
        self.clues_dropped += len(clues) - remaining

    @staticmethod
    def _uuid_from_text(prefix: str, text: str) -> str:
        return f"{prefix}-{uuid.uuid5(uuid.NAMESPACE_DNS, text)}"

    @staticmethod
    def _truncate_text(text: Any) -> str:  # noqa: ANN401
        s = "" if text is None else str(text)
        max_chars = max(0, int(getattr(settings, "KG_SEARCH_NODE_TEXT_MAX_CHARS", 0) or 0))
        if max_chars <= 0 or len(s) <= max_chars:
            return s
        return s[:max_chars]

    @staticmethod
    def build_query_node(config: SearchConfig, use_origin: bool = False) -> Dict[str, Any]:
        query_text = config.original_query if (use_origin and config.original_query) else config.query
        return {
            "id": Tracker._uuid_from_text("query", query_text),
            "type": "query",
            "category": "origin" if use_origin else "rewrite",
            "content": Tracker._truncate_text(query_text),
            "description": "original query" if use_origin else "working query",
        }

    @staticmethod
    def build_entity_node(entity: Dict[str, Any]) -> Dict[str, Any]:
        ent_id = entity.get("entity_id") or entity.get("id") or Tracker._uuid_from_text(
            "entity", entity.get("name", "unknown")
        )
        return {
            "id": ent_id,
            "type": "entity",
            "category": entity.get("type", "unknown"),
            "content": Tracker._truncate_text(entity.get("name", "")),
            "description": Tracker._truncate_text(entity.get("description", "")),
            "hop": entity.get("hop", 0),
        }

    @staticmethod
    def build_event_node(event: Any, stage: Optional[str] = None, hop: Optional[int] = None) -> Dict[str, Any]:
        ev_id = getattr(event, "id", None) or event.get("id") if isinstance(event, dict) else None  # type: ignore
        title = getattr(event, "title", None) or (event.get("title") if isinstance(event, dict) else "")
        content = getattr(event, "content", None) or getattr(event, "summary", None) or (
            event.get("content") if isinstance(event, dict) else ""
        )
        node_id = f"{stage}_{ev_id}" if stage and ev_id else ev_id or Tracker._uuid_from_text("event", title or "")
        return {
            "id": node_id,
            "event_id": str(ev_id) if ev_id else None,
            "type": "event",
            "category": stage or "event",
            "content": Tracker._truncate_text(title or ""),
            "description": Tracker._truncate_text(content or ""),
            "hop": hop,
        }

    def add_clue(
        self,
        stage: str,
        from_node: Dict[str, Any],
        to_node: Dict[str, Any],
        confidence: float = 0.0,
        relation: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._clues_enabled:
            return
        if self._max_clues > 0 and len(self.clues) >= self._max_clues:
            self.clues_dropped += 1
            return
        self.clues.append(
            {
                "id": str(uuid.uuid4()),
                "stage": stage,
                "from": from_node,
                "to": to_node,
                "confidence": confidence,
                "relation": relation,
                "metadata": metadata or {},
            }
        )

    def get_clues(self) -> List[Dict[str, Any]]:
        return self.clues
