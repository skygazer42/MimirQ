"""
Event extractor coordinating LLM + embeddings + persistence.
"""

import asyncio
import time
from typing import Dict, List, Optional, Sequence, Tuple

from app.core.config import settings
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
from app.services.prompt_resolver import resolve_prompt_template
from app.services.metrics_logger import log_metrics

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
        t0 = time.perf_counter()
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

            tenant_id = config.tenant_id or resolved_chunks[0].tenant_id
            prompt_template_content: str | None = None
            chosen_template_id: str | None = None
            if config.prompt_template_id or config.prompt_template_key or config.prompt_ab_experiment_key:
                chosen = resolve_prompt_template(
                    db=session,
                    tenant_id=tenant_id,
                    prompt_template_id=config.prompt_template_id,
                    template_key=config.prompt_template_key,
                    ab_experiment_key=config.prompt_ab_experiment_key,
                    ab_user_key=config.ab_user_key,
                )
                if chosen and chosen.content:
                    prompt_template_content = str(chosen.content).strip() or None
                    chosen_template_id = str(chosen.id)
                    try:
                        chosen.usage_count += 1
                        session.commit()
                    except Exception:
                        session.rollback()
                        logger.warning("Failed to update kg extract prompt usage_count for template %s", chosen_template_id)

            llm_client = await create_llm_client(scenario="extract", model_config=self.model_config)
            processor = EventProcessor(llm_client=llm_client, prompt_template=prompt_template_content)
            embedder = DocumentProcessor()

            max_concurrency = max(
                1,
                int(getattr(settings, "KG_EXTRACT_MAX_CONCURRENCY", 0) or 0) or int(getattr(config, "max_concurrency", 3) or 3),
            )
            max_events_per_chunk = max(1, int(getattr(settings, "KG_EXTRACT_MAX_EVENTS_PER_CHUNK", 6) or 6))
            max_entities_per_event = max(1, int(getattr(settings, "KG_EXTRACT_MAX_ENTITIES_PER_EVENT", 30) or 30))
            embed_batch_size = max(1, int(getattr(settings, "KG_EXTRACT_EMBED_BATCH_SIZE", 128) or 128))

            sem = asyncio.Semaphore(max_concurrency)
            failed_chunks = 0

            async def _extract_one(chunk: DocumentChunk, *, batch_index: int) -> Tuple[DocumentChunk, List[Dict]]:
                nonlocal failed_chunks
                text = (chunk.content or "").strip()
                if not text:
                    return chunk, []
                try:
                    async with sem:
                        data = await processor.extract_from_sections([chunk], batch_index=batch_index)
                    return chunk, data if isinstance(data, list) else []
                except Exception as exc:  # noqa: BLE001
                    failed_chunks += 1
                    logger.warning("KG extract failed for chunk %s: %s", getattr(chunk, "id", ""), str(exc)[:200])
                    return chunk, []

            extracted: List[Tuple[DocumentChunk, List[Dict]]] = []
            group_size = max(1, max_concurrency * 4)
            for offset in range(0, len(resolved_chunks), group_size):
                group = resolved_chunks[offset : offset + group_size]
                results = await asyncio.gather(
                    *[_extract_one(ch, batch_index=offset + i + 1) for i, ch in enumerate(group)],
                )
                extracted.extend(results)

            # Build normalized events first, then embed in batch.
            processed_events: List[Tuple[DocumentChunk, Dict]] = []
            for chunk, events_data in extracted:
                if not events_data:
                    continue

                # Cap and deduplicate events *within the same chunk* (avoid LLM duplicates).
                seen_keys: set[tuple[str, str]] = set()
                kept = 0
                for ev in events_data:
                    if not isinstance(ev, dict):
                        continue
                    if kept >= max_events_per_chunk:
                        break

                    title = (ev.get("title") or "").strip()
                    summary = (ev.get("summary") or "").strip()
                    content = (ev.get("content") or "").strip()

                    if not title:
                        title = (summary[:50] if summary else (chunk.content or "")[:50]).strip() or "Event"
                    if not content:
                        content = (summary or chunk.content or "Event").strip()
                    if not summary:
                        summary = (content[:200] if content else "Event").strip() or "Event"

                    key = (title.casefold(), summary.casefold())
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)

                    entities = ev.get("entities") if isinstance(ev.get("entities"), list) else []
                    entities = [e for e in entities if isinstance(e, dict)]
                    if len(entities) > max_entities_per_event:
                        entities = entities[:max_entities_per_event]

                    processed_events.append(
                        (
                            chunk,
                            {
                                "title": title,
                                "summary": summary,
                                "content": content,
                                "entities": entities,
                            },
                        )
                    )
                    kept += 1

            embed_cache: Dict[str, List[float]] = {}

            def _iter_batches(items: List[str], size: int):
                for i in range(0, len(items), size):
                    yield items[i : i + size]

            to_embed: List[str] = []
            seen_text: set[str] = set()
            for chunk, ev in processed_events:
                ev_text = (ev.get("content") or ev.get("summary") or ev.get("title") or "").strip()
                if not ev_text:
                    ev_text = (chunk.content or "")[:200].strip() or "Event"
                ev["_embed_text"] = ev_text
                if ev_text and ev_text not in seen_text:
                    seen_text.add(ev_text)
                    to_embed.append(ev_text)

                for ent in ev.get("entities") or []:
                    name = (ent.get("name") or "").strip()
                    desc = (ent.get("description") or "").strip()
                    ent_text = (f"{name} {desc}").strip() if desc else name
                    ent["_embed_text"] = ent_text
                    if ent_text and ent_text not in seen_text:
                        seen_text.add(ent_text)
                        to_embed.append(ent_text)

            if to_embed:
                try:
                    for batch in _iter_batches(to_embed, embed_batch_size):
                        vectors = await embedder.generate_batch(batch)
                        for text, vector in zip(batch, vectors):
                            if vector:
                                embed_cache[text] = vector
                except Exception as exc:  # noqa: BLE001
                    logger.warning("KG embedding batch failed; proceeding without vectors: %s", str(exc)[:200])
                    embed_cache = {}

            events_to_index: List[IndexRecord] = []
            entity_total = 0
            for chunk, ev in processed_events:
                vector = embed_cache.get(str(ev.get("_embed_text") or ""))

                entity_inputs: List[EventEntityInput] = []
                for ent in ev.get("entities") or []:
                    name = (ent.get("name") or "").strip()
                    if not name:
                        continue
                    normalized = (ent.get("normalized_name") or name).strip()
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
                entity_total += len(entity_inputs)

                refs: Dict[str, object] = {"chunk_index": chunk.chunk_index, "page": chunk.page_number}
                if getattr(chunk, "start_char", None) is not None:
                    refs["start_char"] = int(getattr(chunk, "start_char"))
                if getattr(chunk, "end_char", None) is not None:
                    refs["end_char"] = int(getattr(chunk, "end_char"))
                meta = getattr(chunk, "doc_metadata", None) or {}
                if isinstance(meta, dict):
                    for k in ("chunk_key", "content_hash", "source"):
                        v = meta.get(k)
                        if isinstance(v, str) and v.strip():
                            refs[k] = v.strip()

                events_to_index.append(
                    IndexRecord(
                        kind=IndexKind.EVENT,
                        title=str(ev.get("title") or "").strip() or "Event",
                        summary=str(ev.get("summary") or "").strip() or "Event",
                        content=str(ev.get("content") or "").strip() or "Event",
                        document_id=chunk.document_id,
                        chunk_id=chunk.id,
                        references=refs,
                        vector=vector,
                        entities=entity_inputs,
                        extra_data={
                            "kg_prompt_template_id": chosen_template_id,
                            "kg_prompt_template_key": config.prompt_template_key,
                            "kg_prompt_ab_experiment_key": config.prompt_ab_experiment_key,
                        },
                    )
                )

            if not events_to_index:
                return []

            indexer = Indexer(session)
            result = indexer.upsert(
                tenant_id=tenant_id,
                records=events_to_index,
                options=index_options,
            ).event_result

            events = result.events if result else []
            if events and bool(getattr(config, "replace_existing", False)):
                try:
                    indexer.delete_event_indexes_for_chunks(
                        tenant_id=tenant_id,
                        chunk_ids=config.chunk_ids,
                        exclude_event_ids=[ev.id for ev in events],
                        prune_orphan_entities=bool(getattr(config, "prune_orphan_entities", False)),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to cleanup previous KG events for chunks: %s", str(exc)[:200])

            elapsed = time.perf_counter() - t0
            log_metrics(
                {
                    "event": "kg.extract",
                    "chunk_count": len(resolved_chunks),
                    "event_count": len(events),
                    "entity_count": int(entity_total),
                    "failed_chunks": int(failed_chunks),
                    "max_concurrency": int(max_concurrency),
                    "elapsed_sec": round(float(elapsed), 3),
                }
            )
            return events
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
