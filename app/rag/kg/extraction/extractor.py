"""
Event extractor coordinating LLM + embeddings + persistence.
"""

import asyncio
import hashlib
import time
from collections.abc import Sequence
from datetime import UTC, datetime

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
from app.rag.kg.extraction.backend_router import resolve_extraction_backend
from app.rag.kg.extraction.config import ExtractConfig
from app.rag.kg.extraction.entity_verifier import EntityCandidate, EntityVerifier
from app.rag.kg.extraction.evidence import coerce_evidence, surface_mentioned
from app.rag.kg.extraction.parser import EntityValueParser
from app.rag.kg.extraction.processor import EventProcessor
from app.rag.kg.extraction.relation_processor import CandidateEntity, RelationProcessor
from app.rag.kg.extraction.relation_verifier import RelationCandidate, RelationVerifier
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
        evidence_quote = str(ent.get("evidence_quote") or "").strip() or None

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
                            "evidence_quote": evidence_quote,
                        }
                    )
                    expanded.append(
                        {
                            "name": alias_surface,
                            "normalized_name": parser.normalize_name(alias_surface),
                            "type": ent_type,
                            "description": "",
                            "role": role,
                            "evidence_quote": evidence_quote,
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
                "evidence_quote": evidence_quote,
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
        if not str(existing.get("evidence_quote") or "").strip():
            eq = str(ent.get("evidence_quote") or "").strip()
            if eq:
                existing["evidence_quote"] = eq

    return deduped[:lim]


class EventExtractor:
    """Orchestrates event extraction for a batch of chunks."""

    def __init__(self, model_config: dict | None = None):
        self.model_config = model_config

    async def extract(
        self,
        config: ExtractConfig,
        *,
        chunks: Sequence[DocumentChunk] | None = None,
        index_options: IndexingOptions | None = None,
    ) -> list[KgSourceEvent]:
        t0 = time.perf_counter()
        session = SessionLocal()
        try:
            alias_diag: dict[str, object] = {
                "enabled": False,
                "chunks_considered": 0,
                "candidates_total": 0,
                "candidates_by_method": {},
                "direction_ok": 0,
                "direction_skipped": 0,
                "canonical_anchor_exact": 0,
                "canonical_anchor_suffix": 0,
                "canonical_anchor_failed": 0,
                "alias_skipped_non_abbrev": 0,
                "entities_upsert_attempted": 0,
                "entities_upserted": 0,
                "edges_planned": 0,
                "edges_appended": 0,
                "edges_skipped_missing_entities": 0,
                "edges_skipped_duplicate": 0,
            }
            alias_stats_by_doc: dict[object, dict[str, int]] = {}

            def _alias_bump(doc_id: object | None, key: str, n: int = 1) -> None:
                if not doc_id or not key:
                    return
                cur = alias_stats_by_doc.setdefault(doc_id, {})
                cur[key] = int(cur.get(key, 0) or 0) + int(n)

            # Load chunks (or reuse provided ones to avoid duplicate DB reads)
            resolved_chunks: list[DocumentChunk]
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
            llm_processor = EventProcessor(llm_client=llm_client, prompt_template=prompt_template_content)
            backend_selection = resolve_extraction_backend(
                llm_processor=llm_processor,
                requested_backend=getattr(config, "extraction_backend", None),
            )
            processor = backend_selection.processor
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
            failure_messages: list[str] = []

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

            async def _extract_one(chunk: DocumentChunk, *, batch_index: int) -> tuple[DocumentChunk, list[dict]]:
                nonlocal failed_chunks
                nonlocal timed_out_chunks
                nonlocal retry_attempts_total
                text = (chunk.content or "").strip()
                if not text:
                    succeeded_chunk_ids.add(chunk.id)
                    return chunk, []

                meta = getattr(chunk, "doc_metadata", None)
                meta_dict = meta if isinstance(meta, dict) else {}
                doc_type = str(meta_dict.get("doc_type_kwd") or "").lower()
                has_asset = (
                    doc_type in {"image", "table"}
                    or meta_dict.get("image") is not None
                    or bool(
                        meta_dict.get("img_id")
                        or meta_dict.get("image_id")
                        or meta_dict.get("image_url")
                        or meta_dict.get("image_path")
                    )
                )

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
                            coro = processor.extract_from_sections(
                                _build_sections(chunk),
                                batch_index=batch_index,
                                max_events=max_events_per_chunk,
                                max_entities_per_event=max_entities_per_event,
                            )
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
                        failure_messages.append(str(last_exc)[:300] if last_exc else "unknown_error")
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

            extracted: list[tuple[DocumentChunk, list[dict]]] = []
            group_size = max(1, max_concurrency * 4)
            for offset in range(0, len(chunks_to_process), group_size):
                group = chunks_to_process[offset : offset + group_size]
                results = await asyncio.gather(
                    *[_extract_one(ch, batch_index=offset + i + 1) for i, ch in enumerate(group)],
                )
                extracted.extend(results)

            # Build normalized events first, then embed in batch.
            processed_events: list[tuple[DocumentChunk, dict]] = []
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

            # Optional: entity verification + evidence grounding (higher quality, higher cost).
            entity_verify_enabled = bool(getattr(settings, "KG_EXTRACT_ENTITY_VERIFY_ENABLED", False))
            relation_verify_enabled = bool(getattr(settings, "KG_EXTRACT_RELATION_VERIFY_ENABLED", False))
            evidence_required = bool(getattr(settings, "KG_EXTRACT_EVIDENCE_REQUIRED", False)) or bool(
                entity_verify_enabled or relation_verify_enabled
            )

            # Assign stable candidate ids per chunk so we can:
            # - verify/filter entities (LLM pass)
            # - later reuse the same ids for relation extraction and alias edges
            entity_candidates_by_chunk: dict[object, list[EntityCandidate]] = {}
            entity_key_to_cid_by_chunk: dict[object, dict[tuple[str, str], str]] = {}

            for chunk, ev in processed_events:
                ent_list = ev.get("entities") if isinstance(ev, dict) else None
                if not isinstance(ent_list, list) or not ent_list:
                    continue
                cid_by_key = entity_key_to_cid_by_chunk.setdefault(chunk.id, {})
                cand_list = entity_candidates_by_chunk.setdefault(chunk.id, [])

                for ent in ent_list:
                    if not isinstance(ent, dict):
                        continue
                    name = str(ent.get("name") or "").strip()
                    if not name:
                        continue
                    norm = str(ent.get("normalized_name") or "").strip()
                    if not norm:
                        norm = entity_parser.normalize_name(name)
                        ent["normalized_name"] = norm
                    etype = str(ent.get("type") or "unknown").strip() or "unknown"
                    key = (etype, norm)
                    cid = cid_by_key.get(key)
                    if not cid:
                        cid = f"E{len(cid_by_key) + 1}"
                        cid_by_key[key] = cid
                        cand_list.append(
                            EntityCandidate(
                                cid=cid,
                                name=name,
                                type=etype,
                                description=str(ent.get("description") or "").strip(),
                                evidence_quote=str(ent.get("evidence_quote") or "").strip() or None,
                            )
                        )
                    ent["_cid"] = cid

            llm_aliases_by_chunk: dict[object, list[dict[str, object]]] = {}
            if entity_verify_enabled and entity_candidates_by_chunk:
                try:
                    verifier = EntityVerifier(llm_client=llm_client)
                    chunk_by_id_for_verify = {c.id: c for c in resolved_chunks if getattr(c, "id", None) is not None}

                    async def _verify_entities_for_chunk(chunk_id: object):
                        ch = chunk_by_id_for_verify.get(chunk_id)
                        if ch is None:
                            return chunk_id, {"kept": [], "aliases": []}, False
                        candidates = entity_candidates_by_chunk.get(chunk_id) or []
                        if not candidates:
                            return chunk_id, {"kept": [], "aliases": []}, True
                        try:
                            async with sem:
                                coro = verifier.verify(
                                    text=(ch.content or ""),
                                    candidates=candidates,
                                    max_keep=max(5, int(max_entities_per_event or 0)),
                                    max_alias_edges=10,
                                )
                                if chunk_timeout_sec > 0:
                                    out = await asyncio.wait_for(coro, timeout=chunk_timeout_sec)
                                else:
                                    out = await coro
                            return chunk_id, out if isinstance(out, dict) else {"kept": [], "aliases": []}, True
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "KG entity verify failed for chunk %s: %s",
                                str(getattr(ch, "id", "") or ""),
                                str(exc)[:200],
                            )
                            return chunk_id, {"kept": [], "aliases": []}, False

                    verify_results = await asyncio.gather(
                        *[_verify_entities_for_chunk(cid) for cid in entity_candidates_by_chunk.keys()],
                    )

                    keep_map_by_chunk: dict[object, dict[str, dict[str, object]]] = {}
                    for chunk_id, out, ok in verify_results:
                        if not ok:
                            continue
                        kept = out.get("kept") if isinstance(out, dict) else None
                        if isinstance(kept, list) and kept:
                            keep_map: dict[str, dict[str, object]] = {}
                            for item in kept:
                                if not isinstance(item, dict):
                                    continue
                                cid = str(item.get("id") or "").strip()
                                if not cid:
                                    continue
                                keep_map[cid] = dict(item)
                            if keep_map:
                                keep_map_by_chunk[chunk_id] = keep_map

                        aliases = out.get("aliases") if isinstance(out, dict) else None
                        if isinstance(aliases, list) and aliases:
                            cleaned: list[dict[str, object]] = []
                            for item in aliases:
                                if not isinstance(item, dict):
                                    continue
                                a = str(item.get("alias_id") or "").strip()
                                c = str(item.get("canonical_id") or "").strip()
                                if not a or not c or a == c:
                                    continue
                                cleaned.append(dict(item))
                            if cleaned:
                                llm_aliases_by_chunk[chunk_id] = cleaned

                    if keep_map_by_chunk:
                        for chunk, ev in processed_events:
                            keep_map = keep_map_by_chunk.get(chunk.id)
                            if not keep_map:
                                continue
                            ent_list = ev.get("entities") if isinstance(ev, dict) else None
                            if not isinstance(ent_list, list) or not ent_list:
                                continue
                            kept_entities: list[dict] = []
                            for ent in ent_list:
                                if not isinstance(ent, dict):
                                    continue
                                cid = str(ent.get("_cid") or "").strip()
                                if not cid or cid not in keep_map:
                                    continue
                                info = keep_map.get(cid) or {}
                                # Apply verifier corrections (best-effort).
                                if info.get("type"):
                                    ent["type"] = info.get("type")
                                if info.get("description"):
                                    ent["description"] = info.get("description")
                                if info.get("evidence_quote"):
                                    ent["evidence_quote"] = info.get("evidence_quote")
                                if info.get("confidence") is not None:
                                    ent["_confidence"] = info.get("confidence")
                                kept_entities.append(ent)
                            ev["entities"] = kept_entities
                except Exception as exc:  # noqa: BLE001
                    logger.warning("KG entity verify pass failed; continuing without verification: %s", str(exc)[:200])

            # Deterministic evidence gating for entities (quote + span).
            # We store evidence fields in the entity dict so they can be persisted on KgEventEntity.extra_data.
            _stop_norm = {
                "i",
                "me",
                "my",
                "we",
                "our",
                "you",
                "your",
                "he",
                "she",
                "they",
                "it",
                "this",
                "that",
                "these",
                "those",
                "the",
                "a",
                "an",
                "and",
                "or",
                "but",
                "so",
                "because",
                "there",
                "here",
                "what",
                "which",
                "who",
                "whom",
                "whose",
                "where",
                "when",
                "why",
                "how",
                "我们",
                "你",
                "你们",
                "他们",
                "她们",
                "它们",
                "这",
                "那",
                "该",
                "本",
                "此",
            }
            entity_evidence_stats: dict[str, int] = {
                "total_raw": 0,
                "kept": 0,
                "dropped_stopword": 0,
                "dropped_noise_short": 0,
                "dropped_noise_digits": 0,
                "dropped_noise_punct": 0,
                "dropped_no_evidence": 0,
            }
            for chunk, ev in processed_events:
                ent_list = ev.get("entities") if isinstance(ev, dict) else None
                if not isinstance(ent_list, list) or not ent_list:
                    continue
                cleaned: list[dict] = []
                for ent in ent_list:
                    if not isinstance(ent, dict):
                        continue
                    name = str(ent.get("name") or "").strip()
                    if not name:
                        continue
                    norm = str(ent.get("normalized_name") or "").strip()
                    if not norm:
                        norm = entity_parser.normalize_name(name)
                        ent["normalized_name"] = norm

                    entity_evidence_stats["total_raw"] += 1
                    if norm in _stop_norm:
                        entity_evidence_stats["dropped_stopword"] += 1
                        continue
                    # Deterministic noise guards: these reduce graph pollution without extra model calls.
                    #
                    # - Drop single-character ASCII tokens (common variable/bullet noise).
                    # - Drop pure digit tokens.
                    # - Drop punctuation-only tokens.
                    if norm.isascii() and len(norm) < 2:
                        entity_evidence_stats["dropped_noise_short"] += 1
                        continue
                    if norm.isdigit():
                        entity_evidence_stats["dropped_noise_digits"] += 1
                        continue
                    if not any(ch.isalnum() for ch in name):
                        entity_evidence_stats["dropped_noise_punct"] += 1
                        continue

                    evq = ent.get("evidence_quote")
                    evidence = coerce_evidence(
                        text=(chunk.content or ""),
                        evidence_quote=(str(evq).strip() if isinstance(evq, str) else None),
                        fallback_mention=name,
                        max_quote_chars=240,
                    )
                    if evidence is None and evidence_required:
                        entity_evidence_stats["dropped_no_evidence"] += 1
                        continue
                    if evidence is not None:
                        ent["evidence_quote"] = evidence.quote
                        ent["evidence_start_char"] = int(evidence.start_char)
                        ent["evidence_end_char"] = int(evidence.end_char)
                        ent["evidence_source"] = str(getattr(evidence, "source", "") or "").strip() or "quote"
                    cleaned.append(ent)
                    entity_evidence_stats["kept"] += 1
                ev["entities"] = cleaned

            embed_cache: dict[str, list[float]] = {}

            def _iter_batches(items: list[str], size: int):
                for i in range(0, len(items), size):
                    yield items[i : i + size]

            to_embed: list[str] = []
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

            events_to_index: list[IndexRecord] = []
            entity_total = 0
            for chunk, ev in processed_events:
                vector = embed_cache.get(str(ev.get("_embed_text") or ""))

                entity_inputs: list[EventEntityInput] = []
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
                            evidence_quote=(str(ent.get("evidence_quote") or "").strip() or None),
                            evidence_source=(str(ent.get("evidence_source") or "").strip() or None),
                            evidence_start_char=(
                                int(ent.get("evidence_start_char"))
                                if ent.get("evidence_start_char") is not None
                                else None
                            ),
                            evidence_end_char=(
                                int(ent.get("evidence_end_char")) if ent.get("evidence_end_char") is not None else None
                            ),
                        )
                    )
                entity_total += len(entity_inputs)

                refs: dict[str, object] = {"chunk_index": chunk.chunk_index, "page": chunk.page_number}
                if getattr(chunk, "start_char", None) is not None:
                    refs["start_char"] = int(chunk.start_char)
                if getattr(chunk, "end_char", None) is not None:
                    refs["end_char"] = int(chunk.end_char)
                meta = getattr(chunk, "doc_metadata", None)
                meta_dict = meta if isinstance(meta, dict) else {}
                source_val = meta_dict.get("source")
                if isinstance(source_val, str) and source_val.strip():
                    refs["source"] = source_val.strip()
                pipeline_hash_val = meta_dict.get("pipeline_hash") or meta_dict.get("active_pipeline_hash")
                if isinstance(pipeline_hash_val, str) and pipeline_hash_val.strip():
                    refs["pipeline_hash"] = pipeline_hash_val.strip()[:200]
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
                if (
                    failed_chunks > 0
                    and not processed_events
                    and llm_called_chunk_ids
                    and len(failed_chunk_ids) >= len(llm_called_chunk_ids)
                    and not timeout_chunk_ids
                ):
                    unique_errors = list(dict.fromkeys(msg for msg in failure_messages if msg))
                    detail = "; ".join(unique_errors)[:500] if unique_errors else "unknown_error"
                    raise RuntimeError(
                        f"KG extraction failed for all attempted chunks ({failed_chunks}); {detail}"
                    )
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
                        "alias_heuristics": dict(alias_diag),
                        "evidence_required": bool(evidence_required),
                        "entity_evidence": dict(entity_evidence_stats),
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
                    alias_stats_by_doc=alias_stats_by_doc,
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
            relation_evidence_stats: dict[str, int] = {
                "total_raw": 0,
                "kept": 0,
                "dropped_no_evidence": 0,
                "dropped_missing_endpoints": 0,
            }
            skill_evidence_stats: dict[str, int] = {
                "total_raw": 0,
                "kept": 0,
                "dropped_no_evidence": 0,
                "taxonomy_edges_kept": 0,
                "taxonomy_edges_dropped_no_evidence": 0,
            }
            if extract_relations_enabled and cleanup_chunk_ids:
                try:
                    # 1) Build candidates per chunk based on extracted entities.
                    candidate_rows_by_chunk: dict[object, list[tuple[str, str, str, str]]] = {}
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
                            cid = str(ent.get("_cid") or "").strip()
                            if not cid:
                                cid = f"E{len(seen)}"
                            rows.append((cid, name, ent_type, normalized))

                    candidates_by_chunk: dict[object, list[CandidateEntity]] = {}
                    for chunk_id in cleanup_chunk_ids:
                        rows = candidate_rows_by_chunk.get(chunk_id) or []
                        candidates_by_chunk[chunk_id] = [
                            CandidateEntity(cid=cid, name=name, type=ent_type, normalized_name=normalized)
                            for (cid, name, ent_type, normalized) in rows
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

                    alias_specs_by_chunk: dict[object, list[tuple[str, str, str, str, str]]] = {}
                    missing_entities: dict[tuple[str, str], str] = {}

                    chunk_by_id = {c.id: c for c in resolved_chunks if getattr(c, "id", None) is not None}
                    alias_parser = EntityValueParser()

                    if alias_enabled and alias_max_candidates > 0:
                        alias_diag["enabled"] = True
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

                            alias_diag["chunks_considered"] = int(alias_diag.get("chunks_considered", 0) or 0) + 1
                            alias_diag["candidates_total"] = int(alias_diag.get("candidates_total", 0) or 0) + int(
                                len(alias_candidates)
                            )
                            for cand in alias_candidates:
                                method = str(getattr(cand, "method", "") or "").strip() or "unknown"
                                by_method = alias_diag.get("candidates_by_method")
                                if isinstance(by_method, dict):
                                    by_method[method] = int(by_method.get(method, 0) or 0) + 1
                                _alias_bump(ch.document_id, f"kg_alias_candidates_{method}", 1)
                            _alias_bump(ch.document_id, "kg_alias_candidates_total", len(alias_candidates))

                            per_chunk_specs: list[tuple[str, str, str, str, str]] = []
                            for cand in alias_candidates:
                                direction = choose_alias_direction(cand.a, cand.b)
                                if not direction:
                                    alias_diag["direction_skipped"] = int(alias_diag.get("direction_skipped", 0) or 0) + 1
                                    _alias_bump(ch.document_id, "kg_alias_direction_skipped", 1)
                                    continue
                                alias_diag["direction_ok"] = int(alias_diag.get("direction_ok", 0) or 0) + 1
                                _alias_bump(ch.document_id, "kg_alias_direction_ok", 1)
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
                                anchored = "exact" if canonical_norm in cand_by_norm else ""
                                if canonical_norm not in cand_by_norm:
                                    match = best_suffix_match(canonical_norm, list(cand_by_norm.keys()), min_chars=2)
                                    if match and match in cand_by_norm:
                                        canonical_norm = match
                                        canonical_surface_resolved = cand_by_norm[match][1]
                                        anchored = "suffix"

                                if canonical_norm not in cand_by_norm:
                                    alias_diag["canonical_anchor_failed"] = (
                                        int(alias_diag.get("canonical_anchor_failed", 0) or 0) + 1
                                    )
                                    _alias_bump(ch.document_id, "kg_alias_anchor_failed", 1)
                                    # Do not create entities from long, context-y surfaces like "我们使用清华大学".
                                    continue
                                if anchored == "exact":
                                    alias_diag["canonical_anchor_exact"] = (
                                        int(alias_diag.get("canonical_anchor_exact", 0) or 0) + 1
                                    )
                                    _alias_bump(ch.document_id, "kg_alias_anchor_exact", 1)
                                elif anchored == "suffix":
                                    alias_diag["canonical_anchor_suffix"] = (
                                        int(alias_diag.get("canonical_anchor_suffix", 0) or 0) + 1
                                    )
                                    _alias_bump(ch.document_id, "kg_alias_anchor_suffix", 1)

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
                                        alias_diag["alias_skipped_non_abbrev"] = (
                                            int(alias_diag.get("alias_skipped_non_abbrev", 0) or 0) + 1
                                        )
                                        _alias_bump(ch.document_id, "kg_alias_skipped_non_abbrev", 1)
                                        continue

                                per_chunk_specs.append(
                                    (
                                        inferred_type,
                                        alias_norm,
                                        canonical_norm,
                                        str(cand.method or ""),
                                        str(getattr(cand, "quote", "") or "").strip(),
                                    )
                                )

                            if per_chunk_specs:
                                alias_specs_by_chunk[chunk_id] = per_chunk_specs
                                alias_diag["edges_planned"] = int(alias_diag.get("edges_planned", 0) or 0) + int(
                                    len(per_chunk_specs)
                                )
                                _alias_bump(ch.document_id, "kg_alias_edges_planned", len(per_chunk_specs))

                        # Best-effort: upsert any missing alias entities so we can create alias_of relations.
                        if missing_entities:
                            alias_diag["entities_upsert_attempted"] = int(len(missing_entities))
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
                                alias_diag["entities_upserted"] = int(len(upserted or []))
                                for ent in upserted or []:
                                    norm = str(getattr(ent, "normalized_name", "") or "").strip()
                                    etype = str(getattr(ent, "type", "") or "unknown").strip() or "unknown"
                                    ent_id = getattr(ent, "id", None)
                                    if norm and ent_id is not None:
                                        entity_id_by_key[(etype, norm)] = ent_id
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("KG alias entity upsert failed; continuing: %s", str(exc)[:200])

                    # 3) Run LLM extraction for chunks with at least 2 candidates.
                    from app.rag.kg.ontology import resolve_allowed_predicates  # noqa: WPS433

                    allowed_predicates: Sequence[str] = resolve_allowed_predicates(
                        db=session,
                        tenant_id=tenant_id,
                        fallback_default=_DEFAULT_RELATION_PREDICATES,
                        raw_override=str(getattr(settings, "KG_RELATION_ALLOWED_PREDICATES", "") or "").strip(),
                    )

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

                    # Optional verification pass: re-check extracted relations against the text and predicate allowlist.
                    rels_by_chunk: dict[object, list[dict[str, object]]] = {}
                    for chunk_id, rels, ok in rel_results:
                        if not ok:
                            continue
                        if isinstance(rels, list) and rels:
                            rels_by_chunk[chunk_id] = [r for r in rels if isinstance(r, dict)]

                    if relation_verify_enabled and rels_by_chunk:
                        try:
                            verifier = RelationVerifier(llm_client=llm_client, allowed_predicates=allowed_predicates)

                            async def _verify_relations_for_chunk(chunk_id: object):
                                ch = chunk_by_id.get(chunk_id)
                                if ch is None:
                                    return chunk_id, None, False
                                rels0 = rels_by_chunk.get(chunk_id) or []
                                if not rels0:
                                    return chunk_id, [], True

                                rel_cands: list[RelationCandidate] = []
                                by_rid: dict[str, dict[str, object]] = {}
                                for i, rel in enumerate(rels0, 1):
                                    if not isinstance(rel, dict):
                                        continue
                                    rid = f"R{i}"
                                    by_rid[rid] = rel
                                    rel_cands.append(
                                        RelationCandidate(
                                            rid=rid,
                                            subject_id=str(rel.get("subject_id") or "").strip(),
                                            predicate=str(rel.get("predicate") or "").strip() or "unknown",
                                            object_id=str(rel.get("object_id") or "").strip(),
                                            confidence=float(rel.get("confidence") or 0.5),
                                            evidence_quote=str(rel.get("evidence_quote") or "").strip() or None,
                                        )
                                    )

                                if not rel_cands:
                                    return chunk_id, [], True

                                try:
                                    async with sem:
                                        coro = verifier.verify(
                                            text=(ch.content or ""),
                                            candidates=rel_cands,
                                            max_keep=max_relations_per_chunk,
                                        )
                                        if chunk_timeout_sec > 0:
                                            out = await asyncio.wait_for(coro, timeout=chunk_timeout_sec)
                                        else:
                                            out = await coro
                                    kept = out.get("kept") if isinstance(out, dict) else None
                                    if not isinstance(kept, list) or not kept:
                                        # Fail-open: keep original extraction if verifier returns nothing.
                                        return chunk_id, None, True

                                    verified: list[dict[str, object]] = []
                                    for item in kept:
                                        if not isinstance(item, dict):
                                            continue
                                        rid = str(item.get("rid") or "").strip()
                                        src = by_rid.get(rid)
                                        if not rid or src is None:
                                            continue
                                        dst = dict(src)
                                        if item.get("predicate"):
                                            dst["predicate"] = item.get("predicate")
                                        if item.get("confidence") is not None:
                                            dst["confidence"] = item.get("confidence")
                                        if item.get("evidence_quote"):
                                            dst["evidence_quote"] = item.get("evidence_quote")
                                        verified.append(dst)
                                        if len(verified) >= max_relations_per_chunk:
                                            break
                                    return chunk_id, verified, True
                                except Exception as exc:  # noqa: BLE001
                                    logger.warning(
                                        "KG relation verify failed for chunk %s: %s",
                                        str(getattr(ch, "id", "") or ""),
                                        str(exc)[:200],
                                    )
                                    return chunk_id, None, False

                            verify_results = await asyncio.gather(
                                *[_verify_relations_for_chunk(cid) for cid in rels_by_chunk.keys()]
                            )
                            for chunk_id, verified, ok in verify_results:
                                if not ok:
                                    continue
                                if verified is None:
                                    continue
                                rels_by_chunk[chunk_id] = verified
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("KG relation verify pass failed; continuing without verification: %s", str(exc)[:200])

                    succeeded_rel_chunk_ids: list[object] = []
                    rel_rows: list[KgRelation] = []

                    for chunk_id, rels, ok in rel_results:
                        ch = chunk_by_id.get(chunk_id)
                        if ch is None:
                            continue
                        if ok and chunk_id in rels_by_chunk:
                            rels = rels_by_chunk.get(chunk_id) or []
                        if ok:
                            succeeded_rel_chunk_ids.append(chunk_id)

                        refs: dict[str, object] = {"chunk_index": ch.chunk_index, "page": ch.page_number}
                        if getattr(ch, "start_char", None) is not None:
                            refs["start_char"] = int(ch.start_char)
                        if getattr(ch, "end_char", None) is not None:
                            refs["end_char"] = int(ch.end_char)
                        meta = getattr(ch, "doc_metadata", None)
                        meta_dict = meta if isinstance(meta, dict) else {}
                        source_val = meta_dict.get("source")
                        if isinstance(source_val, str) and source_val.strip():
                            refs["source"] = source_val.strip()
                        pipeline_hash_val = meta_dict.get("pipeline_hash") or meta_dict.get("active_pipeline_hash")
                        if isinstance(pipeline_hash_val, str) and pipeline_hash_val.strip():
                            refs["pipeline_hash"] = pipeline_hash_val.strip()[:200]
                        refs["chunk_key"] = chunk_key_by_id.get(ch.id) or str(ch.chunk_index)
                        refs["content_hash"] = chunk_hash_by_id.get(ch.id) or ""
                        refs["content_len"] = int(chunk_len_by_id.get(ch.id, 0) or 0)
                        pipeline_hash = str(refs.get("pipeline_hash") or "").strip() or None

                        seen_rel_keys: set[tuple[object, str, object]] = set()
                        # If LLM extraction failed, we do not replace old relations. To keep the alias heuristic
                        # idempotent, skip inserting alias edges that already exist for this chunk.
                        alias_specs = alias_specs_by_chunk.get(chunk_id) or []
                        llm_aliases_existing = llm_aliases_by_chunk.get(chunk_id) or []
                        if (not ok) and (alias_specs or llm_aliases_existing):
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

                        cand_map = {c.cid: c for c in (candidates_by_chunk.get(chunk_id) or [])}
                        if ok:
                            for rel in rels or []:
                                if not isinstance(rel, dict):
                                    continue
                                relation_evidence_stats["total_raw"] += 1
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

                                # Evidence gating (optional but recommended): require an in-text quote for the relation.
                                rel_refs = dict(refs)
                                evq = rel.get("evidence_quote")
                                evidence = coerce_evidence(
                                    text=(ch.content or ""),
                                    evidence_quote=(str(evq).strip() if isinstance(evq, str) else None),
                                    fallback_mention=None,
                                    max_quote_chars=240,
                                )
                                if evidence is None and evidence_required:
                                    relation_evidence_stats["dropped_no_evidence"] += 1
                                    continue
                                if evidence is not None:
                                    # Best-effort: ensure both endpoints appear in the quote to reduce "two entities exist"
                                    # false positives.
                                    # Keep this deterministic and conservative: we require both endpoints to be
                                    # mentioned in the evidence quote (after lightweight normalization).
                                    subj_ok = surface_mentioned(quote=evidence.quote, surface=str(subj_cand.name or "")) or (
                                        surface_mentioned(quote=evidence.quote, surface=str(subj_cand.normalized_name or ""))
                                    )
                                    obj_ok = surface_mentioned(quote=evidence.quote, surface=str(obj_cand.name or "")) or (
                                        surface_mentioned(quote=evidence.quote, surface=str(obj_cand.normalized_name or ""))
                                    )
                                    if evidence_required and not (subj_ok and obj_ok):
                                        relation_evidence_stats["dropped_missing_endpoints"] += 1
                                        continue
                                    rel_refs["evidence_quote"] = evidence.quote
                                    rel_refs["evidence_start_char"] = int(evidence.start_char)
                                    rel_refs["evidence_end_char"] = int(evidence.end_char)
                                    rel_refs["evidence_source"] = str(getattr(evidence, "source", "") or "").strip() or "quote"

                                relation_evidence_stats["kept"] += 1
                                rel_rows.append(
                                    KgRelation(
                                        tenant_id=tenant_id,
                                        pipeline_hash=pipeline_hash,
                                        document_id=ch.document_id,
                                        chunk_id=ch.id,
                                        event_id=None,
                                        subject_entity_id=subj_ent_id,
                                        predicate=pred,
                                        predicate_raw=(str(rel.get("predicate_raw") or "").strip() or None),
                                        object_entity_id=obj_ent_id,
                                        confidence=conf,
                                        qualifiers=rel.get("qualifiers") if isinstance(rel.get("qualifiers"), dict) else None,
                                        references=rel_refs,
                                        extra_data={
                                            "kg_prompt_template_id": chosen_template_id,
                                            "kg_prompt_template_key": config.prompt_template_key,
                                            "kg_prompt_ab_experiment_key": config.prompt_ab_experiment_key,
                                        },
                                    )
                                )

                        # Insert heuristic alias_of edges (best-effort; may run even if LLM failed).
                        for etype, alias_norm, canonical_norm, method, alias_quote in alias_specs:
                            subj_ent_id = entity_id_by_key.get((etype, alias_norm))
                            obj_ent_id = entity_id_by_key.get((etype, canonical_norm))
                            if subj_ent_id is None or obj_ent_id is None or subj_ent_id == obj_ent_id:
                                alias_diag["edges_skipped_missing_entities"] = (
                                    int(alias_diag.get("edges_skipped_missing_entities", 0) or 0) + 1
                                )
                                _alias_bump(ch.document_id, "kg_alias_edges_skipped_missing_entities", 1)
                                continue
                            rel_key = (subj_ent_id, "alias_of", obj_ent_id)
                            if rel_key in seen_rel_keys or (obj_ent_id, "alias_of", subj_ent_id) in seen_rel_keys:
                                alias_diag["edges_skipped_duplicate"] = (
                                    int(alias_diag.get("edges_skipped_duplicate", 0) or 0) + 1
                                )
                                _alias_bump(ch.document_id, "kg_alias_edges_skipped_duplicate", 1)
                                continue
                            seen_rel_keys.add(rel_key)

                            alias_diag["edges_appended"] = int(alias_diag.get("edges_appended", 0) or 0) + 1
                            _alias_bump(ch.document_id, "kg_alias_edges_appended", 1)

                            alias_refs = dict(refs)
                            evidence = coerce_evidence(
                                text=(ch.content or ""),
                                evidence_quote=(str(alias_quote).strip() or None),
                                fallback_mention=None,
                                max_quote_chars=240,
                            )
                            if evidence is None and evidence_required:
                                continue
                            if evidence is not None:
                                alias_refs["evidence_quote"] = evidence.quote
                                alias_refs["evidence_start_char"] = int(evidence.start_char)
                                alias_refs["evidence_end_char"] = int(evidence.end_char)
                                alias_refs["evidence_source"] = str(getattr(evidence, "source", "") or "").strip() or "quote"
                            rel_rows.append(
                                KgRelation(
                                    tenant_id=tenant_id,
                                    pipeline_hash=pipeline_hash,
                                    document_id=ch.document_id,
                                    chunk_id=ch.id,
                                    event_id=None,
                                    subject_entity_id=subj_ent_id,
                                    predicate="alias_of",
                                    predicate_raw=None,
                                    object_entity_id=obj_ent_id,
                                    confidence=float(alias_conf),
                                    qualifiers={"method": "heuristic_alias", "pattern": str(method or "")},
                                    references=alias_refs,
                                    extra_data={
                                        "kg_prompt_template_id": chosen_template_id,
                                        "kg_prompt_template_key": config.prompt_template_key,
                                        "kg_prompt_ab_experiment_key": config.prompt_ab_experiment_key,
                                    },
                                    )
                                )

                        # Insert LLM-derived alias_of edges from the entity verification pass (best-effort).
                        llm_aliases = llm_aliases_by_chunk.get(chunk_id) or []
                        for item in llm_aliases:
                            if not isinstance(item, dict):
                                continue
                            alias_cid = str(item.get("alias_id") or "").strip()
                            canon_cid = str(item.get("canonical_id") or "").strip()
                            if not alias_cid or not canon_cid or alias_cid == canon_cid:
                                continue
                            alias_cand = cand_map.get(alias_cid)
                            canon_cand = cand_map.get(canon_cid)
                            if alias_cand is None or canon_cand is None:
                                continue

                            etype = str(alias_cand.type or "unknown").strip() or "unknown"
                            if str(canon_cand.type or "unknown").strip() != etype:
                                continue

                            alias_key = (etype, str(alias_cand.normalized_name or "").strip())
                            canon_key = (etype, str(canon_cand.normalized_name or "").strip())
                            subj_ent_id = entity_id_by_key.get(alias_key)
                            obj_ent_id = entity_id_by_key.get(canon_key)
                            if subj_ent_id is None or obj_ent_id is None or subj_ent_id == obj_ent_id:
                                continue

                            rel_key = (subj_ent_id, "alias_of", obj_ent_id)
                            if rel_key in seen_rel_keys or (obj_ent_id, "alias_of", subj_ent_id) in seen_rel_keys:
                                continue
                            seen_rel_keys.add(rel_key)

                            llm_refs = dict(refs)
                            evidence = coerce_evidence(
                                text=(ch.content or ""),
                                evidence_quote=(str(item.get("evidence_quote") or "").strip() or None),
                                fallback_mention=None,
                                max_quote_chars=240,
                            )
                            if evidence is None and evidence_required:
                                continue
                            if evidence is not None:
                                llm_refs["evidence_quote"] = evidence.quote
                                llm_refs["evidence_start_char"] = int(evidence.start_char)
                                llm_refs["evidence_end_char"] = int(evidence.end_char)
                                llm_refs["evidence_source"] = str(getattr(evidence, "source", "") or "").strip() or "quote"

                            try:
                                conf = float(item.get("confidence") or 0.9)
                            except Exception:
                                conf = 0.9
                            conf = max(0.0, min(1.0, conf))

                            rel_rows.append(
                                KgRelation(
                                    tenant_id=tenant_id,
                                    pipeline_hash=pipeline_hash,
                                    document_id=ch.document_id,
                                    chunk_id=ch.id,
                                    event_id=None,
                                    subject_entity_id=subj_ent_id,
                                    predicate="alias_of",
                                    predicate_raw=None,
                                    object_entity_id=obj_ent_id,
                                    confidence=conf,
                                    qualifiers={"method": "llm_entity_verify", "kind": "alias"},
                                    references=llm_refs,
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
                    except Exception as exc:
                        logger.debug("Ignoring non-critical KG extractor fallback failure: %s", exc)
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
                    skill_evidence_required = bool(getattr(settings, "KG_SKILL_EVIDENCE_REQUIRED", False))

                    chunk_by_id = {c.id: c for c in resolved_chunks if getattr(c, "id", None) is not None}
                    events_by_chunk: dict[object, list[object]] = {}
                    for ev in new_events:
                        cid = getattr(ev, "chunk_id", None)
                        if cid is None or cid not in cleanup_chunk_ids:
                            continue
                        events_by_chunk.setdefault(cid, []).append(ev)

                    parser = EntityValueParser()
                    skill_processor = SkillProcessor(llm_client=llm_client)

                    def _dedupe_surfaces(values: object, *, limit: int) -> list[str]:
                        lim = max(0, int(limit or 0))
                        if lim <= 0:
                            return []
                        seq = values if isinstance(values, list) else []
                        out: list[str] = []
                        seen: set[str] = set()
                        for item in seq:
                            s = str(item or "").strip()
                            if not s:
                                continue
                            key = s.casefold() if s.isascii() else s
                            if key in seen:
                                continue
                            seen.add(key)
                            out.append(s)
                            if len(out) >= lim:
                                break
                        return out

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

                            skill_evidence_stats["total_raw"] += 1
                            evq = raw.get("evidence_quote")
                            evidence = coerce_evidence(
                                text=(ch.content or ""),
                                evidence_quote=(str(evq).strip() if isinstance(evq, str) else None),
                                fallback_mention=name,
                                max_quote_chars=240,
                            )
                            if evidence is None and skill_evidence_required:
                                skill_evidence_stats["dropped_no_evidence"] += 1
                                continue

                            summary = str(raw.get("summary") or "").strip() or None
                            category = str(raw.get("category") or "").strip() or None
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
                                        "category": category,
                                        "steps": [str(s).strip() for s in steps if str(s).strip()][:50],
                                        "inputs": [str(s).strip() for s in inputs if str(s).strip()][:50],
                                        "outputs": [str(s).strip() for s in outputs if str(s).strip()][:50],
                                        "tools": [str(s).strip() for s in tools if str(s).strip()][:50],
                                        "tags": _dedupe_surfaces(tags, limit=10),
                                        "confidence": raw.get("confidence"),
                                    },
                                    "_embed_text": embed_text,
                                    "_chunk_id": chunk_id,
                                    "_evidence_quote": (evidence.quote if evidence is not None else None),
                                    "_evidence_start_char": (int(evidence.start_char) if evidence is not None else None),
                                    "_evidence_end_char": (int(evidence.end_char) if evidence is not None else None),
                                    "_evidence_source": (
                                        str(getattr(evidence, "source", "") or "").strip() if evidence is not None else None
                                    ),
                                }
                            )
                            skill_evidence_stats["kept"] += 1
                            if len(kept) >= max_skills_per_chunk:
                                break

                        if kept:
                            skills_by_chunk[chunk_id] = kept
                            for item in kept:
                                text = str(item.get("_embed_text") or "").strip()
                                if text:
                                    skill_embed_texts.append(text)

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

                        # Optional: SkillNet-style taxonomy nodes + relations.
                        # Note: these are stored in kg_relations, so we only run them when relations are enabled.
                        tag_id_by_norm: dict[str, object] = {}
                        category_id_by_norm: dict[str, object] = {}
                        if extract_relations_enabled:
                            try:
                                tag_surface_by_norm: dict[str, str] = {}
                                category_surface_by_norm: dict[str, str] = {}

                                for _chunk_id, items in skills_by_chunk.items():
                                    for item in items or []:
                                        if not isinstance(item, dict):
                                            continue
                                        extra = item.get("extra_data") if isinstance(item.get("extra_data"), dict) else {}
                                        tags = extra.get("tags") if isinstance(extra.get("tags"), list) else []
                                        for tag in tags:
                                            t = str(tag or "").strip()
                                            if not t:
                                                continue
                                            t_norm = parser.normalize_name(t)
                                            if not t_norm:
                                                continue
                                            tag_surface_by_norm.setdefault(t_norm, t)

                                        cat = str(extra.get("category") or "").strip()
                                        if cat:
                                            c_norm = parser.normalize_name(cat)
                                            if c_norm:
                                                category_surface_by_norm.setdefault(c_norm, cat)

                                tag_vectors_by_norm: dict[str, list[float]] = {}
                                category_vectors_by_norm: dict[str, list[float]] = {}

                                to_embed: list[str] = list(tag_surface_by_norm.values()) + list(
                                    category_surface_by_norm.values()
                                )
                                if to_embed:
                                    try:
                                        vectors = await embedder.generate_batch(to_embed)
                                    except Exception as exc:  # noqa: BLE001
                                        logger.warning(
                                            "KG skill taxonomy embedding failed; proceeding without vectors: %s",
                                            str(exc)[:200],
                                        )
                                        vectors = [[] for _ in to_embed]

                                    for idx, vec in enumerate(list(vectors or [])):
                                        surface = str(to_embed[idx] or "").strip()
                                        if not surface:
                                            continue
                                        norm = parser.normalize_name(surface)
                                        if not norm:
                                            continue
                                        if surface in tag_surface_by_norm.values():
                                            if vec:
                                                tag_vectors_by_norm[norm] = list(vec)
                                        elif surface in category_surface_by_norm.values():
                                            if vec:
                                                category_vectors_by_norm[norm] = list(vec)

                                tag_inputs: list[dict] = []
                                for norm, surface in tag_surface_by_norm.items():
                                    tag_inputs.append(
                                        {
                                            "name": surface,
                                            "normalized_name": norm,
                                            "type": "SkillTag",
                                            "description": None,
                                            "vector": tag_vectors_by_norm.get(norm),
                                            "extra_data": {"source": "skill_taxonomy"},
                                        }
                                    )

                                category_inputs: list[dict] = []
                                for norm, surface in category_surface_by_norm.items():
                                    category_inputs.append(
                                        {
                                            "name": surface,
                                            "normalized_name": norm,
                                            "type": "SkillCategory",
                                            "description": None,
                                            "vector": category_vectors_by_norm.get(norm),
                                            "extra_data": {"source": "skill_taxonomy"},
                                        }
                                    )

                                if tag_inputs:
                                    upserted_tags = indexer.upsert_entities(
                                        tenant_id=tenant_id,
                                        entities=tag_inputs,
                                        options=index_options,
                                        commit=True,
                                    )
                                    for ent in upserted_tags or []:
                                        if str(getattr(ent, "type", "") or "") != "SkillTag":
                                            continue
                                        norm = str(getattr(ent, "normalized_name", "") or "").strip()
                                        if norm:
                                            tag_id_by_norm[norm] = getattr(ent, "id", None)

                                if category_inputs:
                                    upserted_categories = indexer.upsert_entities(
                                        tenant_id=tenant_id,
                                        entities=category_inputs,
                                        options=index_options,
                                        commit=True,
                                    )
                                    for ent in upserted_categories or []:
                                        if str(getattr(ent, "type", "") or "") != "SkillCategory":
                                            continue
                                        norm = str(getattr(ent, "normalized_name", "") or "").strip()
                                        if norm:
                                            category_id_by_norm[norm] = getattr(ent, "id", None)
                            except Exception as exc:  # noqa: BLE001
                                logger.warning(
                                    "KG skill taxonomy upsert failed; continuing without taxonomy nodes: %s",
                                    str(exc)[:200],
                                )

                        # Link: event -> skill (role="skill") with provenance.
                        links: list[KgEventEntity] = []
                        skill_rel_rows: list[KgRelation] = []
                        for chunk_id, items in skills_by_chunk.items():
                            ch = chunk_by_id.get(chunk_id)
                            if ch is None:
                                continue

                            refs_base: dict[str, object] = {"chunk_index": ch.chunk_index, "page": ch.page_number}
                            if getattr(ch, "start_char", None) is not None:
                                refs_base["start_char"] = int(ch.start_char)
                            if getattr(ch, "end_char", None) is not None:
                                refs_base["end_char"] = int(ch.end_char)
                            meta = getattr(ch, "doc_metadata", None)
                            meta_dict = meta if isinstance(meta, dict) else {}
                            source_val = meta_dict.get("source")
                            if isinstance(source_val, str) and source_val.strip():
                                refs_base["source"] = source_val.strip()
                            pipeline_hash_val = meta_dict.get("pipeline_hash") or meta_dict.get("active_pipeline_hash")
                            if isinstance(pipeline_hash_val, str) and pipeline_hash_val.strip():
                                refs_base["pipeline_hash"] = pipeline_hash_val.strip()[:200]
                            refs_base["chunk_key"] = chunk_key_by_id.get(ch.id) or str(ch.chunk_index)
                            refs_base["content_hash"] = chunk_hash_by_id.get(ch.id) or ""
                            refs_base["content_len"] = int(chunk_len_by_id.get(ch.id, 0) or 0)
                            pipeline_hash = str(refs_base.get("pipeline_hash") or "").strip() or None

                            link_extra_base = build_event_entity_provenance(
                                document_id=ch.document_id,
                                chunk_id=ch.id,
                                references=refs_base,
                            )
                            chunk_text = str(getattr(ch, "content", "") or "")

                            # Skill taxonomy relations: Skill -> belong_to -> (SkillTag/SkillCategory)
                            # and Skill -> compose_with -> Skill (co-extracted within the same chunk).
                            if extract_relations_enabled:
                                seen_skill_rel_keys: set[tuple[object, str, object]] = set()
                                # Dedupe against existing rows on best-effort basis (only needed when relation extraction
                                # failed earlier and we didn't replace relations for this chunk).
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
                                            KgRelation.predicate.in_(["belong_to", "compose_with", "depends_on"]),
                                        )
                                        .all()
                                    )
                                    for subj_id, pred, obj_id in existing:
                                        if subj_id is None or obj_id is None:
                                            continue
                                        seen_skill_rel_keys.add((subj_id, str(pred or "").strip(), obj_id))
                                except Exception as exc:
                                    logger.debug("Ignoring non-critical KG extractor fallback failure: %s", exc)

                                skill_ids_in_chunk: list[tuple[object, float, dict]] = []
                                for item in items:
                                    if not isinstance(item, dict):
                                        continue
                                    norm = str(item.get("normalized_name") or "").strip()
                                    skill_id = skill_id_by_norm.get(norm)
                                    if not skill_id:
                                        continue
                                    conf = float(item.get("_confidence") or 0.6)
                                    conf = max(0.0, min(1.0, conf))
                                    skill_ids_in_chunk.append((skill_id, conf, item))

                                    extra = item.get("extra_data") if isinstance(item.get("extra_data"), dict) else {}
                                    tags = extra.get("tags") if isinstance(extra.get("tags"), list) else []
                                    for tag in tags:
                                        surface = str(tag or "").strip()
                                        if not surface:
                                            continue
                                        t_norm = parser.normalize_name(surface)
                                        tag_id = tag_id_by_norm.get(t_norm)
                                        if not tag_id:
                                            continue
                                        rel_key = (skill_id, "belong_to", tag_id)
                                        if rel_key in seen_skill_rel_keys:
                                            continue
                                        tag_evidence = coerce_evidence(
                                            text=chunk_text,
                                            evidence_quote=None,
                                            fallback_mention=surface,
                                            max_quote_chars=240,
                                        )
                                        if tag_evidence is None and skill_evidence_required:
                                            skill_evidence_stats["taxonomy_edges_dropped_no_evidence"] += 1
                                            continue
                                        seen_skill_rel_keys.add(rel_key)
                                        edge_refs = dict(refs_base)
                                        if tag_evidence is not None:
                                            edge_refs["evidence_quote"] = tag_evidence.quote
                                            edge_refs["evidence_start_char"] = int(tag_evidence.start_char)
                                            edge_refs["evidence_end_char"] = int(tag_evidence.end_char)
                                            edge_refs["evidence_source"] = (
                                                str(getattr(tag_evidence, "source", "") or "").strip() or "mention"
                                            )
                                        skill_rel_rows.append(
                                            KgRelation(
                                                tenant_id=tenant_id,
                                                pipeline_hash=pipeline_hash,
                                                document_id=ch.document_id,
                                                chunk_id=ch.id,
                                                event_id=None,
                                                subject_entity_id=skill_id,
                                                predicate="belong_to",
                                                predicate_raw=None,
                                                object_entity_id=tag_id,
                                                confidence=conf,
                                                qualifiers={"method": "skill_taxonomy", "kind": "tag"},
                                                references=edge_refs,
                                                extra_data={
                                                    "kg_prompt_template_id": chosen_template_id,
                                                    "kg_prompt_template_key": config.prompt_template_key,
                                                    "kg_prompt_ab_experiment_key": config.prompt_ab_experiment_key,
                                                },
                                            )
                                        )
                                        skill_evidence_stats["taxonomy_edges_kept"] += 1

                                    cat = str(extra.get("category") or "").strip()
                                    if cat:
                                        c_norm = parser.normalize_name(cat)
                                        cat_id = category_id_by_norm.get(c_norm)
                                        if cat_id:
                                            rel_key = (skill_id, "belong_to", cat_id)
                                            if rel_key in seen_skill_rel_keys:
                                                continue
                                            cat_evidence = coerce_evidence(
                                                text=chunk_text,
                                                evidence_quote=None,
                                                fallback_mention=cat,
                                                max_quote_chars=240,
                                            )
                                            if cat_evidence is None and skill_evidence_required:
                                                skill_evidence_stats["taxonomy_edges_dropped_no_evidence"] += 1
                                                continue
                                            seen_skill_rel_keys.add(rel_key)
                                            edge_refs = dict(refs_base)
                                            if cat_evidence is not None:
                                                edge_refs["evidence_quote"] = cat_evidence.quote
                                                edge_refs["evidence_start_char"] = int(cat_evidence.start_char)
                                                edge_refs["evidence_end_char"] = int(cat_evidence.end_char)
                                                edge_refs["evidence_source"] = (
                                                    str(getattr(cat_evidence, "source", "") or "").strip() or "mention"
                                                )
                                            skill_rel_rows.append(
                                                KgRelation(
                                                    tenant_id=tenant_id,
                                                    pipeline_hash=pipeline_hash,
                                                    document_id=ch.document_id,
                                                    chunk_id=ch.id,
                                                    event_id=None,
                                                    subject_entity_id=skill_id,
                                                    predicate="belong_to",
                                                    predicate_raw=None,
                                                    object_entity_id=cat_id,
                                                    confidence=conf,
                                                    qualifiers={"method": "skill_taxonomy", "kind": "category"},
                                                    references=edge_refs,
                                                    extra_data={
                                                        "kg_prompt_template_id": chosen_template_id,
                                                        "kg_prompt_template_key": config.prompt_template_key,
                                                        "kg_prompt_ab_experiment_key": config.prompt_ab_experiment_key,
                                                    },
                                                )
                                            )
                                            skill_evidence_stats["taxonomy_edges_kept"] += 1

                                # compose_with edges between skills co-extracted in the same chunk (bounded by max_skills_per_chunk)
                                if len(skill_ids_in_chunk) >= 2:
                                    for i in range(len(skill_ids_in_chunk)):
                                        for j in range(i + 1, len(skill_ids_in_chunk)):
                                            a_id, a_conf, a_item = skill_ids_in_chunk[i]
                                            b_id, b_conf, b_item = skill_ids_in_chunk[j]
                                            conf = max(0.0, min(1.0, float(min(a_conf, b_conf) * 0.8)))

                                            # Evidence for composability is grounded as "co-mentioned in this chunk".
                                            # We try to persist a short span that covers both skill evidence spans.
                                            pair_refs = dict(refs_base)
                                            pair_quote: str | None = None
                                            pair_start: int | None = None
                                            pair_end: int | None = None
                                            try:
                                                a_s = a_item.get("_evidence_start_char")
                                                a_e = a_item.get("_evidence_end_char")
                                                b_s = b_item.get("_evidence_start_char")
                                                b_e = b_item.get("_evidence_end_char")
                                                if (
                                                    isinstance(a_s, int)
                                                    and isinstance(a_e, int)
                                                    and isinstance(b_s, int)
                                                    and isinstance(b_e, int)
                                                    and chunk_text
                                                ):
                                                    start = int(min(a_s, b_s))
                                                    end = int(max(a_e, b_e))
                                                    if 0 <= start < end <= len(chunk_text):
                                                        raw_quote = chunk_text[start:end]
                                                        lstrip_len = len(raw_quote) - len(raw_quote.lstrip())
                                                        rstrip_len = len(raw_quote) - len(raw_quote.rstrip())
                                                        start2 = start + lstrip_len
                                                        end2 = end - rstrip_len
                                                        if 0 <= start2 < end2 <= len(chunk_text):
                                                            q = chunk_text[start2:end2]
                                                            if q and len(q) <= 240:
                                                                pair_quote = q
                                                                pair_start = int(start2)
                                                                pair_end = int(end2)
                                            except Exception:
                                                pair_quote = None
                                                pair_start = None
                                                pair_end = None

                                            if pair_quote is None and skill_evidence_required:
                                                skill_evidence_stats["taxonomy_edges_dropped_no_evidence"] += 1
                                                continue
                                            if pair_quote is not None:
                                                pair_refs["evidence_quote"] = pair_quote
                                                pair_refs["evidence_source"] = "quote"
                                                if pair_start is not None:
                                                    pair_refs["evidence_start_char"] = int(pair_start)
                                                if pair_end is not None:
                                                    pair_refs["evidence_end_char"] = int(pair_end)
                                            for subj, obj in ((a_id, b_id), (b_id, a_id)):
                                                rel_key = (subj, "compose_with", obj)
                                                if rel_key in seen_skill_rel_keys:
                                                    continue
                                                seen_skill_rel_keys.add(rel_key)
                                                skill_rel_rows.append(
                                                    KgRelation(
                                                        tenant_id=tenant_id,
                                                        pipeline_hash=pipeline_hash,
                                                        document_id=ch.document_id,
                                                        chunk_id=ch.id,
                                                        event_id=None,
                                                        subject_entity_id=subj,
                                                        predicate="compose_with",
                                                        predicate_raw=None,
                                                        object_entity_id=obj,
                                                        confidence=conf,
                                                        qualifiers={"method": "skill_taxonomy", "kind": "compose_with"},
                                                        references=pair_refs,
                                                        extra_data={
                                                            "kg_prompt_template_id": chosen_template_id,
                                                            "kg_prompt_template_key": config.prompt_template_key,
                                                            "kg_prompt_ab_experiment_key": config.prompt_ab_experiment_key,
                                                        },
                                                    )
                                                )
                                                skill_evidence_stats["taxonomy_edges_kept"] += 1

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
                                    link_extra = dict(link_extra_base or {})
                                    evq = item.get("_evidence_quote")
                                    if isinstance(evq, str) and evq.strip():
                                        link_extra["evidence_quote"] = evq.strip()[:240]
                                    evsrc = item.get("_evidence_source")
                                    if isinstance(evsrc, str) and evsrc.strip():
                                        link_extra["evidence_source"] = evsrc.strip()
                                    evs = item.get("_evidence_start_char")
                                    eve = item.get("_evidence_end_char")
                                    if isinstance(evs, int):
                                        link_extra["evidence_start_char"] = int(evs)
                                    if isinstance(eve, int):
                                        link_extra["evidence_end_char"] = int(eve)
                                    links.append(
                                        KgEventEntity(
                                            event_id=ev_id,
                                            entity_id=skill_id,
                                            weight=conf,
                                            role="skill",
                                            extra_data=(link_extra or None),
                                            )
                                    )

                        if links or skill_rel_rows:
                            if links:
                                session.add_all(links)
                            if skill_rel_rows:
                                session.add_all(skill_rel_rows)
                            session.commit()
                except Exception as exc:  # noqa: BLE001
                    try:
                        session.rollback()
                    except Exception as exc:
                        logger.debug("Ignoring non-critical KG extractor fallback failure: %s", exc)
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
                    "alias_heuristics": dict(alias_diag),
                    "evidence_required": bool(evidence_required),
                    "entity_evidence": dict(entity_evidence_stats),
                    "relation_evidence": dict(relation_evidence_stats),
                    "skill_evidence": dict(skill_evidence_stats),
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
                alias_stats_by_doc=alias_stats_by_doc,
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
        alias_stats_by_doc: dict[object, dict[str, int]] | None = None,
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

            extracted_at = datetime.now(UTC).isoformat()
            # Count events by document using chunk->doc mapping for robustness.
            event_count_by_doc: dict[object, int] = dict.fromkeys(doc_ids, 0)
            for ev in kept_events:
                cid = getattr(ev, "chunk_id", None)
                doc_id = chunk_id_to_doc_id.get(cid) if cid is not None else getattr(ev, "document_id", None)
                if doc_id in event_count_by_doc:
                    event_count_by_doc[doc_id] += 1

            skipped_count_by_doc: dict[object, int] = dict.fromkeys(doc_ids, 0)
            failed_count_by_doc: dict[object, int] = dict.fromkeys(doc_ids, 0)
            short_skipped_count_by_doc: dict[object, int] = dict.fromkeys(doc_ids, 0)
            retry_count_by_doc: dict[object, int] = dict.fromkeys(doc_ids, 0)
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
                alias_stats = alias_stats_by_doc.get(doc.id, {}) if isinstance(alias_stats_by_doc, dict) else {}
                for key, val in (alias_stats.items() if isinstance(alias_stats, dict) else []):
                    if not key:
                        continue
                    try:
                        meta[str(key)] = int(val or 0)
                    except Exception:
                        continue
                doc.doc_metadata = meta
            session.commit()
        except Exception as exc:  # noqa: BLE001
            try:
                session.rollback()
            except Exception as exc:
                logger.debug("Ignoring non-critical KG extractor fallback failure: %s", exc)
            logger.warning("Failed to write back kg metrics to document metadata: %s", str(exc)[:200])
