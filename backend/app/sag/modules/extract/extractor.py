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
from app.sag.core.ai.factory import create_llm_client
from app.sag.modules.extract.config import ExtractConfig
from app.sag.modules.extract.processor import EventProcessor
from app.sag.modules.load.processor import DocumentProcessor
from app.sag.storage import EntityRepository, EventRepository
from app.sag.utils import get_logger

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
                        existing = session.execute(
                            select(SagEntity).where(
                                SagEntity.tenant_id == event_obj.tenant_id,
                                SagEntity.normalized_name == normalized,
                                SagEntity.type == ent_type,
                            )
                        ).scalar_one_or_none()
                        if existing:
                            entity_obj = existing
                        else:
                            entity_obj = SagEntity(
                                tenant_id=event_obj.tenant_id,
                                name=ent.get("name") or normalized,
                                normalized_name=normalized,
                                type=ent_type,
                                description=ent.get("description"),
                                vector=None,
                                extra_data=None,
                            )
                            session.add(entity_obj)
                            session.flush()

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
            return extracted_events
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
