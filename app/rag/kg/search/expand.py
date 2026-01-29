"""
Expand stage: multi-hop entity -> event expansion.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Set

from app.core.config import settings
from app.rag.kg.repository import EntityRepository, EventRepository, get_session
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.recall import RecallResult
from app.rag.kg.search.tracker import Tracker


@dataclass
class ExpandResult:
    key_final: List[Dict[str, Any]]
    event_ids: List[str]
    clues: List[Dict[str, Any]]
    event_scores: Dict[str, float]


class ExpandSearcher:
    def __init__(self):
        ...

    async def expand(self, config: SearchConfig, recall_result: RecallResult) -> ExpandResult:
        if not config.expand.enabled:
            return ExpandResult(
                key_final=recall_result.key_final,
                event_ids=recall_result.event_ids,
                clues=recall_result.clues,
                event_scores=recall_result.event_scores,
            )

        tracker = Tracker()
        tracker.extend_clues(list(recall_result.clues or []))

        session = get_session()
        try:
            entity_repo = EntityRepository(session)
            event_repo = EventRepository(session)
            tenant_id = config.tenant_id or settings.DEFAULT_TENANT_ID

            known_entities: Set[str] = {e["entity_id"] for e in recall_result.key_final if e.get("entity_id")}
            entity_weights = dict(recall_result.key_weights)
            discovered_events: List[str] = list(recall_result.event_ids or [])
            discovered_event_ids: Set[str] = set(discovered_events)
            current_entities = [e["entity_id"] for e in (recall_result.key_final or []) if e.get("entity_id")]
            max_candidates = max(0, int(getattr(settings, "KG_SEARCH_MAX_RERANK_CANDIDATES", 0) or 0))

            for hop in range(config.expand.max_hops):
                if not current_entities:
                    break
                if max_candidates > 0 and len(discovered_event_ids) >= max_candidates:
                    break

                limit = int(config.expand.max_events_per_hop)
                if max_candidates > 0:
                    remaining = max(0, int(max_candidates) - int(len(discovered_event_ids)))
                    if remaining <= 0:
                        break
                    limit = max(1, min(limit, remaining))

                events = event_repo.find_events_by_entities(
                    current_entities,
                    tenant_id=tenant_id,
                    limit=limit,
                    document_ids=config.document_ids,
                )
                new_event_ids: List[str] = []
                for ev in events:
                    ev_id = str(ev.id)
                    if ev_id in discovered_event_ids:
                        continue
                    discovered_event_ids.add(ev_id)
                    new_event_ids.append(ev_id)
                if not new_event_ids:
                    break
                discovered_events.extend(new_event_ids)
                if max_candidates > 0 and len(discovered_event_ids) >= max_candidates:
                    break

                # score new events using existing entity weights
                assoc_map = event_repo.get_entities_for_events(new_event_ids, tenant_id=tenant_id)
                for ev in events:
                    ev_id = str(ev.id)
                    base = recall_result.event_scores.get(ev_id, 0.0)
                    boost = sum(
                        entity_weights.get(str(ent.id), 0.0) for ent in assoc_map.get(ev_id, [])
                    )
                    recall_result.event_scores[ev_id] = base * 0.5 + boost * 0.5

                # collect new entities from these events
                new_entities: Dict[str, float] = {}
                events_by_id = {str(ev.id): ev for ev in events}
                for ev_id, ents in assoc_map.items():
                    for ent in ents:
                        ent_id = str(ent.id)
                        if ent_id in known_entities:
                            continue
                        weight = recall_result.event_scores.get(ev_id, 0.0)
                        new_entities[ent_id] = new_entities.get(ent_id, 0.0) + weight
                        tracker.add_clue(
                            stage=f"expand-hop-{hop+1}",
                            from_node=Tracker.build_event_node(
                                events_by_id.get(ev_id) or {"id": ev_id},
                                stage=f"expand-hop-{hop+1}",
                                hop=hop + 1,
                            ),
                            to_node=Tracker.build_entity_node(
                                {"entity_id": ent_id, "name": ent.name, "type": ent.type, "hop": hop + 1}
                            ),
                            confidence=0.3,
                            relation="event->entity",
                            metadata={"step": f"hop-{hop+1}"},
                        )

                sorted_new = sorted(new_entities.items(), key=lambda x: x[1], reverse=True)
                sorted_new = sorted_new[: config.expand.entities_per_hop]
                if not sorted_new:
                    break

                current_entities = []
                for ent_id, w in sorted_new:
                    known_entities.add(ent_id)
                    entity_weights[ent_id] = entity_weights.get(ent_id, 0.0) * 0.5 + w * 0.5
                    current_entities.append(ent_id)

                min_events = int(getattr(config.expand, "min_events_per_hop", 0) or 0)
                if min_events > 0 and len(new_event_ids) < min_events:
                    break

            # build key_final list
            key_final: List[Dict[str, Any]] = []
            ent_objects = entity_repo.get_entities_by_ids(list(known_entities), tenant_id=tenant_id)
            for ent in ent_objects:
                key_final.append(
                    {
                        "entity_id": str(ent.id),
                        "name": ent.name,
                        "type": ent.type,
                        "weight": entity_weights.get(str(ent.id), 0.0),
                    }
                )
            key_final.sort(key=lambda x: x["weight"], reverse=True)
            key_final = key_final[: config.recall.final_entity_count]

            return ExpandResult(
                key_final=key_final,
                event_ids=discovered_events,
                clues=tracker.get_clues(),
                event_scores=recall_result.event_scores,
            )
        finally:
            session.close()
