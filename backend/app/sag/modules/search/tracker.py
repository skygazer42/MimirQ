"""
Clue tracker used to visualize recall/expand/rerank steps.
"""
from typing import Any, Dict, List


class Tracker:
    def __init__(self):
        self.clues: List[Dict[str, Any]] = []

    def add_clue(self, stage: str, from_node: Dict[str, Any], to_node: Dict[str, Any], confidence: float = 0.0, metadata: Dict[str, Any] | None = None):
        self.clues.append(
            {
                "stage": stage,
                "from": from_node,
                "to": to_node,
                "confidence": confidence,
                "metadata": metadata or {},
            }
        )

    @staticmethod
    def build_query_node(config) -> Dict[str, Any]:
        return {"type": "query", "id": "query", "label": config.query}

    @staticmethod
    def build_entity_node(entity: Dict[str, Any]) -> Dict[str, Any]:
        return {"type": "entity", "id": entity.get("entity_id") or entity.get("id"), "label": entity.get("name"), "entity_type": entity.get("type")}

    def get_clues(self) -> List[Dict[str, Any]]:
        return self.clues

