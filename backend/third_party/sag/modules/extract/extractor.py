"""
Event extractor coordinating LLM + embeddings + persistence.
"""
import asyncio
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.document import DocumentChunk
from app.models.sag_entities import SagEntity, SagEventEntity, SagSourceEvent
from third_party.sag.core.ai.factory import create_llm_client
from third_party.sag.modules.extract.config import ExtractConfig
from third_party.sag.modules.extract.processor import EventProcessor
from third_party.sag.modules.load.processor import DocumentProcessor
from third_party.sag.storage import EntityRepository, EventRepository
from third_party.sag.utils import get_logger

logger = get_logger("sag.extract.extractor")


class EventExtractor:
    """Orchestrates event extraction for a batch of chunks."""

    def __init__(self, model_config: Optional[dict] = None):
        self.model_config = model_config

    async def extract(self, config: ExtractConfig) -> List[SagSourceEvent]:
        session = SessionLocal()
        try:
            # Load chunks
            chunks = (
                session.query(DocumentChunk)
                .filter(DocumentChunk.id.in_(config.chunk_ids))
                .order_by(DocumentChunk.chunk_index)
                .all()
            )
            if not chunks:
                logger.warning("No chunks found for extraction")
                return []

            llm_client = await create_llm_client(scenario="extract", model_config=self.model_config)
            processor = EventProcessor(llm_client=llm_client)
            embedder = DocumentProcessor()

            entity_repo = EntityRepository(session)
            event_repo = EventRepository(session)

            extracted_events: List[SagSourceEvent] = []
            for idx, chunk in enumerate(chunks, 1):
                events_data = await processor.extract_from_sections([chunk], batch_index=idx)
                for ev in events_data:
                    vector = await embedder.generate_embedding(ev.get("content") or ev.get("summary") or ev.get("title", ""))
                    event_obj = SagSourceEvent(
                        tenant_id=config.tenant_id or chunk.tenant_id,
                        document_id=chunk.document_id,
                        chunk_id=chunk.id,
                        title=ev.get("title") or (chunk.content[:50] if chunk.content else "Event"),
                        summary=ev.get("summary") or ev.get("content") or (chunk.content[:200] if chunk.content else "Event"),
                        content=ev.get("content") or ev.get("summary") or (chunk.content or "Event"),
                        content_vector=vector,
                        references={"chunk_index": chunk.chunk_index, "page": chunk.page_number},
                    )
                    session.add(event_obj)
                    session.flush()  # to get id

                    # Upsert entities
                    links: List[SagEventEntity] = []
                    for ent in ev.get("entities") or []:
                        normalized = ent.get("normalized_name") or ent.get("name", "").lower()
                        ent_type = ent.get("type") or "unknown"
                        # embed entity name/desc
                        ent_vector = await embedder.generate_embedding(
                            (ent.get("name") or "") + " " + (ent.get("description") or "")
                        )
                        entity_obj = entity_repo.get_or_create(
                            tenant_id=event_obj.tenant_id,
                            name=ent.get("name") or normalized,
                            normalized_name=normalized,
                            type_=ent_type,
                            description=ent.get("description"),
                        )
                        if not entity_obj.vector:
                            entity_obj.vector = ent_vector
                            session.add(entity_obj)
                            session.commit()
                            session.refresh(entity_obj)
                        else:
                            # update vector if empty
                            pass

                        links.append(
                            SagEventEntity(
                                event_id=event_obj.id,
                                entity_id=entity_obj.id,
                                weight=1.0,
                                role=ent.get("role"),
                            )
                        )

                    extracted_events.append(event_obj)
                    if links:
                        for link in links:
                            session.add(link)

            session.commit()

            # Push vectors to Milvus
            event_repo.upsert_events(extracted_events)
            # collect entities that were linked
            entity_ids = set()
            for ev in extracted_events:
                for assoc in ev.associations:
                    entity_ids.add(assoc.entity_id)
            if entity_ids:
                entities_for_push = session.query(SagEntity).filter(SagEntity.id.in_(entity_ids)).all()
                if entities_for_push:
                    entity_repo.upsert_entities(entities_for_push)
            return extracted_events
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
