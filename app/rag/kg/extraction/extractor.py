"""
Event extractor coordinating LLM + embeddings + persistence.
"""

import asyncio
import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import DocumentChunk
from app.rag.kg.extraction.alias import (
    best_suffix_match,
    choose_alias_direction,
    extract_alias_candidates,
    is_abbrev_token,
    split_trailing_parenthetical_alias,
)
from app.rag.kg.extraction.config import ExtractConfig
from app.rag.kg.extraction.parser import EntityValueParser
from app.rag.kg.extraction.processor import EventProcessor
from app.rag.kg.extraction.relation_processor import CandidateEntity, RelationProcessor
from app.rag.kg.extraction.skill_processor import SkillProcessor
from app.rag.kg.loading.processor import DocumentProcessor
from app.rag.kg.models import KgEventEntity, KgRelation, KgSourceEvent
from app.rag.kg.provenance import build_event_entity_provenance
from app.rag.kg.repository import RelationRepository
from app.rag.kg.utils import get_logger
from app.rag.llm.factory import create_llm_client
from app.rag.preprocessing.normalization import normalize_text
from app.services.indexer import Indexer
from app.services.metrics_logger import log_metrics
from app.services.prompt_resolver import resolve_prompt_template
from app.types.indexing import EventEntityInput, IndexingOptions, IndexKind, IndexRecord

logger = get_logger("kg.extract.extractor")

_PROMPT_SELECTOR_KEYS = (
    "kg_prompt_template_id",
    "kg_prompt_template_key",
    "kg_prompt_ab_experiment_key",
)

# Predicate allowlist v1: keep ontology compact and map everything else to "unknown".
# This list is intentionally small; we can expand or make it DB-driven later.
_DEFAULT_RELATION_PREDICATES: tuple[str, ...] = (
    "alias_of",
    "same_as",
    "is_a",
    "part_of",
    "has_part",
    "member_of",
    "located_in",
    "works_for",
    "works_with",
    "reports_to",
    "owns",
    "owned_by",
    "created_by",
    "authored_by",
    "uses",
    "depends_on",
    "implements",
    "supports",
    "causes",
    "affects",
    "treats",
    "related_to",
)


def _normalize_prompt_selector_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _compute_content_stats(text: str) -> tuple[str, int]:
    normalized = normalize_text(text or "", normalize_line_endings=True, remove_control_chars=True)
    stripped = (normalized or "").strip()
    return hashlib.sha256(stripped.encode("utf-8", "ignore")).hexdigest(), int(len(stripped))


def _is_chunk_unchanged(
    prior_events: Sequence[KgSourceEvent],
    *,
    content_hash: str,
    prompt_selector_expected: dict[str, str],
) -> bool:
    if not prior_events:
        return False
    if not isinstance(content_hash, str) or not content_hash.strip():
        return False

    for ev in prior_events:
        refs = ev.references if isinstance(getattr(ev, "references", None), dict) else {}
        prior_hash = (refs.get("content_hash") or "").strip() if isinstance(refs, dict) else ""
        if not prior_hash or prior_hash != content_hash:
            return False

        extra = getattr(ev, "extra_data", None)
        if not isinstance(extra, dict):
            return False
        for key in _PROMPT_SELECTOR_KEYS:
            if _normalize_prompt_selector_value(extra.get(key)) != prompt_selector_expected.get(key, ""):
                return False

    return True


def _canonicalize_entities_for_chunk(
    entities: list[dict],
    *,
    chunk_text: str,
    max_entities: int,
    parser: EntityValueParser,
) -> list[dict]:
    """
    Best-effort entity canonicalization to reduce fragmentation:
    - "Long Form (ABBR)" becomes two entities: "Long Form" and "ABBR"
    - Only triggers when the chunk text contains both surfaces (evidence guard).
    """
    if not entities:
        return []
    if not bool(getattr(settings, "KG_ENTITY_CANONICALIZE_PARENTHESES_ALIAS", True)):
        return entities[: max(0, int(max_entities or 0))] if max_entities else list(entities)

    lim = max(0, int(max_entities or 0))
    if lim <= 0:
        return []

    text_raw = str(chunk_text or "")
    text_fold = text_raw.casefold()

    expanded: list[dict] = []
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        raw_name = str(ent.get("name") or "").strip()
        if not raw_name:
            continue
        raw_type = str(ent.get("type") or "unknown").strip() or "unknown"
        ent_type = parser.normalize_type(raw_type)
        desc = str(ent.get("description") or "").strip()
        role = ent.get("role")

        split = split_trailing_parenthetical_alias(raw_name)
        if split:
            head, tail = split
            direction = choose_alias_direction(head, tail)
            if direction:
                alias_surface, canonical_surface = direction
                alias_fold = alias_surface.casefold()
                canon_fold = canonical_surface.casefold()
                if canon_fold in text_fold and alias_fold in text_fold:
                    expanded.append(
                        {
                            "name": canonical_surface,
                            "normalized_name": parser.normalize_name(canonical_surface),
                            "type": ent_type,
                            "description": desc,
                            "role": role,
                        }
                    )
                    expanded.append(
                        {
                            "name": alias_surface,
                            "normalized_name": parser.normalize_name(alias_surface),
                            "type": ent_type,
                            "description": "",
                            "role": role,
                        }
                    )
                    continue

        expanded.append(
            {
                "name": raw_name,
                "normalized_name": str(ent.get("normalized_name") or parser.normalize_name(raw_name)).strip(),
                "type": ent_type,
                "description": desc,
                "role": role,
            }
        )

    # Dedupe while preserving order; keep longer descriptions.
    deduped: list[dict] = []
    seen: dict[tuple[str, str], dict] = {}
    for ent in expanded:
        etype = str(ent.get("type") or "unknown").strip() or "unknown"
        norm = str(ent.get("normalized_name") or "").strip()
        name = str(ent.get("name") or "").strip()
        if not name or not norm:
            continue
        key = (etype, norm)
        existing = seen.get(key)
        if existing is None:
            seen[key] = ent
            deduped.append(ent)
            continue
        if len(str(ent.get("description") or "")) > len(str(existing.get("description") or "")):
            existing["description"] = ent.get("description") or ""

    return deduped[:lim]


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
            chunk_timeout_sec = float(getattr(settings, "KG_EXTRACT_CHUNK_TIMEOUT_SEC", 0) or 0)
            if chunk_timeout_sec < 0:
                chunk_timeout_sec = 0.0

            context_window = int(getattr(settings, "KG_EXTRACT_CONTEXT_WINDOW_CHUNKS", 0) or 0)
            context_window = max(0, min(context_window, 20))

            min_chars = max(0, int(getattr(settings, "KG_EXTRACT_MIN_CHARS", 0) or 0))
            chunk_max_retries = max(0, int(getattr(settings, "KG_EXTRACT_CHUNK_MAX_RETRIES", 0) or 0))
            retry_backoff_sec = float(getattr(settings, "KG_EXTRACT_CHUNK_RETRY_BACKOFF_SEC", 0.5) or 0.5)
            if retry_backoff_sec < 0:
                retry_backoff_sec = 0.0

            replace_existing = bool(getattr(config, "replace_existing", False))
            skip_unchanged = bool(getattr(settings, "KG_EXTRACT_SKIP_UNCHANGED_CHUNKS", False)) and bool(replace_existing)

            # Per-request overrides (if provided) take precedence over global settings.
            extract_relations_enabled: bool
            if config.extract_relations is None:
                extract_relations_enabled = bool(getattr(settings, "KG_RELATION_ENABLED", False))
            else:
                extract_relations_enabled = bool(config.extract_relations)

            extract_skills_enabled: bool
            if config.extract_skills is None:
                extract_skills_enabled = bool(getattr(settings, "KG_SKILL_ENABLED", False))
            else:
                extract_skills_enabled = bool(config.extract_skills)

            failed_chunks = 0
            timed_out_chunks = 0
            timeout_chunk_ids: set[object] = set()
            failed_chunk_ids: set[object] = set()
            succeeded_chunk_ids: set[object] = set()
            skipped_chunk_ids: set[object] = set()
            skipped_short_chunk_ids: set[object] = set()
            retry_chunk_ids: set[object] = set()
            retry_attempts_total = 0
            llm_called_chunk_ids: set[object] = set()

            prompt_selector_expected = {
                "kg_prompt_template_id": _normalize_prompt_selector_value(chosen_template_id),
                "kg_prompt_template_key": _normalize_prompt_selector_value(config.prompt_template_key),
                "kg_prompt_ab_experiment_key": _normalize_prompt_selector_value(config.prompt_ab_experiment_key),
            }

            # Ensure chunk hashes/keys exist even if upstream parsing didn't inject them.
            chunk_hash_by_id: dict[object, str] = {}
            chunk_key_by_id: dict[object, str] = {}
            chunk_len_by_id: dict[object, int] = {}
            for ch in resolved_chunks:
                meta = getattr(ch, "doc_metadata", None)
                meta_dict = meta if isinstance(meta, dict) else {}
                raw_hash = meta_dict.get("content_hash")
                content_hash = raw_hash.strip() if isinstance(raw_hash, str) and raw_hash.strip() else ""
                raw_len = meta_dict.get("content_len")
                content_len: int | None
                try:
                    content_len = int(raw_len) if raw_len is not None else None
                except Exception:
                    content_len = None

                computed_digest = ""
                computed_len = 0
                if not content_hash or content_len is None:
                    computed_digest, computed_len = _compute_content_stats(getattr(ch, "content", "") or "")
                if not content_hash:
                    content_hash = computed_digest
                if content_len is None:
                    content_len = computed_len

                chunk_hash_by_id[ch.id] = content_hash
                chunk_len_by_id[ch.id] = max(0, int(content_len))

                raw_key = meta_dict.get("chunk_key")
                chunk_key = raw_key.strip() if isinstance(raw_key, str) and raw_key.strip() else ""
                if not chunk_key:
                    chunk_key = str(getattr(ch, "chunk_index", "") or "")
                chunk_key_by_id[ch.id] = chunk_key

            # Incremental extraction: skip unchanged chunks when replace_existing + prompt selection matches.
            existing_events_by_chunk: dict[object, list[KgSourceEvent]] = {}
            kept_events: list[KgSourceEvent] = []
            if skip_unchanged:
                existing = (
                    session.query(KgSourceEvent)
                    .filter(
                        KgSourceEvent.tenant_id == tenant_id,
                        KgSourceEvent.chunk_id.in_([c.id for c in resolved_chunks]),
                    )
                    .all()
                )
                for ev in existing:
                    if not getattr(ev, "chunk_id", None):
                        continue
                    existing_events_by_chunk.setdefault(ev.chunk_id, []).append(ev)

                for ch in resolved_chunks:
                    prior = existing_events_by_chunk.get(ch.id) or []
                    if not prior:
                        continue
                    cur_hash = chunk_hash_by_id.get(ch.id) or ""
                    if not cur_hash:
                        continue

                    if _is_chunk_unchanged(prior, content_hash=cur_hash, prompt_selector_expected=prompt_selector_expected):
                        skipped_chunk_ids.add(ch.id)
                        kept_events.extend(prior)

            chunks_to_process: list[DocumentChunk] = [c for c in resolved_chunks if c.id not in skipped_chunk_ids]
            chunk_id_to_pos = {c.id: i for i, c in enumerate(resolved_chunks)}

            def _build_sections(target: DocumentChunk) -> list[DocumentChunk]:
                if context_window <= 0:
                    return [target]
                pos = chunk_id_to_pos.get(target.id)
                if pos is None:
                    return [target]

                sections: list[DocumentChunk] = [target]
                # Include nearest neighbors first (prev1, next1, prev2, next2, ...)
                for step in range(1, context_window + 1):
                    if pos - step >= 0:
                        sections.append(resolved_chunks[pos - step])
                    if pos + step < len(resolved_chunks):
                        sections.append(resolved_chunks[pos + step])
                return sections

            async def _extract_one(chunk: DocumentChunk, *, batch_index: int) -> Tuple[DocumentChunk, List[Dict]]:
                nonlocal failed_chunks
                nonlocal timed_out_chunks
                nonlocal retry_attempts_total
                text = (chunk.content or "").strip()
                if not text:
                    succeeded_chunk_ids.add(chunk.id)
                    return chunk, []

                meta = getattr(chunk, "doc_metadata", None)
                meta_dict = meta if isinstance(meta, dict) else {}
                has_asset = False
                doc_type = str(meta_dict.get("doc_type_kwd") or "").lower()
                if doc_type in {"image", "table"}:
                    has_asset = True
                elif meta_dict.get("image") is not None:
                    has_asset = True
                elif meta_dict.get("img_id") or meta_dict.get("image_id") or meta_dict.get("image_url") or meta_dict.get("image_path"):
                    has_asset = True

                content_len = int(chunk_len_by_id.get(chunk.id, len(text)))
                if min_chars > 0 and content_len < int(min_chars) and not has_asset:
                    skipped_short_chunk_ids.add(chunk.id)
                    succeeded_chunk_ids.add(chunk.id)
                    return chunk, []

                attempt = 0
                last_exc: Exception | None = None
                while True:
                    try:
                        async with sem:
                            llm_called_chunk_ids.add(chunk.id)
                            coro = processor.extract_from_sections(_build_sections(chunk), batch_index=batch_index)
                            if chunk_timeout_sec > 0:
                                data = await asyncio.wait_for(coro, timeout=chunk_timeout_sec)
                            else:
                                data = await coro
                        succeeded_chunk_ids.add(chunk.id)
                        if attempt > 0:
                            retry_chunk_ids.add(chunk.id)
                            retry_attempts_total += int(attempt)
                        return chunk, data if isinstance(data, list) else []
                    except asyncio.TimeoutError as exc:
                        timed_out_chunks += 1
                        timeout_chunk_ids.add(chunk.id)
                        last_exc = exc
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc

                    if attempt >= int(chunk_max_retries):
                        if attempt > 0:
                            retry_chunk_ids.add(chunk.id)
                            retry_attempts_total += int(attempt)
                        failed_chunks += 1
                        failed_chunk_ids.add(chunk.id)
                        logger.warning(
                            "KG extract failed for chunk %s after %s attempts: %s",
                            getattr(chunk, "id", ""),
                            attempt + 1,
                            str(last_exc)[:200] if last_exc else "unknown_error",
                        )
                        return chunk, []

                    attempt += 1
                    if retry_backoff_sec > 0:
                        await asyncio.sleep(float(retry_backoff_sec) * (2 ** (attempt - 1)))

            extracted: List[Tuple[DocumentChunk, List[Dict]]] = []
            group_size = max(1, max_concurrency * 4)
            for offset in range(0, len(chunks_to_process), group_size):
                group = chunks_to_process[offset : offset + group_size]
                results = await asyncio.gather(
                    *[_extract_one(ch, batch_index=offset + i + 1) for i, ch in enumerate(group)],
                )
                extracted.extend(results)

            # Build normalized events first, then embed in batch.
            processed_events: List[Tuple[DocumentChunk, Dict]] = []
            entity_parser = EntityValueParser()
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
                    entities = _canonicalize_entities_for_chunk(
                        entities,
                        chunk_text=(chunk.content or ""),
                        max_entities=max_entities_per_event,
                        parser=entity_parser,
                    )

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
                        for text, vector in zip(batch, vectors, strict=False):
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
                    refs["start_char"] = int(chunk.start_char)
                if getattr(chunk, "end_char", None) is not None:
                    refs["end_char"] = int(chunk.end_char)
                meta = getattr(chunk, "doc_metadata", None)
                meta_dict = meta if isinstance(meta, dict) else {}
                source_val = meta_dict.get("source")
                if isinstance(source_val, str) and source_val.strip():
                    refs["source"] = source_val.strip()
                refs["chunk_key"] = chunk_key_by_id.get(chunk.id) or str(chunk.chunk_index)
                refs["content_hash"] = chunk_hash_by_id.get(chunk.id) or ""
                refs["content_len"] = int(chunk_len_by_id.get(chunk.id, 0) or 0)

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
                kept_on_failure: list[KgSourceEvent] = []
                if replace_existing and failed_chunk_ids:
                    if existing_events_by_chunk:
                        for cid in failed_chunk_ids:
                            kept_on_failure.extend(existing_events_by_chunk.get(cid) or [])
                    else:
                        existing = (
                            session.query(KgSourceEvent)
                            .filter(
                                KgSourceEvent.tenant_id == tenant_id,
                                KgSourceEvent.chunk_id.in_(list(failed_chunk_ids)),
                            )
                            .all()
                        )
                        for ev in existing:
                            if getattr(ev, "chunk_id", None) in failed_chunk_ids:
                                kept_on_failure.append(ev)

                cleanup_chunk_ids = [cid for cid in succeeded_chunk_ids if cid not in skipped_chunk_ids]
                if replace_existing and cleanup_chunk_ids:
                    try:
                        # Keep relation data consistent with events: if we replace extraction for a chunk,
                        # remove any prior relations derived from that chunk before pruning entities.
                        if extract_relations_enabled:
                            RelationRepository(session).delete_relations_for_chunks(
                                cleanup_chunk_ids,
                                tenant_id=tenant_id,
                                commit=False,
                            )
                        Indexer(session).delete_event_indexes_for_chunks(
                            tenant_id=tenant_id,
                            chunk_ids=list(cleanup_chunk_ids),
                            exclude_event_ids=[],
                            prune_orphan_entities=bool(getattr(config, "prune_orphan_entities", False)),
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to cleanup previous KG events for chunks: %s", str(exc)[:200])

                events = list(kept_events) + list(kept_on_failure)
                elapsed = time.perf_counter() - t0
                log_metrics(
                    {
                        "event": "kg.extract",
                        "chunk_count": len(resolved_chunks),
                        "chunk_processed": int(len(chunks_to_process)),
                        "chunk_skipped": int(len(skipped_chunk_ids)),
                        "chunk_skipped_short": int(len(skipped_short_chunk_ids)),
                        "chunk_failed": int(failed_chunks),
                        "chunk_timeout": int(len(timeout_chunk_ids)),
                        "timeout_errors": int(timed_out_chunks),
                        "retry_chunks": int(len(retry_chunk_ids)),
                        "retry_attempts": int(retry_attempts_total),
                        "llm_called_chunks": int(len(llm_called_chunk_ids)),
                        "event_new": 0,
                        "event_kept": int(len(events)),
                        "event_total": int(len(events)),
                        "elapsed_sec": round(float(elapsed), 3),
                    }
                )
                self._writeback_document_metadata(
                    session=session,
                    tenant_id=tenant_id,
                    chunks=resolved_chunks,
                    kept_events=events,
                    skipped_chunk_ids=skipped_chunk_ids,
                    skipped_short_chunk_ids=skipped_short_chunk_ids,
                    failed_chunk_ids=failed_chunk_ids,
                    retry_chunk_ids=retry_chunk_ids,
                )
                return events

            indexer = Indexer(session)
            result = indexer.upsert(
                tenant_id=tenant_id,
                records=events_to_index,
                options=index_options,
            ).event_result

            new_events = result.events if result else []
            cleanup_chunk_ids = [cid for cid in succeeded_chunk_ids if cid not in skipped_chunk_ids]

            # Optional pass: extract entity->entity relations (triples) per processed chunk.
            # This runs after event/entity indexing so we can map candidate entities to persisted KgEntity ids.
            # IMPORTANT: commit relations before deleting old events when pruning is enabled; otherwise,
            # relation-referenced entities could be pruned prematurely.
            if extract_relations_enabled and cleanup_chunk_ids:
                try:
                    # 1) Build candidates per chunk based on extracted entities.
                    candidate_rows_by_chunk: dict[object, list[tuple[str, str, str]]] = {}
                    seen_by_chunk: dict[object, set[tuple[str, str]]] = {}
                    for chunk, ev in processed_events:
                        if chunk.id not in cleanup_chunk_ids:
                            continue
                        entities = ev.get("entities") if isinstance(ev, dict) else None
                        if not isinstance(entities, list) or not entities:
                            continue

                        rows = candidate_rows_by_chunk.setdefault(chunk.id, [])
                        seen = seen_by_chunk.setdefault(chunk.id, set())
                        for ent in entities:
                            if not isinstance(ent, dict):
                                continue
                            name = (ent.get("name") or "").strip()
                            if not name:
                                continue
                            normalized = (ent.get("normalized_name") or name).strip()
                            ent_type = (ent.get("type") or "unknown").strip() or "unknown"
                            key = (ent_type, normalized)
                            if key in seen:
                                continue
                            seen.add(key)
                            rows.append((name, ent_type, normalized))

                    candidates_by_chunk: dict[object, list[CandidateEntity]] = {}
                    for chunk_id in cleanup_chunk_ids:
                        rows = candidate_rows_by_chunk.get(chunk_id) or []
                        candidates_by_chunk[chunk_id] = [
                            CandidateEntity(cid=f"E{i}", name=name, type=ent_type, normalized_name=normalized)
                            for i, (name, ent_type, normalized) in enumerate(rows, 1)
                        ]

                    # 2) Build lookup from (type, normalized_name) to KgEntity.id from the indexing result.
                    entity_id_by_key: dict[tuple[str, str], object] = {}
                    for ent in (list(result.entities) if result else []):
                        norm = str(getattr(ent, "normalized_name", "") or "").strip()
                        etype = str(getattr(ent, "type", "") or "unknown").strip() or "unknown"
                        ent_id = getattr(ent, "id", None)
                        if norm and ent_id is not None:
                            entity_id_by_key[(etype, norm)] = ent_id

                    # 2.5) Heuristic alias pass (high precision): detect explicit alias definitions in the chunk
                    # and ensure both sides exist as entities + create alias_of relations.
                    #
                    # This reduces entity fragmentation across docs, which directly improves KG-assisted recall
                    # and downstream RAG query expansion / chunk injection.
                    alias_enabled = bool(getattr(settings, "KG_RELATION_ALIAS_HEURISTIC_ENABLED", True))
                    alias_max_candidates = max(
                        0,
                        int(getattr(settings, "KG_RELATION_ALIAS_MAX_CANDIDATES_PER_CHUNK", 10) or 10),
                    )
                    alias_conf_raw = getattr(settings, "KG_RELATION_ALIAS_CONFIDENCE", 0.95)
                    try:
                        alias_conf = float(alias_conf_raw) if alias_conf_raw is not None else 0.95
                    except Exception:
                        alias_conf = 0.95
                    alias_conf = max(0.0, min(alias_conf, 1.0))

                    alias_specs_by_chunk: dict[object, list[tuple[str, str, str, str]]] = {}
                    missing_entities: dict[tuple[str, str], str] = {}

                    chunk_by_id = {c.id: c for c in resolved_chunks if getattr(c, "id", None) is not None}
                    alias_parser = EntityValueParser()

                    if alias_enabled and alias_max_candidates > 0:
                        for chunk_id in cleanup_chunk_ids:
                            ch = chunk_by_id.get(chunk_id)
                            if ch is None:
                                continue
                            candidates = candidates_by_chunk.get(chunk_id) or []
                            if not candidates:
                                continue

                            # Match alias candidates to extracted entities in this chunk via normalized_name.
                            cand_by_norm: dict[str, tuple[str, str]] = {}
                            for c in candidates:
                                norm = str(getattr(c, "normalized_name", "") or "").strip() or alias_parser.normalize_name(
                                    str(getattr(c, "name", "") or "")
                                )
                                etype = str(getattr(c, "type", "") or "unknown").strip() or "unknown"
                                name = str(getattr(c, "name", "") or "").strip()
                                if not norm or not name:
                                    continue
                                cand_by_norm.setdefault(norm, (etype, name))

                            alias_candidates = extract_alias_candidates(
                                text=(ch.content or ""),
                                max_candidates=alias_max_candidates,
                            )
                            if not alias_candidates:
                                continue

                            per_chunk_specs: list[tuple[str, str, str, str]] = []
                            for cand in alias_candidates:
                                direction = choose_alias_direction(cand.a, cand.b)
                                if not direction:
                                    continue
                                alias_surface, canonical_surface = direction
                                alias_norm_raw = alias_parser.normalize_name(alias_surface)
                                canonical_norm_raw = alias_parser.normalize_name(canonical_surface)
                                if not alias_norm_raw or not canonical_norm_raw:
                                    continue
                                if alias_norm_raw == canonical_norm_raw:
                                    continue

                                # Anchor canonical_surface to an extracted entity for this chunk (precision guard).
                                # Parentheses/abbr patterns can capture leading context (especially in CJK), so
                                # we also attempt a suffix alignment to the extracted entity surfaces.
                                canonical_norm = canonical_norm_raw
                                canonical_surface_resolved = canonical_surface
                                if canonical_norm not in cand_by_norm:
                                    match = best_suffix_match(canonical_norm, list(cand_by_norm.keys()), min_chars=2)
                                    if match and match in cand_by_norm:
                                        canonical_norm = match
                                        canonical_surface_resolved = cand_by_norm[match][1]

                                if canonical_norm not in cand_by_norm:
                                    # Do not create entities from long, context-y surfaces like "我们使用清华大学".
                                    continue

                                inferred_type: str = cand_by_norm[canonical_norm][0]

                                alias_norm = alias_norm_raw
                                alias_surface_resolved = alias_surface
                                if alias_norm in cand_by_norm:
                                    alias_surface_resolved = cand_by_norm[alias_norm][1]

                                # Ensure both sides exist as entities (best-effort upsert with vectors).
                                if (inferred_type, canonical_norm) not in entity_id_by_key:
                                    missing_entities[(inferred_type, canonical_norm)] = canonical_surface_resolved

                                if (inferred_type, alias_norm) not in entity_id_by_key:
                                    # Only upsert missing aliases if they actually look like abbreviations.
                                    # This keeps the heuristic high-precision and avoids injecting "sentence fragments"
                                    # as entities when regex capture is too broad.
                                    if alias_norm in cand_by_norm or is_abbrev_token(alias_surface_resolved):
                                        missing_entities[(inferred_type, alias_norm)] = alias_surface_resolved
                                    else:
                                        continue

                                per_chunk_specs.append(
                                    (inferred_type, alias_norm, canonical_norm, str(cand.method or ""))
                                )

                            if per_chunk_specs:
                                alias_specs_by_chunk[chunk_id] = per_chunk_specs

                        # Best-effort: upsert any missing alias entities so we can create alias_of relations.
                        if missing_entities:
                            alias_texts = list(missing_entities.values())
                            vectors: list[list[float]] = []
                            try:
                                vectors = await embedder.generate_batch(alias_texts)
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("KG alias embedding failed; proceeding without vectors: %s", str(exc)[:200])
                                vectors = [[] for _ in alias_texts]

                            to_upsert: list[dict] = []
                            for (etype, norm), surface, vec in zip(
                                list(missing_entities.keys()),
                                alias_texts,
                                vectors,
                                strict=False,
                            ):
                                item = {
                                    "name": surface,
                                    "normalized_name": norm,
                                    "type": etype,
                                    "description": None,
                                    "vector": list(vec) if isinstance(vec, list) and vec else None,
                                    "extra_data": {"source": "alias_heuristic"},
                                }
                                to_upsert.append(item)

                            try:
                                upserted = indexer.upsert_entities(
                                    tenant_id=tenant_id,
                                    entities=to_upsert,
                                    options=index_options,
                                    commit=True,
                                )
                                for ent in upserted or []:
                                    norm = str(getattr(ent, "normalized_name", "") or "").strip()
                                    etype = str(getattr(ent, "type", "") or "unknown").strip() or "unknown"
                                    ent_id = getattr(ent, "id", None)
                                    if norm and ent_id is not None:
                                        entity_id_by_key[(etype, norm)] = ent_id
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("KG alias entity upsert failed; continuing: %s", str(exc)[:200])

                    # 3) Run LLM extraction for chunks with at least 2 candidates.
                    allowed_predicates: Sequence[str] = _DEFAULT_RELATION_PREDICATES
                    raw_predicates = str(getattr(settings, "KG_RELATION_ALLOWED_PREDICATES", "") or "").strip()
                    if raw_predicates:
                        parts = [p.strip() for p in re.split(r"[,\n]+", raw_predicates) if str(p).strip()]
                        if parts:
                            allowed_predicates = parts

                    relation_processor = RelationProcessor(
                        llm_client=llm_client,
                        allowed_predicates=allowed_predicates,
                    )
                    max_relations_per_chunk = max(
                        0,
                        int(getattr(settings, "KG_RELATION_MAX_RELATIONS_PER_CHUNK", 20) or 20),
                    )
                    if max_relations_per_chunk <= 0:
                        raise RuntimeError("KG_RELATION_MAX_RELATIONS_PER_CHUNK must be > 0 when relations are enabled")

                    async def _extract_relations_for_chunk(chunk_id: object):
                        ch = chunk_by_id.get(chunk_id)
                        if ch is None:
                            return chunk_id, [], False
                        candidates = candidates_by_chunk.get(chunk_id) or []
                        # Treat <2 candidates as a successful empty extraction (replace mode should delete old relations).
                        if len(candidates) < 2:
                            return chunk_id, [], True
                        try:
                            async with sem:
                                coro = relation_processor.extract_relations(
                                    text=(ch.content or ""),
                                    candidates=candidates,
                                    max_relations=max_relations_per_chunk,
                                )
                                if chunk_timeout_sec > 0:
                                    rels = await asyncio.wait_for(coro, timeout=chunk_timeout_sec)
                                else:
                                    rels = await coro
                            return chunk_id, rels if isinstance(rels, list) else [], True
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "KG relation extract failed for chunk %s: %s",
                                str(getattr(ch, "id", "") or ""),
                                str(exc)[:200],
                            )
                            return chunk_id, [], False

                    rel_results = await asyncio.gather(*[_extract_relations_for_chunk(cid) for cid in cleanup_chunk_ids])

                    succeeded_rel_chunk_ids: list[object] = []
                    rel_rows: list[KgRelation] = []

                    for chunk_id, rels, ok in rel_results:
                        ch = chunk_by_id.get(chunk_id)
                        if ch is None:
                            continue
                        if ok:
                            succeeded_rel_chunk_ids.append(chunk_id)

                        refs: Dict[str, object] = {"chunk_index": ch.chunk_index, "page": ch.page_number}
                        if getattr(ch, "start_char", None) is not None:
                            refs["start_char"] = int(ch.start_char)
                        if getattr(ch, "end_char", None) is not None:
                            refs["end_char"] = int(ch.end_char)
                        meta = getattr(ch, "doc_metadata", None)
                        meta_dict = meta if isinstance(meta, dict) else {}
                        source_val = meta_dict.get("source")
                        if isinstance(source_val, str) and source_val.strip():
                            refs["source"] = source_val.strip()
                        refs["chunk_key"] = chunk_key_by_id.get(ch.id) or str(ch.chunk_index)
                        refs["content_hash"] = chunk_hash_by_id.get(ch.id) or ""
                        refs["content_len"] = int(chunk_len_by_id.get(ch.id, 0) or 0)

                        seen_rel_keys: set[tuple[object, str, object]] = set()
                        # If LLM extraction failed, we do not replace old relations. To keep the alias heuristic
                        # idempotent, skip inserting alias edges that already exist for this chunk.
                        alias_specs = alias_specs_by_chunk.get(chunk_id) or []
                        if (not ok) and alias_specs:
                            try:
                                existing = (
                                    session.query(
                                        KgRelation.subject_entity_id,
                                        KgRelation.predicate,
                                        KgRelation.object_entity_id,
                                    )
                                    .filter(
                                        KgRelation.tenant_id == tenant_id,
                                        KgRelation.chunk_id == ch.id,
                                        KgRelation.predicate.in_(["alias_of", "same_as"]),
                                    )
                                    .all()
                                )
                                for subj_id, pred, obj_id in existing:
                                    if subj_id is None or obj_id is None:
                                        continue
                                    seen_rel_keys.add((subj_id, str(pred or "").strip(), obj_id))
                            except Exception:
                                # Best-effort: if the DB can't answer, proceed without dedupe.
                                pass

                        if ok:
                            cand_map = {c.cid: c for c in (candidates_by_chunk.get(chunk_id) or [])}
                            for rel in rels or []:
                                if not isinstance(rel, dict):
                                    continue
                                subj_cid = str(rel.get("subject_id") or "").strip()
                                obj_cid = str(rel.get("object_id") or "").strip()
                                pred = str(rel.get("predicate") or "").strip() or "unknown"
                                if not subj_cid or not obj_cid:
                                    continue
                                subj_cand = cand_map.get(subj_cid)
                                obj_cand = cand_map.get(obj_cid)
                                if subj_cand is None or obj_cand is None:
                                    continue

                                subj_key = (
                                    str(subj_cand.type or "unknown").strip() or "unknown",
                                    str(subj_cand.normalized_name or "").strip(),
                                )
                                obj_key = (
                                    str(obj_cand.type or "unknown").strip() or "unknown",
                                    str(obj_cand.normalized_name or "").strip(),
                                )
                                subj_ent_id = entity_id_by_key.get(subj_key)
                                obj_ent_id = entity_id_by_key.get(obj_key)
                                if subj_ent_id is None or obj_ent_id is None:
                                    continue

                                rel_key = (subj_ent_id, pred, obj_ent_id)
                                if rel_key in seen_rel_keys:
                                    continue
                                seen_rel_keys.add(rel_key)

                                conf_raw = rel.get("confidence")
                                try:
                                    conf = float(conf_raw) if conf_raw is not None else 0.5
                                except Exception:
                                    conf = 0.5
                                conf = max(0.0, min(1.0, conf))

                                rel_rows.append(
                                    KgRelation(
                                        tenant_id=tenant_id,
                                        document_id=ch.document_id,
                                        chunk_id=ch.id,
                                        event_id=None,
                                        subject_entity_id=subj_ent_id,
                                        predicate=pred,
                                        predicate_raw=(str(rel.get("predicate_raw") or "").strip() or None),
                                        object_entity_id=obj_ent_id,
                                        confidence=conf,
                                        qualifiers=rel.get("qualifiers") if isinstance(rel.get("qualifiers"), dict) else None,
                                        references=refs,
                                        extra_data={
                                            "kg_prompt_template_id": chosen_template_id,
                                            "kg_prompt_template_key": config.prompt_template_key,
                                            "kg_prompt_ab_experiment_key": config.prompt_ab_experiment_key,
                                        },
                                    )
                                )

                        # Insert heuristic alias_of edges (best-effort; may run even if LLM failed).
                        for etype, alias_norm, canonical_norm, method in alias_specs:
                            subj_ent_id = entity_id_by_key.get((etype, alias_norm))
                            obj_ent_id = entity_id_by_key.get((etype, canonical_norm))
                            if subj_ent_id is None or obj_ent_id is None or subj_ent_id == obj_ent_id:
                                continue
                            rel_key = (subj_ent_id, "alias_of", obj_ent_id)
                            if rel_key in seen_rel_keys or (obj_ent_id, "alias_of", subj_ent_id) in seen_rel_keys:
                                continue
                            seen_rel_keys.add(rel_key)

                            rel_rows.append(
                                KgRelation(
                                    tenant_id=tenant_id,
                                    document_id=ch.document_id,
                                    chunk_id=ch.id,
                                    event_id=None,
                                    subject_entity_id=subj_ent_id,
                                    predicate="alias_of",
                                    predicate_raw=None,
                                    object_entity_id=obj_ent_id,
                                    confidence=float(alias_conf),
                                    qualifiers={"method": "heuristic_alias", "pattern": str(method or "")},
                                    references=refs,
                                    extra_data={
                                        "kg_prompt_template_id": chosen_template_id,
                                        "kg_prompt_template_key": config.prompt_template_key,
                                        "kg_prompt_ab_experiment_key": config.prompt_ab_experiment_key,
                                    },
                                )
                            )

                    # 4) Persist: replace relations only for chunks that succeeded relation extraction.
                    if replace_existing and succeeded_rel_chunk_ids:
                        RelationRepository(session).delete_relations_for_chunks(
                            succeeded_rel_chunk_ids,
                            tenant_id=tenant_id,
                            commit=False,
                        )

                    if succeeded_rel_chunk_ids or rel_rows:
                        if rel_rows:
                            session.add_all(rel_rows)
                        session.commit()
                except Exception as exc:  # noqa: BLE001
                    try:
                        session.rollback()
                    except Exception:
                        pass
                    logger.warning("KG relation pass failed; continuing without relations: %s", str(exc)[:200])

            # Optional pass: extract Skill/SOP entities and link them to the new events.
            # This is executed after relations (per "triples first, then skills") and before
            # deleting old events, so pruning doesn't accidentally remove newly created skills.
            if extract_skills_enabled and cleanup_chunk_ids:
                try:
                    max_skills_per_chunk = max(
                        0,
                        int(getattr(settings, "KG_SKILL_MAX_SKILLS_PER_CHUNK", 3) or 3),
                    )
                    if max_skills_per_chunk <= 0:
                        raise RuntimeError("KG_SKILL_MAX_SKILLS_PER_CHUNK must be > 0 when skills are enabled")

                    chunk_by_id = {c.id: c for c in resolved_chunks if getattr(c, "id", None) is not None}
                    events_by_chunk: dict[object, list[object]] = {}
                    for ev in new_events:
                        cid = getattr(ev, "chunk_id", None)
                        if cid is None or cid not in cleanup_chunk_ids:
                            continue
                        events_by_chunk.setdefault(cid, []).append(ev)

                    parser = EntityValueParser()
                    skill_processor = SkillProcessor(llm_client=llm_client)

                    async def _extract_skills_for_chunk(chunk_id: object):
                        ch = chunk_by_id.get(chunk_id)
                        if ch is None:
                            return chunk_id, [], False
                        if chunk_id not in events_by_chunk:
                            # No new events to attach to => skip storing skills for now.
                            return chunk_id, [], False
                        try:
                            async with sem:
                                coro = skill_processor.extract_skills(
                                    text=(ch.content or ""),
                                    max_skills=max_skills_per_chunk,
                                )
                                if chunk_timeout_sec > 0:
                                    skills = await asyncio.wait_for(coro, timeout=chunk_timeout_sec)
                                else:
                                    skills = await coro
                            return chunk_id, skills if isinstance(skills, list) else [], True
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "KG skill extract failed for chunk %s: %s",
                                str(getattr(ch, "id", "") or ""),
                                str(exc)[:200],
                            )
                            return chunk_id, [], False

                    skill_results = await asyncio.gather(*[_extract_skills_for_chunk(cid) for cid in cleanup_chunk_ids])

                    # Flatten + embed skills for vector search (kg_entities milvus).
                    skill_entity_inputs: list[dict] = []
                    skills_by_chunk: dict[object, list[dict]] = {}
                    skill_embed_texts: list[str] = []
                    skill_embed_key_by_input_idx: list[str] = []

                    for chunk_id, skills, ok in skill_results:
                        if not ok:
                            continue
                        if not skills:
                            continue
                        ch = chunk_by_id.get(chunk_id)
                        if ch is None:
                            continue

                        kept: list[dict] = []
                        seen_norm: set[str] = set()
                        for raw in skills:
                            if not isinstance(raw, dict):
                                continue
                            name = str(raw.get("name") or "").strip()
                            if not name:
                                continue
                            norm = parser.normalize_name(name)
                            if not norm or norm in seen_norm:
                                continue
                            seen_norm.add(norm)

                            summary = str(raw.get("summary") or "").strip() or None
                            steps = raw.get("steps") if isinstance(raw.get("steps"), list) else []
                            inputs = raw.get("inputs") if isinstance(raw.get("inputs"), list) else []
                            outputs = raw.get("outputs") if isinstance(raw.get("outputs"), list) else []
                            tools = raw.get("tools") if isinstance(raw.get("tools"), list) else []
                            tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []

                            embed_text = name
                            if summary:
                                embed_text += f"\n{summary}"
                            if steps:
                                embed_text += "\n" + "\n".join([str(s).strip() for s in steps[:6] if str(s).strip()])
                            embed_text = embed_text[:2000]

                            kept.append(
                                {
                                    "name": name,
                                    "normalized_name": norm,
                                    "type": "Skill",
                                    "description": summary,
                                    "vector": None,  # filled after embedding
                                    "extra_data": {
                                        "summary": summary,
                                        "steps": [str(s).strip() for s in steps if str(s).strip()][:50],
                                        "inputs": [str(s).strip() for s in inputs if str(s).strip()][:50],
                                        "outputs": [str(s).strip() for s in outputs if str(s).strip()][:50],
                                        "tools": [str(s).strip() for s in tools if str(s).strip()][:50],
                                        "tags": [str(s).strip() for s in tags if str(s).strip()][:50],
                                        "confidence": raw.get("confidence"),
                                    },
                                    "_embed_text": embed_text,
                                    "_chunk_id": chunk_id,
                                }
                            )
                            if len(kept) >= max_skills_per_chunk:
                                break

                        if kept:
                            skills_by_chunk[chunk_id] = kept
                            for item in kept:
                                text = str(item.get("_embed_text") or "").strip()
                                if text:
                                    skill_embed_texts.append(text)
                                    skill_embed_key_by_input_idx.append(text)

                    # Embed skills (best-effort).
                    skill_vectors_by_text: dict[str, list[float]] = {}
                    if skill_embed_texts:
                        try:
                            vectors = await embedder.generate_batch(skill_embed_texts)
                            for text, vec in zip(skill_embed_texts, vectors, strict=False):
                                if vec:
                                    skill_vectors_by_text[str(text)] = list(vec)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("KG skill embedding failed; proceeding without vectors: %s", str(exc)[:200])
                            skill_vectors_by_text = {}

                    for chunk_skills in skills_by_chunk.values():
                        for item in chunk_skills:
                            etxt = str(item.get("_embed_text") or "").strip()
                            if etxt and etxt in skill_vectors_by_text:
                                item["vector"] = skill_vectors_by_text.get(etxt)
                            # Drop internal keys before persistence.
                            item.pop("_embed_text", None)

                            # Convert confidence to a stable numeric edge weight later.
                            try:
                                item["_confidence"] = float(item.get("extra_data", {}).get("confidence") or 0.6)
                            except Exception:
                                item["_confidence"] = 0.6

                    for _chunk_id, items in skills_by_chunk.items():
                        for item in items:
                            skill_entity_inputs.append(item)

                    if skill_entity_inputs:
                        upserted = indexer.upsert_entities(
                            tenant_id=tenant_id,
                            entities=[
                                {k: v for k, v in item.items() if not str(k).startswith("_")}
                                for item in skill_entity_inputs
                                if isinstance(item, dict)
                            ],
                            options=index_options,
                            commit=True,
                        )
                        skill_id_by_norm: dict[str, object] = {}
                        for ent in upserted or []:
                            if str(getattr(ent, "type", "") or "") != "Skill":
                                continue
                            norm = str(getattr(ent, "normalized_name", "") or "").strip()
                            if norm:
                                skill_id_by_norm[norm] = getattr(ent, "id", None)

                        # Link: event -> skill (role="skill") with provenance.
                        links: list[KgEventEntity] = []
                        for chunk_id, items in skills_by_chunk.items():
                            ch = chunk_by_id.get(chunk_id)
                            if ch is None:
                                continue

                            refs: Dict[str, object] = {"chunk_index": ch.chunk_index, "page": ch.page_number}
                            if getattr(ch, "start_char", None) is not None:
                                refs["start_char"] = int(ch.start_char)
                            if getattr(ch, "end_char", None) is not None:
                                refs["end_char"] = int(ch.end_char)
                            meta = getattr(ch, "doc_metadata", None)
                            meta_dict = meta if isinstance(meta, dict) else {}
                            source_val = meta_dict.get("source")
                            if isinstance(source_val, str) and source_val.strip():
                                refs["source"] = source_val.strip()
                            refs["chunk_key"] = chunk_key_by_id.get(ch.id) or str(ch.chunk_index)
                            refs["content_hash"] = chunk_hash_by_id.get(ch.id) or ""
                            refs["content_len"] = int(chunk_len_by_id.get(ch.id, 0) or 0)

                            link_extra = build_event_entity_provenance(
                                document_id=ch.document_id,
                                chunk_id=ch.id,
                                references=refs,
                            )

                            for ev in events_by_chunk.get(chunk_id, []) or []:
                                ev_id = getattr(ev, "id", None)
                                if ev_id is None:
                                    continue
                                for item in items:
                                    norm = str(item.get("normalized_name") or "").strip()
                                    skill_id = skill_id_by_norm.get(norm)
                                    if not skill_id:
                                        continue
                                    conf = float(item.get("_confidence") or 0.6)
                                    conf = max(0.0, min(1.0, conf))
                                    links.append(
                                        KgEventEntity(
                                            event_id=ev_id,
                                            entity_id=skill_id,
                                            weight=conf,
                                            role="skill",
                                            extra_data=(link_extra or None),
                                        )
                                    )

                        if links:
                            session.add_all(links)
                            session.commit()
                except Exception as exc:  # noqa: BLE001
                    try:
                        session.rollback()
                    except Exception:
                        pass
                    logger.warning("KG skill pass failed; continuing without skills: %s", str(exc)[:200])

            if replace_existing and cleanup_chunk_ids:
                try:
                    indexer.delete_event_indexes_for_chunks(
                        tenant_id=tenant_id,
                        chunk_ids=list(cleanup_chunk_ids),
                        exclude_event_ids=[ev.id for ev in new_events],
                        prune_orphan_entities=bool(getattr(config, "prune_orphan_entities", False)),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to cleanup previous KG events for chunks: %s", str(exc)[:200])

            kept_on_failure: list[KgSourceEvent] = []
            if replace_existing and failed_chunk_ids:
                if not existing_events_by_chunk:
                    existing = (
                        session.query(KgSourceEvent)
                        .filter(
                            KgSourceEvent.tenant_id == tenant_id,
                            KgSourceEvent.chunk_id.in_(list(failed_chunk_ids)),
                        )
                        .all()
                    )
                    for ev in existing:
                        if getattr(ev, "chunk_id", None) in failed_chunk_ids:
                            kept_on_failure.append(ev)
                else:
                    for cid in failed_chunk_ids:
                        kept_on_failure.extend(existing_events_by_chunk.get(cid) or [])

            events = list(kept_events) + list(kept_on_failure) + list(new_events)

            elapsed = time.perf_counter() - t0
            log_metrics(
                {
                    "event": "kg.extract",
                    "chunk_count": len(resolved_chunks),
                    "chunk_processed": int(len(chunks_to_process)),
                    "chunk_skipped": int(len(skipped_chunk_ids)),
                    "chunk_skipped_short": int(len(skipped_short_chunk_ids)),
                    "chunk_failed": int(failed_chunks),
                    "chunk_timeout": int(len(timeout_chunk_ids)),
                    "timeout_errors": int(timed_out_chunks),
                    "retry_chunks": int(len(retry_chunk_ids)),
                    "retry_attempts": int(retry_attempts_total),
                    "llm_called_chunks": int(len(llm_called_chunk_ids)),
                    "event_new": int(len(new_events)),
                    "event_kept": int(len(kept_events) + len(kept_on_failure)),
                    "event_total": int(len(events)),
                    "entity_count_new": int(entity_total),
                    "max_concurrency": int(max_concurrency),
                    "elapsed_sec": round(float(elapsed), 3),
                }
            )
            self._writeback_document_metadata(
                session=session,
                tenant_id=tenant_id,
                chunks=resolved_chunks,
                kept_events=events,
                skipped_chunk_ids=skipped_chunk_ids,
                skipped_short_chunk_ids=skipped_short_chunk_ids,
                failed_chunk_ids=failed_chunk_ids,
                retry_chunk_ids=retry_chunk_ids,
            )
            return events
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _writeback_document_metadata(
        self,
        *,
        session,
        tenant_id,
        chunks: Sequence[DocumentChunk],
        kept_events: Sequence[KgSourceEvent],
        skipped_chunk_ids: set[object],
        skipped_short_chunk_ids: set[object],
        failed_chunk_ids: set[object],
        retry_chunk_ids: set[object],
    ) -> None:
        try:
            from app.models.document import Document as DBDocument

            if not chunks:
                return

            chunk_id_to_doc_id: dict[object, object] = {}
            for ch in chunks:
                if getattr(ch, "id", None) and getattr(ch, "document_id", None):
                    chunk_id_to_doc_id[ch.id] = ch.document_id

            doc_ids = {doc_id for doc_id in chunk_id_to_doc_id.values() if doc_id}
            if not doc_ids:
                return

            extracted_at = datetime.now(timezone.utc).isoformat()
            # Count events by document using chunk->doc mapping for robustness.
            event_count_by_doc: dict[object, int] = {doc_id: 0 for doc_id in doc_ids}
            for ev in kept_events:
                cid = getattr(ev, "chunk_id", None)
                doc_id = chunk_id_to_doc_id.get(cid) if cid is not None else getattr(ev, "document_id", None)
                if doc_id in event_count_by_doc:
                    event_count_by_doc[doc_id] += 1

            skipped_count_by_doc: dict[object, int] = {doc_id: 0 for doc_id in doc_ids}
            failed_count_by_doc: dict[object, int] = {doc_id: 0 for doc_id in doc_ids}
            short_skipped_count_by_doc: dict[object, int] = {doc_id: 0 for doc_id in doc_ids}
            retry_count_by_doc: dict[object, int] = {doc_id: 0 for doc_id in doc_ids}
            for cid in skipped_chunk_ids:
                doc_id = chunk_id_to_doc_id.get(cid)
                if doc_id in skipped_count_by_doc:
                    skipped_count_by_doc[doc_id] += 1
            for cid in skipped_short_chunk_ids:
                doc_id = chunk_id_to_doc_id.get(cid)
                if doc_id in short_skipped_count_by_doc:
                    short_skipped_count_by_doc[doc_id] += 1
            for cid in failed_chunk_ids:
                doc_id = chunk_id_to_doc_id.get(cid)
                if doc_id in failed_count_by_doc:
                    failed_count_by_doc[doc_id] += 1
            for cid in retry_chunk_ids:
                doc_id = chunk_id_to_doc_id.get(cid)
                if doc_id in retry_count_by_doc:
                    retry_count_by_doc[doc_id] += 1

            docs = (
                session.query(DBDocument)
                .filter(
                    DBDocument.id.in_(list(doc_ids)),
                    DBDocument.tenant_id == tenant_id,
                )
                .all()
            )
            for doc in docs:
                meta = dict(getattr(doc, "doc_metadata", None) or {})
                meta["kg_event_count"] = int(event_count_by_doc.get(doc.id, 0))
                meta["kg_skipped_chunks"] = int(skipped_count_by_doc.get(doc.id, 0))
                meta["kg_skipped_short_chunks"] = int(short_skipped_count_by_doc.get(doc.id, 0))
                meta["kg_failed_chunks"] = int(failed_count_by_doc.get(doc.id, 0))
                meta["kg_retry_chunks"] = int(retry_count_by_doc.get(doc.id, 0))
                meta["kg_extracted_at"] = extracted_at
                doc.doc_metadata = meta
            session.commit()
        except Exception as exc:  # noqa: BLE001
            try:
                session.rollback()
            except Exception:
                pass
            logger.warning("Failed to write back kg metrics to document metadata: %s", str(exc)[:200])
