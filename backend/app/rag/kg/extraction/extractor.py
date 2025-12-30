"""
Event extractor coordinating LLM + embeddings + persistence.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from app.core.database import SessionLocal
from app.models.document import DocumentChunk
from app.rag.kg.models import KgSourceEvent
from app.rag.llm.factory import create_llm_client
from app.rag.kg.extraction.config import ExtractConfig
from app.rag.kg.extraction.processor import EventProcessor
from app.rag.kg.loading.processor import DocumentProcessor
from app.types.indexing import EventEntityInput, IndexKind, IndexRecord, IndexingOptions
from app.services.indexer import Indexer
from app.rag.kg.utils import get_logger

logger = get_logger("kg.extract.extractor")


class EventExtractor:
    """Orchestrates event extraction for a batch of chunks."""

    def __init__(self, model_config: Optional[dict] = None):
        self.model_config = model_config

    async def extract(
        self,
        config: ExtractConfig,
        *,
        chunks: Optional[Sequence[DocumentChunk]] = None,
        index_options: Optional[IndexingOptions] = None,
    ) -> List[KgSourceEvent]:
        session = SessionLocal()
        try:
            # Load chunks (or reuse provided ones to avoid duplicate DB reads)
            resolved_chunks: List[DocumentChunk]
            if chunks is None:
                resolved_chunks = (
                    session.query(DocumentChunk)
                    .filter(DocumentChunk.id.in_(config.chunk_ids))
                    .order_by(DocumentChunk.chunk_index)
                    .all()
                )
            else:
                resolved_chunks = list(chunks)
                resolved_chunks.sort(key=lambda c: c.chunk_index)

            if not resolved_chunks:
                logger.warning("No chunks found for extraction")
                return []

            llm_client = await create_llm_client(scenario="extract", model_config=self.model_config)
            processor = EventProcessor(llm_client=llm_client)
            embedder = DocumentProcessor()

            embed_cache: Dict[str, List[float]] = {}
            events_to_index: List[IndexRecord] = []
            for idx, chunk in enumerate(resolved_chunks, 1):
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

                # Build index inputs
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

                    entity_inputs: List[EventEntityInput] = []
                    for ent in ev.get("entities") or []:
                        name = (ent.get("name") or "").strip()
                        if not name:
                            continue

                        normalized = (ent.get("normalized_name") or name.lower()).strip()
                        ent_type = (ent.get("type") or "unknown").strip() or "unknown"
                        ent_text = str(ent.get("_embed_text") or name)
                        entity_vec = embed_cache.get(ent_text)
                        entity_inputs.append(
                            EventEntityInput(
                                name=name,
                                normalized_name=normalized,
                                type=ent_type,
                                description=(ent.get("description") or "").strip() or None,
                                vector=entity_vec,
                                role=ent.get("role"),
                            )
                        )

                    events_to_index.append(
                        IndexRecord(
                            kind=IndexKind.EVENT,
                            title=title,
                            summary=summary,
                            content=content,
                            document_id=chunk.document_id,
                            chunk_id=chunk.id,
                            references={"chunk_index": chunk.chunk_index, "page": chunk.page_number},
                            vector=vector,
                            entities=entity_inputs,
                        )
                    )

            if not events_to_index:
                return []

            tenant_id = config.tenant_id or resolved_chunks[0].tenant_id
            result = Indexer(session).upsert(
                tenant_id=tenant_id,
                records=events_to_index,
                options=index_options,
            ).event_result
            return result.events if result else []
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
