"""
Event extractor coordinating LLM + embeddings + persistence.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.core.database import SessionLocal
from app.models.document import DocumentChunk
from app.kg.models import SagEventEntity, SagSourceEvent
from app.ai.factory import create_llm_client
from app.kg.extraction.config import ExtractConfig
from app.kg.extraction.processor import EventProcessor
from app.kg.loading.processor import DocumentProcessor
from app.kg.repository import EntityRepository, EventRepository
from app.kg.utils import get_logger

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

            embed_cache: Dict[str, List[float]] = {}
            entity_cache: Dict[Tuple[str, str, str], Any] = {}
            extracted_events: List[SagSourceEvent] = []
            for idx, chunk in enumerate(chunks, 1):
                events_data = await processor.extract_from_sections([chunk], batch_index=idx)
                if not events_data:
                    continue

                # Pre-embed all event/entity texts in this chunk (batch + cache)
                to_embed: List[str] = []
                seen = set(embed_cache.keys())

                for ev in events_data:
                    ev_text = (ev.get("content") or ev.get("summary") or ev.get("title") or "").strip()
                    if not ev_text:
                        ev_text = (chunk.content or "")[:200].strip() or "Event"
                    ev["_embed_text"] = ev_text
                    if ev_text and ev_text not in seen:
                        seen.add(ev_text)
                        to_embed.append(ev_text)

                    for ent in ev.get("entities") or []:
                        name = (ent.get("name") or "").strip()
                        desc = (ent.get("description") or "").strip()
                        ent_text = (f"{name} {desc}").strip() if desc else name
                        ent["_embed_text"] = ent_text
                        if ent_text and ent_text not in seen:
                            seen.add(ent_text)
                            to_embed.append(ent_text)

                if to_embed:
                    vectors = await embedder.generate_batch(to_embed)
                    for text, vector in zip(to_embed, vectors):
                        embed_cache[text] = vector

                # Persist events/entities/links
                for ev in events_data:
                    title = (ev.get("title") or "").strip()
                    summary = (ev.get("summary") or "").strip()
                    content = (ev.get("content") or "").strip()

                    if not title:
                        title = (summary[:50] if summary else (chunk.content or "")[:50]).strip() or "Event"
                    if not content:
                        content = (summary or chunk.content or "Event").strip()
                    if not summary:
                        summary = (content[:200] if content else "Event").strip() or "Event"

                    ev_text = str(ev.get("_embed_text") or content)
                    vector = embed_cache.get(ev_text)

                    event_obj = SagSourceEvent(
                        tenant_id=config.tenant_id or chunk.tenant_id,
                        document_id=chunk.document_id,
                        chunk_id=chunk.id,
                        title=title,
                        summary=summary,
                        content=content,
                        content_vector=vector,
                        references={"chunk_index": chunk.chunk_index, "page": chunk.page_number},
                    )
                    session.add(event_obj)
                    extracted_events.append(event_obj)

                    for ent in ev.get("entities") or []:
                        name = (ent.get("name") or "").strip()
                        if not name:
                            continue

                        normalized = (ent.get("normalized_name") or name.lower()).strip()
                        ent_type = (ent.get("type") or "unknown").strip() or "unknown"
                        cache_key = (str(event_obj.tenant_id), normalized, ent_type)

                        entity_obj = entity_cache.get(cache_key)
                        if entity_obj is None:
                            entity_obj = entity_repo.get_or_create(
                                tenant_id=event_obj.tenant_id,
                                name=name or normalized,
                                normalized_name=normalized,
                                type_=ent_type,
                                description=(ent.get("description") or "").strip() or None,
                                commit=False,
                            )
                            entity_cache[cache_key] = entity_obj

                        if not getattr(entity_obj, "vector", None):
                            ent_text = str(ent.get("_embed_text") or name)
                            entity_vec = embed_cache.get(ent_text)
                            if entity_vec:
                                entity_obj.vector = entity_vec

                        session.add(
                            SagEventEntity(
                                event=event_obj,
                                entity=entity_obj,
                                weight=1.0,
                                role=ent.get("role"),
                            )
                        )

            session.commit()

            # Push vectors to Milvus (avoid duplicate embedding work)
            event_repo.push_events_to_milvus(extracted_events)
            entity_repo.push_entities_to_milvus(list(entity_cache.values()))
            return extracted_events
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
