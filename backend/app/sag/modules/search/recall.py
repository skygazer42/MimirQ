"""
Recall stage: query -> entities -> events (entity + content) with weights and clues.
"""
from dataclasses import dataclass
from typing import Any, Dict, List

from app.core.config import settings
from app.sag.modules.load.processor import DocumentProcessor
from app.sag.modules.search.config import SearchConfig
from app.sag.modules.search.tracker import Tracker
from app.sag.storage import EntityRepository, EventRepository, get_session
from app.sag.utils import get_logger

logger = get_logger("sag.search.recall")


@dataclass
class RecallResult:
    original_query: str
    key_final: List[Dict[str, Any]]
    event_ids: List[str]
    clues: List[Dict[str, Any]]
    key_weights: Dict[str, float]
    event_scores: Dict[str, float]


class RecallSearcher:
    def __init__(self):
        self.processor = DocumentProcessor()

    async def search(self, config: SearchConfig) -> RecallResult:
        tracker = Tracker()
        session = get_session()
        try:
            entity_repo = EntityRepository(session)
            event_repo = EventRepository(session)
            tenant_id = config.tenant_id or settings.DEFAULT_TENANT_ID

            # embed query
            query_vec = await self.processor.generate_embedding(config.query)

            # entity recall (vector)
            entities = entity_repo.search_similar(
                query_vector=query_vec,
                tenant_id=tenant_id,
                k=config.recall.vector_candidates,
            )
            entities = [
                e for e in entities if e.get("similarity", 0.0) >= config.recall.entity_similarity_threshold
            ][: config.recall.max_entities]

            # clues for entities
            for ent in entities:
                tracker.add_clue(
                    stage="recall",
                    from_node=tracker.build_query_node(config),
                    to_node=tracker.build_entity_node(ent),
                    confidence=ent.get("similarity", 0.0),
                )

            # weight entities (normalize similarities)
            key_weights: Dict[str, float] = {}
            if entities:
                sims = [e.get("similarity", 0.0) for e in entities]
                mx = max(sims) or 1.0
                for ent in entities:
                    key_weights[ent["entity_id"]] = ent.get("similarity", 0.0) / mx

            # events via entities
            event_ids_from_entities = event_repo.search_events_by_entities(
                [e["entity_id"] for e in entities],
                tenant_id=tenant_id,
                limit=config.recall.vector_candidates,
            )

            # events via content
            content_results = event_repo.search_similar_by_content(
                query_vector=query_vec,
                tenant_id=tenant_id,
                k=config.recall.vector_candidates,
            )
            event_ids_from_content = [
                item["event_id"]
                for item in content_results
                if item.get("similarity", 0.0) >= config.recall.event_similarity_threshold
            ]

            # merge events
            merged_event_ids = list(
                dict.fromkeys(event_ids_from_entities + event_ids_from_content)
            )[: config.recall.max_events]

            # score events
            events_detail = event_repo.get_events_by_ids(merged_event_ids)
            event_scores: Dict[str, float] = {}
            for ev in events_detail:
                sim = 0.0
                if ev.content_vector:
                    sim = self._cosine(query_vec, ev.content_vector)
                # boost by matched entity count
                assoc = event_repo.get_event_entities([str(ev.id)]).get(str(ev.id), [])
                boost = sum(
                    key_weights.get(str(link.entity_id), 0.0) for link in assoc
                )
                event_scores[str(ev.id)] = sim * 0.6 + boost * 0.4

            # sort by score
            merged_event_ids.sort(
                key=lambda eid: event_scores.get(str(eid), 0.0), reverse=True
            )

            key_final = [
                e
                for e in entities
                if key_weights.get(e["entity_id"], 0.0) >= config.recall.entity_weight_threshold
            ][: config.recall.final_entity_count]

            return RecallResult(
                original_query=config.query,
                key_final=key_final,
                event_ids=merged_event_ids,
                clues=tracker.get_clues(),
                key_weights=key_weights,
                event_scores=event_scores,
            )
        finally:
            session.close()

    def _cosine(self, a: List[float], b: List[float]) -> float:
        import math

        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)
