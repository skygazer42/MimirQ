"""
Expand stage: multi-hop entity → event expansion.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Set

from app.core.config import settings
from app.sag.modules.search.config import SearchConfig
from app.sag.modules.search.recall import RecallResult
from app.sag.modules.search.tracker import Tracker
from app.sag.storage import EntityRepository, EventRepository, get_session
from app.sag.utils import get_logger

logger = get_logger("sag.search.expand")


@dataclass
class ExpandResult:
    key_final: List[Dict[str, Any]]
    event_ids: List[str]
    clues: List[Dict[str, Any]]


class ExpandSearcher:
    def __init__(self):
        ...

    async def expand(self, config: SearchConfig, recall_result: RecallResult) -> ExpandResult:
        if not config.expand.enabled:
            return ExpandResult(
                key_final=recall_result.key_final,
                event_ids=recall_result.event_ids,
                clues=recall_result.clues,
            )

        tracker = Tracker()
        # carry previous clues
        for clue in recall_result.clues:
            tracker.clues.append(clue)

        session = get_session()
        try:
            entity_repo = EntityRepository(session)
            event_repo = EventRepository(session)
            tenant_id = config.tenant_id or settings.DEFAULT_TENANT_ID

            known_entities: Set[str] = {e["entity_id"] for e in recall_result.key_final}
            entity_weights = dict(recall_result.key_weights)
            discovered_events: List[str] = list(recall_result.event_ids)

            current_entities = list(known_entities)

            for hop in range(config.expand.max_hops):
                if not current_entities:
                    break

                events = event_repo.find_events_by_entities(
                    current_entities,
                    tenant_id=tenant_id,
                    limit=config.expand.max_events_per_hop,
                )
                new_event_ids = [str(e.id) for e in events if str(e.id) not in discovered_events]
                if not new_event_ids:
                    break
                discovered_events.extend(new_event_ids)

                # collect new entities from these events
                assoc_map = event_repo.get_entities_for_events(new_event_ids)
                new_entities: List[str] = []
                for ev_id, ents in assoc_map.items():
                    for ent in ents:
                        ent_id = str(ent.id)
                        if ent_id in known_entities:
                            continue
                        new_entities.append(ent_id)
                        tracker.add_clue(
                            stage=f"expand-hop-{hop+1}",
                            from_node={"type": "event", "id": ev_id, "label": "event"},
                            to_node=tracker.build_entity_node(
                                {"entity_id": ent_id, "name": ent.name, "type": ent.type}
                            ),
                            confidence=0.3,
                        )
                        entity_weights[ent_id] = entity_weights.get(ent_id, 0.0) + 0.3

                new_entities = new_entities[: config.expand.entities_per_hop]
                if not new_entities:
                    break
                known_entities.update(new_entities)
                current_entities = new_entities

            # build key_final list
            key_final: List[Dict[str, Any]] = []
            ent_objects = entity_repo.get_entities_by_ids(list(known_entities))
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
            )
        finally:
            session.close()
