"""
Clue tracker with normalized node formats for query/entity/event.
"""
import uuid
from typing import Any, Dict, List, Optional

from third_party.sag.modules.search.config import SearchConfig


class Tracker:
    def __init__(self, config: Optional[SearchConfig] = None):
        self.config = config
        self.clues: List[Dict[str, Any]] = []

    @staticmethod
    def _uuid_from_text(prefix: str, text: str) -> str:
        return f"{prefix}-{uuid.uuid5(uuid.NAMESPACE_DNS, text)}"

    @staticmethod
    def build_query_node(config: SearchConfig, use_origin: bool = False) -> Dict[str, Any]:
        query_text = config.original_query if (use_origin and config.original_query) else config.query
        return {
            "id": Tracker._uuid_from_text("query", query_text),
            "type": "query",
            "category": "origin" if use_origin else "rewrite",
            "content": query_text,
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
            "content": entity.get("name", ""),
            "description": entity.get("description", ""),
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
            "content": title or "",
            "description": content or "",
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

