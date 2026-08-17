"""
Event extractor coordinating LLM + embeddings + persistence.
"""

import asyncio
import hashlib
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace

from langchain_core.documents import Document as LCDocument

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
from app.rag.kg.extraction.heuristic_extractor import HeuristicExtractor
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
from app.rag.pipeline_plugins.runtime import apply_kg_python_plugin
from app.rag.preprocessing.normalization import normalize_text
from app.services.indexer import Indexer
from app.services.metrics_logger import log_metrics
from app.services.prompt_resolver import resolve_prompt_template
from app.types.indexing import EventEntityInput, IndexingOptions, IndexKind, IndexRecord

logger = get_logger("kg.extract.extractor")
_KG_EXTRACTOR_FALLBACK_LOG_MESSAGE = "Ignoring non-critical KG extractor fallback failure: %s"

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


def _append_unique_index(picked: list[int], seen: set[int], idx: int) -> None:
    if idx in seen:
        return
    seen.add(idx)
    picked.append(idx)


def _seed_uniform_sample_indices(indices: list[int], k: int) -> tuple[list[int], set[int]]:
    n = len(indices)
    picked: list[int] = []
    seen: set[int] = set()
    for i in range(k):
        pos = round(i * (n - 1) / (k - 1))
        pos = max(0, min(n - 1, int(pos)))
        _append_unique_index(picked, seen, indices[pos])
    return picked, seen


def _backfill_uniform_sample_indices(indices: list[int], picked: list[int], seen: set[int], k: int) -> list[int]:
    for idx in indices:
        if len(picked) >= k:
            break
        _append_unique_index(picked, seen, idx)
    return picked[:k]


def _uniform_sample_indices(indices: list[int], k: int) -> list[int]:
    if k <= 0:
        return []
    if k >= len(indices):
        return list(indices)
    if len(indices) == 1:
        return [indices[0]]
    if k == 1:
        return [indices[len(indices) // 2]]

    picked, seen = _seed_uniform_sample_indices(indices, k)
    return _backfill_uniform_sample_indices(indices, picked, seen, k)


def _apply_document_chunk_budget(
    chunks: list[DocumentChunk],
    *,
    max_chunks_per_document: int,
    strategy: str,
) -> tuple[list[DocumentChunk], dict[object, dict[str, int | str]]]:
    if max_chunks_per_document <= 0 or not chunks:
        return chunks, {}

    strategy_norm = (strategy or "uniform").strip().lower() or "uniform"
    if strategy_norm not in {"head", "uniform"}:
        strategy_norm = "uniform"

    grouped: dict[object, list[DocumentChunk]] = {}
    doc_order: list[object] = []
    for chunk in chunks:
        doc_id = getattr(chunk, "document_id", None)
        if doc_id not in grouped:
            grouped[doc_id] = []
            doc_order.append(doc_id)
        grouped[doc_id].append(chunk)

    keep_ids: set[object] = set()
    budget_stats: dict[object, dict[str, int | str]] = {}
    for doc_id in doc_order:
        doc_chunks = grouped.get(doc_id) or []
        total = len(doc_chunks)
        if total <= max_chunks_per_document:
            for chunk in doc_chunks:
                keep_ids.add(getattr(chunk, "id", None))
            budget_stats[doc_id] = {
                "strategy": strategy_norm,
                "total": int(total),
                "kept": int(total),
                "skipped": 0,
            }
            continue

        if strategy_norm == "head":
            selected = doc_chunks[:max_chunks_per_document]
        else:
            sampled_positions = set(_uniform_sample_indices(list(range(total)), max_chunks_per_document))
            selected = [chunk for idx, chunk in enumerate(doc_chunks) if idx in sampled_positions]

        for chunk in selected:
            keep_ids.add(getattr(chunk, "id", None))
        budget_stats[doc_id] = {
            "strategy": strategy_norm,
            "total": int(total),
            "kept": int(len(selected)),
            "skipped": int(total - len(selected)),
        }

    kept_chunks = [chunk for chunk in chunks if getattr(chunk, "id", None) in keep_ids]
    return kept_chunks, budget_stats


def _release_idle_transaction(session) -> None:  # noqa: ANN001
    """Release read-only DB transactions before long LLM/vector work."""
    try:
        session.expunge_all()
    except Exception as exc:
        logger.debug("Ignoring non-critical KG session cleanup failure: %s", exc)
    try:
        session.rollback()
    except Exception as exc:
        logger.debug("Ignoring non-critical KG session cleanup failure: %s", exc)


def _normalize_prompt_selector_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _compute_content_stats(text: str) -> tuple[str, int]:
    normalized = normalize_text(text or "", normalize_line_endings=True, remove_control_chars=True)
    stripped = (normalized or "").strip()
    return hashlib.sha256(stripped.encode("utf-8", "ignore")).hexdigest(), int(len(stripped))


def _document_from_chunk(chunk: DocumentChunk) -> LCDocument:
    meta = dict(getattr(chunk, "doc_metadata", None) or {})
    if getattr(chunk, "document_id", None) is not None:
        meta.setdefault("document_id", str(chunk.document_id))
    if getattr(chunk, "id", None) is not None:
        meta.setdefault("chunk_id", str(chunk.id))
    if getattr(chunk, "chunk_index", None) is not None:
        meta.setdefault("chunk_index", int(chunk.chunk_index))
    if getattr(chunk, "page_number", None) is not None:
        meta.setdefault("page_number", int(chunk.page_number))
    if getattr(chunk, "start_char", None) is not None:
        meta.setdefault("start_char", int(chunk.start_char))
    if getattr(chunk, "end_char", None) is not None:
        meta.setdefault("end_char", int(chunk.end_char))
    return LCDocument(
        page_content=str(getattr(chunk, "content", "") or ""),
        metadata=meta,
        id=str(getattr(chunk, "id", "") or ""),
    )


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


def _build_canonicalized_entity(
    *,
    name: str,
    ent_type: str,
    parser: EntityValueParser,
    description: str,
    role: object,
    evidence_quote: str | None,
    normalized_name: str | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "normalized_name": (normalized_name or parser.normalize_name(name)).strip(),
        "type": ent_type,
        "description": description,
        "role": role,
        "evidence_quote": evidence_quote,
    }


def _expand_canonicalized_entity(ent: dict, *, text_fold: str, parser: EntityValueParser) -> list[dict[str, object]]:
    raw_name = str(ent.get("name") or "").strip()
    if not raw_name:
        return []

    raw_type = str(ent.get("type") or "unknown").strip() or "unknown"
    ent_type = parser.normalize_type(raw_type)
    description = str(ent.get("description") or "").strip()
    role = ent.get("role")
    evidence_quote = str(ent.get("evidence_quote") or "").strip() or None

    split = split_trailing_parenthetical_alias(raw_name)
    if split is None:
        return [
            _build_canonicalized_entity(
                name=raw_name,
                normalized_name=str(ent.get("normalized_name") or "").strip() or None,
                ent_type=ent_type,
                parser=parser,
                description=description,
                role=role,
                evidence_quote=evidence_quote,
            )
        ]

    head, tail = split
    direction = choose_alias_direction(head, tail)
    if direction is None:
        return [
            _build_canonicalized_entity(
                name=raw_name,
                normalized_name=str(ent.get("normalized_name") or "").strip() or None,
                ent_type=ent_type,
                parser=parser,
                description=description,
                role=role,
                evidence_quote=evidence_quote,
            )
        ]

    alias_surface, canonical_surface = direction
    if canonical_surface.casefold() not in text_fold or alias_surface.casefold() not in text_fold:
        return [
            _build_canonicalized_entity(
                name=raw_name,
                normalized_name=str(ent.get("normalized_name") or "").strip() or None,
                ent_type=ent_type,
                parser=parser,
                description=description,
                role=role,
                evidence_quote=evidence_quote,
            )
        ]

    return [
        _build_canonicalized_entity(
            name=canonical_surface,
            ent_type=ent_type,
            parser=parser,
            description=description,
            role=role,
            evidence_quote=evidence_quote,
        ),
        _build_canonicalized_entity(
            name=alias_surface,
            ent_type=ent_type,
            parser=parser,
            description="",
            role=role,
            evidence_quote=evidence_quote,
        ),
    ]


def _merge_canonicalized_entity(existing: dict, candidate: dict) -> None:
    if len(str(candidate.get("description") or "")) > len(str(existing.get("description") or "")):
        existing["description"] = candidate.get("description") or ""
    if str(existing.get("evidence_quote") or "").strip():
        return
    evidence_quote = str(candidate.get("evidence_quote") or "").strip()
    if evidence_quote:
        existing["evidence_quote"] = evidence_quote


def _dedupe_canonicalized_entities(expanded: list[dict[str, object]]) -> list[dict]:
    deduped: list[dict] = []
    seen: dict[tuple[str, str], dict] = {}
    for ent in expanded:
        ent_type = str(ent.get("type") or "unknown").strip() or "unknown"
        normalized_name = str(ent.get("normalized_name") or "").strip()
        name = str(ent.get("name") or "").strip()
        if not name or not normalized_name:
            continue
        key = (ent_type, normalized_name)
        existing = seen.get(key)
        if existing is None:
            seen[key] = ent
            deduped.append(ent)
            continue
        _merge_canonicalized_entity(existing, ent)
    return deduped


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

    limit = max(0, int(max_entities or 0))
    if limit <= 0:
        return []

    text_fold = str(chunk_text or "").casefold()
    expanded: list[dict[str, object]] = []
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        expanded.extend(_expand_canonicalized_entity(ent, text_fold=text_fold, parser=parser))

    return _dedupe_canonicalized_entities(expanded)[:limit]


@dataclass
class _ExtractProgress:
    failed_chunks: int = 0
    timed_out_chunks: int = 0
    timeout_chunk_ids: set[object] = field(default_factory=set)
    failed_chunk_ids: set[object] = field(default_factory=set)
    succeeded_chunk_ids: set[object] = field(default_factory=set)
    skipped_chunk_ids: set[object] = field(default_factory=set)
    skipped_short_chunk_ids: set[object] = field(default_factory=set)
    retry_chunk_ids: set[object] = field(default_factory=set)
    retry_attempts_total: int = 0
    llm_called_chunk_ids: set[object] = field(default_factory=set)
    failure_messages: list[str] = field(default_factory=list)


@dataclass
class _ExtractState:
    tenant_id: object
    resolved_chunks: list[DocumentChunk]
    budgeted_chunks: list[DocumentChunk]
    max_chunks_per_document: int
    chunk_budget_strategy: str
    budget_stats_by_doc: dict[object, dict[str, int | str]]
    budget_skipped_chunk_ids: set[object]
    processor: object
    embedder: DocumentProcessor
    backend_selection: SimpleNamespace
    backend_reason: str | None
    prompt_template_content: str | None
    chosen_template_id: str | None
    max_concurrency: int
    max_events_per_chunk: int
    max_entities_per_event: int
    embed_batch_size: int
    chunk_timeout_sec: float
    context_window: int
    min_chars: int
    chunk_max_retries: int
    retry_backoff_sec: float
    replace_existing: bool
    skip_unchanged: bool
    extract_relations_enabled: bool
    extract_skills_enabled: bool
    prompt_selector_expected: dict[str, str]
    chunk_hash_by_id: dict[object, str] = field(default_factory=dict)
    chunk_key_by_id: dict[object, str] = field(default_factory=dict)
    chunk_len_by_id: dict[object, int] = field(default_factory=dict)
    existing_events_by_chunk: dict[object, list[KgSourceEvent]] = field(default_factory=dict)
    kept_events: list[KgSourceEvent] = field(default_factory=list)
    chunks_to_process: list[DocumentChunk] = field(default_factory=list)
    chunk_id_to_pos: dict[object, int] = field(default_factory=dict)
    sem: asyncio.Semaphore | None = None


@dataclass
class _PreparedEventBundle:
    processed_events: list[tuple[DocumentChunk, dict]]
    events_to_index: list[IndexRecord]
    entity_total: int
    entity_evidence_stats: dict[str, int]
    relation_verify_enabled: bool
    evidence_required: bool
    llm_aliases_by_chunk: dict[object, list[dict[str, object]]]


_ENTITY_EVIDENCE_STOP_NORMS = {
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


@dataclass
class _RelationPostIndexContext:
    session: object
    config: ExtractConfig
    index_options: IndexingOptions | None
    indexer: object
    state: _ExtractState
    processed_events: list[tuple[DocumentChunk, dict]]
    result: object
    cleanup_chunk_ids: list[object]
    llm_client: object | None
    alias_diag: dict[str, object]
    alias_stats_by_doc: dict[object, dict[str, int]]
    llm_aliases_by_chunk: dict[object, list[dict[str, object]]]
    relation_verify_enabled: bool
    chosen_template_id: str | None
    evidence_required: bool


@dataclass
class _SkillPostIndexContext:
    session: object
    config: ExtractConfig
    index_options: IndexingOptions | None
    indexer: object
    state: _ExtractState
    cleanup_chunk_ids: list[object]
    llm_client: object | None
    chosen_template_id: str | None
    evidence_required: bool
    new_events: Sequence[KgSourceEvent]


@dataclass
class _SkillPassData:
    chunk_by_id: dict[object, DocumentChunk]
    events_by_chunk: dict[object, list[object]]
    skills_by_chunk: dict[object, list[dict]] = field(default_factory=dict)
    skill_embed_texts: list[str] = field(default_factory=list)
    skill_entity_inputs: list[dict] = field(default_factory=list)
    skill_id_by_norm: dict[str, object] = field(default_factory=dict)
    tag_id_by_norm: dict[str, object] = field(default_factory=dict)
    category_id_by_norm: dict[str, object] = field(default_factory=dict)


@dataclass
class _RelationPassData:
    candidates_by_chunk: dict[object, list[CandidateEntity]]
    entity_id_by_key: dict[tuple[str, str], object]
    chunk_by_id: dict[object, DocumentChunk]
    alias_specs_by_chunk: dict[object, list[tuple[str, str, str, str, str]]] = field(default_factory=dict)
    alias_conf: float = 0.95
    rel_results: list[tuple[object, list[dict[str, object]], bool]] = field(default_factory=list)
    rels_by_chunk: dict[object, list[dict[str, object]]] = field(default_factory=dict)


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
        return await self._extract_with_session(
            config,
            chunks=chunks,
            index_options=index_options,
        )

    async def _extract_with_session(
        self,
        config: ExtractConfig,
        *,
        chunks: Sequence[DocumentChunk] | None = None,
        index_options: IndexingOptions | None = None,
    ) -> list[KgSourceEvent]:
        t0 = time.perf_counter()
        session = SessionLocal()
        try:
            initialized = await self._initialize_extract_context(
                session=session,
                config=config,
                chunks=chunks,
                index_options=index_options,
                t0=t0,
            )
            if isinstance(initialized, list):
                return initialized

            state, progress, alias_diag, alias_stats_by_doc, llm_client = initialized
            tenant_id = state.tenant_id
            processor = state.processor
            backend_selection = state.backend_selection
            backend_reason = state.backend_reason
            max_concurrency = state.max_concurrency
            max_events_per_chunk = state.max_events_per_chunk
            max_entities_per_event = state.max_entities_per_event
            sem = state.sem
            chunk_timeout_sec = state.chunk_timeout_sec
            context_window = state.context_window
            min_chars = state.min_chars
            chunk_max_retries = state.chunk_max_retries
            retry_backoff_sec = state.retry_backoff_sec
            replace_existing = state.replace_existing
            extract_relations_enabled = state.extract_relations_enabled
            chosen_template_id = state.chosen_template_id
            chunk_len_by_id = state.chunk_len_by_id

            extracted = await self._extract_chunk_groups(
                chunks_to_process=state.chunks_to_process,
                processor=processor,
                sem=sem,
                chunk_id_to_pos=state.chunk_id_to_pos,
                chunk_len_by_id=chunk_len_by_id,
                context_window=context_window,
                min_chars=min_chars,
                max_concurrency=max_concurrency,
                max_events_per_chunk=max_events_per_chunk,
                max_entities_per_event=max_entities_per_event,
                chunk_timeout_sec=chunk_timeout_sec,
                chunk_max_retries=chunk_max_retries,
                retry_backoff_sec=retry_backoff_sec,
                progress=progress,
            )

            processed_events = self._build_processed_events(
                extracted,
                max_events_per_chunk=max_events_per_chunk,
                max_entities_per_event=max_entities_per_event,
            )

            event_bundle = await self._prepare_event_bundle(
                state=state,
                config=config,
                processed_events=processed_events,
                llm_client=llm_client,
            )
            processed_events = event_bundle.processed_events
            events_to_index = event_bundle.events_to_index
            entity_total = event_bundle.entity_total
            entity_evidence_stats = event_bundle.entity_evidence_stats
            relation_verify_enabled = event_bundle.relation_verify_enabled
            evidence_required = event_bundle.evidence_required
            llm_aliases_by_chunk = event_bundle.llm_aliases_by_chunk

            if not events_to_index:
                return self._handle_empty_extract_result(
                    session=session,
                    config=config,
                    state=state,
                    progress=progress,
                    processed_events=processed_events,
                    alias_diag=alias_diag,
                    alias_stats_by_doc=alias_stats_by_doc,
                    entity_evidence_stats=entity_evidence_stats,
                    extract_relations_enabled=extract_relations_enabled,
                    t0=t0,
                    evidence_required=evidence_required,
                    backend_selection=backend_selection,
                    backend_reason=backend_reason,
                )

            indexer = Indexer(session)
            result = indexer.upsert(
                tenant_id=tenant_id,
                records=events_to_index,
                options=index_options,
            ).event_result

            new_events = result.events if result else []
            cleanup_chunk_ids = [cid for cid in progress.succeeded_chunk_ids if cid not in progress.skipped_chunk_ids]

            # Optional pass: extract entity->entity relations (triples) per processed chunk.
            # This runs after event/entity indexing so we can map candidate entities to persisted KgEntity ids.
            # IMPORTANT: commit relations before deleting old events when pruning is enabled; otherwise,
            # relation-referenced entities could be pruned prematurely.
            relation_evidence_stats, skill_evidence_stats = await self._run_post_index_passes(
                session=session,
                config=config,
                index_options=index_options,
                indexer=indexer,
                state=state,
                progress=progress,
                processed_events=processed_events,
                result=result,
                new_events=new_events,
                cleanup_chunk_ids=cleanup_chunk_ids,
                llm_client=llm_client,
                alias_diag=alias_diag,
                alias_stats_by_doc=alias_stats_by_doc,
                llm_aliases_by_chunk=llm_aliases_by_chunk,
                relation_verify_enabled=relation_verify_enabled,
                chosen_template_id=chosen_template_id,
                evidence_required=evidence_required,
            )

            replace_cleanup_chunk_ids = list(
                dict.fromkeys(
                    list(cleanup_chunk_ids) + (list(state.budget_skipped_chunk_ids) if replace_existing else [])
                )
            )
            if replace_existing and replace_cleanup_chunk_ids:
                try:
                    indexer.delete_event_indexes_for_chunks(
                        tenant_id=tenant_id,
                        chunk_ids=list(replace_cleanup_chunk_ids),
                        exclude_event_ids=[ev.id for ev in new_events],
                        prune_orphan_entities=bool(getattr(config, "prune_orphan_entities", False)),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to cleanup previous KG events for chunks: %s", str(exc)[:200])

            return self._finalize_extract_result(
                session=session,
                state=state,
                progress=progress,
                new_events=new_events,
                alias_diag=alias_diag,
                alias_stats_by_doc=alias_stats_by_doc,
                entity_evidence_stats=entity_evidence_stats,
                relation_evidence_stats=relation_evidence_stats,
                skill_evidence_stats=skill_evidence_stats,
                entity_total=entity_total,
                t0=t0,
                evidence_required=evidence_required,
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _chunk_id_to_document_id(chunks: Sequence[DocumentChunk]) -> dict[object, object]:
        mapping: dict[object, object] = {}
        for chunk in chunks:
            if getattr(chunk, "id", None) and getattr(chunk, "document_id", None):
                mapping[chunk.id] = chunk.document_id
        return mapping

    @staticmethod
    def _count_events_by_document(
        doc_ids: set[object],
        chunk_id_to_doc_id: dict[object, object],
        kept_events: Sequence[KgSourceEvent],
    ) -> dict[object, int]:
        counts: dict[object, int] = dict.fromkeys(doc_ids, 0)
        for ev in kept_events:
            chunk_id = getattr(ev, "chunk_id", None)
            doc_id = chunk_id_to_doc_id.get(chunk_id) if chunk_id is not None else getattr(ev, "document_id", None)
            if doc_id in counts:
                counts[doc_id] += 1
        return counts

    @staticmethod
    def _count_chunks_by_document(
        doc_ids: set[object],
        chunk_id_to_doc_id: dict[object, object],
        chunk_ids: set[object],
    ) -> dict[object, int]:
        counts: dict[object, int] = dict.fromkeys(doc_ids, 0)
        for chunk_id in chunk_ids:
            doc_id = chunk_id_to_doc_id.get(chunk_id)
            if doc_id in counts:
                counts[doc_id] += 1
        return counts

    @staticmethod
    def _apply_budget_metadata(meta: dict[str, object], budget_stats: dict[str, int | str]) -> None:
        if not budget_stats:
            return
        meta["kg_chunk_budget"] = {
            "strategy": str(budget_stats.get("strategy") or ""),
            "total": int(budget_stats.get("total") or 0),
            "kept": int(budget_stats.get("kept") or 0),
            "skipped": int(budget_stats.get("skipped") or 0),
        }

    @staticmethod
    def _apply_alias_metadata(meta: dict[str, object], alias_stats: dict[str, int]) -> None:
        for key, value in alias_stats.items():
            if not key:
                continue
            try:
                meta[str(key)] = int(value or 0)
            except Exception:
                logger.debug("Skipping item after non-critical exception", exc_info=True)

    def _document_metadata_counts(
        self,
        *,
        chunks: Sequence[DocumentChunk],
        kept_events: Sequence[KgSourceEvent],
        skipped_chunk_ids: set[object],
        budget_skipped_chunk_ids: set[object],
        skipped_short_chunk_ids: set[object],
        failed_chunk_ids: set[object],
        retry_chunk_ids: set[object],
    ) -> tuple[set[object], dict[object, object], dict[str, dict[object, int]]]:
        chunk_id_to_doc_id = self._chunk_id_to_document_id(chunks)
        doc_ids = {doc_id for doc_id in chunk_id_to_doc_id.values() if doc_id}
        counts = {
            "events": self._count_events_by_document(doc_ids, chunk_id_to_doc_id, kept_events),
            "skipped": self._count_chunks_by_document(doc_ids, chunk_id_to_doc_id, skipped_chunk_ids),
            "budget_skipped": self._count_chunks_by_document(doc_ids, chunk_id_to_doc_id, budget_skipped_chunk_ids),
            "short_skipped": self._count_chunks_by_document(doc_ids, chunk_id_to_doc_id, skipped_short_chunk_ids),
            "failed": self._count_chunks_by_document(doc_ids, chunk_id_to_doc_id, failed_chunk_ids),
            "retry": self._count_chunks_by_document(doc_ids, chunk_id_to_doc_id, retry_chunk_ids),
        }
        return doc_ids, chunk_id_to_doc_id, counts

    @staticmethod
    def _build_relation_verify_candidates(
        relations: list[dict[str, object]],
    ) -> tuple[list[RelationCandidate], dict[str, dict[str, object]]]:
        candidates: list[RelationCandidate] = []
        by_rid: dict[str, dict[str, object]] = {}
        for index, relation in enumerate(relations, start=1):
            if not isinstance(relation, dict):
                continue
            relation_id = f"R{index}"
            by_rid[relation_id] = relation
            candidates.append(
                RelationCandidate(
                    rid=relation_id,
                    subject_id=str(relation.get("subject_id") or "").strip(),
                    predicate=str(relation.get("predicate") or "").strip() or "unknown",
                    object_id=str(relation.get("object_id") or "").strip(),
                    confidence=float(relation.get("confidence") or 0.5),
                    evidence_quote=str(relation.get("evidence_quote") or "").strip() or None,
                )
            )
        return candidates, by_rid

    @staticmethod
    def _merge_verified_relations(
        kept: list[dict[str, object]],
        *,
        by_rid: dict[str, dict[str, object]],
        max_relations_per_chunk: int,
    ) -> list[dict[str, object]]:
        verified: list[dict[str, object]] = []
        for item in kept:
            if not isinstance(item, dict):
                continue
            relation_id = str(item.get("rid") or "").strip()
            source = by_rid.get(relation_id)
            if not relation_id or source is None:
                continue
            merged = dict(source)
            if item.get("predicate"):
                merged["predicate"] = item.get("predicate")
            if item.get("confidence") is not None:
                merged["confidence"] = item.get("confidence")
            if item.get("evidence_quote"):
                merged["evidence_quote"] = item.get("evidence_quote")
            verified.append(merged)
            if len(verified) >= max_relations_per_chunk:
                break
        return verified

    async def _verify_relations_for_chunk(
        self,
        *,
        chunk_id: object,
        chunk_by_id: dict[object, DocumentChunk],
        rels_by_chunk: dict[object, list[dict[str, object]]],
        verifier: RelationVerifier,
        sem: asyncio.Semaphore,
        chunk_timeout_sec: float,
        max_relations_per_chunk: int,
    ) -> tuple[object, list[dict[str, object]] | None, bool]:
        chunk = chunk_by_id.get(chunk_id)
        if chunk is None:
            return chunk_id, None, False

        relations = rels_by_chunk.get(chunk_id) or []
        if not relations:
            return chunk_id, [], True

        relation_candidates, by_rid = self._build_relation_verify_candidates(relations)
        if not relation_candidates:
            return chunk_id, [], True

        try:
            async with sem:
                verify_coro = verifier.verify(
                    text=(chunk.content or ""),
                    candidates=relation_candidates,
                    max_keep=max_relations_per_chunk,
                )
                if chunk_timeout_sec > 0:
                    verify_output = await asyncio.wait_for(verify_coro, timeout=chunk_timeout_sec)
                else:
                    verify_output = await verify_coro
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "KG relation verify failed for chunk %s: %s",
                str(getattr(chunk, "id", "") or ""),
                str(exc)[:200],
            )
            return chunk_id, None, False

        kept = verify_output.get("kept") if isinstance(verify_output, dict) else None
        if not isinstance(kept, list) or not kept:
            return chunk_id, None, True
        return (
            chunk_id,
            self._merge_verified_relations(
                kept,
                by_rid=by_rid,
                max_relations_per_chunk=max_relations_per_chunk,
            ),
            True,
        )

    @staticmethod
    def _build_chunk_sections(
        target: DocumentChunk,
        *,
        chunks_to_process: list[DocumentChunk],
        chunk_id_to_pos: dict[object, int],
        context_window: int,
    ) -> list[DocumentChunk]:
        if context_window <= 0:
            return [target]
        position = chunk_id_to_pos.get(target.id)
        if position is None:
            return [target]

        sections: list[DocumentChunk] = [target]
        for step in range(1, context_window + 1):
            if position - step >= 0:
                sections.append(chunks_to_process[position - step])
            if position + step < len(chunks_to_process):
                sections.append(chunks_to_process[position + step])
        return sections

    @staticmethod
    def _chunk_has_asset(chunk: DocumentChunk) -> bool:
        meta = getattr(chunk, "doc_metadata", None)
        meta_dict = meta if isinstance(meta, dict) else {}
        doc_type = str(meta_dict.get("doc_type_kwd") or "").lower()
        if doc_type in {"image", "table"}:
            return True
        if meta_dict.get("image") is not None:
            return True
        return bool(
            meta_dict.get("img_id")
            or meta_dict.get("image_id")
            or meta_dict.get("image_url")
            or meta_dict.get("image_path")
        )

    @staticmethod
    async def _run_chunk_extract_call(
        *,
        processor: object,
        sections: list[DocumentChunk],
        sem: asyncio.Semaphore,
        batch_index: int,
        max_events_per_chunk: int,
        max_entities_per_event: int,
        chunk_timeout_sec: float,
    ) -> object:
        async with sem:
            coro = processor.extract_from_sections(
                sections,
                batch_index=batch_index,
                max_events=max_events_per_chunk,
                max_entities_per_event=max_entities_per_event,
            )
            if chunk_timeout_sec > 0:
                return await asyncio.wait_for(coro, timeout=chunk_timeout_sec)
            return await coro

    @staticmethod
    def _record_chunk_retry_success(progress: _ExtractProgress, *, chunk_id: object, attempt: int) -> None:
        if attempt <= 0:
            return
        progress.retry_chunk_ids.add(chunk_id)
        progress.retry_attempts_total += int(attempt)

    @staticmethod
    def _record_chunk_failure(
        progress: _ExtractProgress,
        *,
        chunk: DocumentChunk,
        attempt: int,
        last_exc: Exception | None,
    ) -> None:
        if attempt > 0:
            progress.retry_chunk_ids.add(chunk.id)
            progress.retry_attempts_total += int(attempt)
        progress.failed_chunks += 1
        progress.failed_chunk_ids.add(chunk.id)
        progress.failure_messages.append(str(last_exc)[:300] if last_exc else "unknown_error")
        logger.warning(
            "KG extract failed for chunk %s after %s attempts: %s",
            getattr(chunk, "id", ""),
            attempt + 1,
            str(last_exc)[:200] if last_exc else "unknown_error",
        )

    async def _extract_chunk_with_retries(
        self,
        *,
        chunk: DocumentChunk,
        batch_index: int,
        processor: object,
        sem: asyncio.Semaphore,
        chunks_to_process: list[DocumentChunk],
        chunk_id_to_pos: dict[object, int],
        chunk_len_by_id: dict[object, int],
        context_window: int,
        min_chars: int,
        max_events_per_chunk: int,
        max_entities_per_event: int,
        chunk_timeout_sec: float,
        chunk_max_retries: int,
        retry_backoff_sec: float,
        progress: _ExtractProgress,
    ) -> tuple[DocumentChunk, list[dict]]:
        text = (chunk.content or "").strip()
        if not text:
            progress.succeeded_chunk_ids.add(chunk.id)
            return chunk, []

        content_len = int(chunk_len_by_id.get(chunk.id, len(text)))
        if min_chars > 0 and content_len < int(min_chars) and not self._chunk_has_asset(chunk):
            progress.skipped_short_chunk_ids.add(chunk.id)
            progress.succeeded_chunk_ids.add(chunk.id)
            return chunk, []

        attempt = 0
        last_exc: Exception | None = None
        sections = self._build_chunk_sections(
            chunk,
            chunks_to_process=chunks_to_process,
            chunk_id_to_pos=chunk_id_to_pos,
            context_window=context_window,
        )
        while True:
            try:
                progress.llm_called_chunk_ids.add(chunk.id)
                data = await self._run_chunk_extract_call(
                    processor=processor,
                    sections=sections,
                    sem=sem,
                    batch_index=batch_index,
                    max_events_per_chunk=max_events_per_chunk,
                    max_entities_per_event=max_entities_per_event,
                    chunk_timeout_sec=chunk_timeout_sec,
                )
                progress.succeeded_chunk_ids.add(chunk.id)
                self._record_chunk_retry_success(progress, chunk_id=chunk.id, attempt=attempt)
                return chunk, data if isinstance(data, list) else []
            except asyncio.TimeoutError as exc:
                progress.timed_out_chunks += 1
                progress.timeout_chunk_ids.add(chunk.id)
                last_exc = exc
            except Exception as exc:  # noqa: BLE001
                last_exc = exc

            if attempt >= int(chunk_max_retries):
                self._record_chunk_failure(
                    progress,
                    chunk=chunk,
                    attempt=attempt,
                    last_exc=last_exc,
                )
                return chunk, []

            attempt += 1
            if retry_backoff_sec > 0:
                await asyncio.sleep(float(retry_backoff_sec) * (2 ** (attempt - 1)))

    async def _extract_chunk_groups(
        self,
        *,
        chunks_to_process: list[DocumentChunk],
        processor: object,
        sem: asyncio.Semaphore,
        chunk_id_to_pos: dict[object, int],
        chunk_len_by_id: dict[object, int],
        context_window: int,
        min_chars: int,
        max_concurrency: int,
        max_events_per_chunk: int,
        max_entities_per_event: int,
        chunk_timeout_sec: float,
        chunk_max_retries: int,
        retry_backoff_sec: float,
        progress: _ExtractProgress,
    ) -> list[tuple[DocumentChunk, list[dict]]]:
        extracted: list[tuple[DocumentChunk, list[dict]]] = []
        group_size = max(1, max_concurrency * 4)
        for offset in range(0, len(chunks_to_process), group_size):
            group = chunks_to_process[offset : offset + group_size]
            results = await asyncio.gather(
                *[
                    self._extract_chunk_with_retries(
                        chunk=chunk,
                        batch_index=offset + index + 1,
                        processor=processor,
                        sem=sem,
                        chunks_to_process=chunks_to_process,
                        chunk_id_to_pos=chunk_id_to_pos,
                        chunk_len_by_id=chunk_len_by_id,
                        context_window=context_window,
                        min_chars=min_chars,
                        max_events_per_chunk=max_events_per_chunk,
                        max_entities_per_event=max_entities_per_event,
                        chunk_timeout_sec=chunk_timeout_sec,
                        chunk_max_retries=chunk_max_retries,
                        retry_backoff_sec=retry_backoff_sec,
                        progress=progress,
                    )
                    for index, chunk in enumerate(group)
                ]
            )
            extracted.extend(results)
        return extracted

    @staticmethod
    def _new_alias_diag() -> dict[str, object]:
        return {
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

    @staticmethod
    def _alias_bump(
        alias_stats_by_doc: dict[object, dict[str, int]],
        doc_id: object | None,
        key: str,
        n: int = 1,
    ) -> None:
        if not doc_id or not key:
            return
        current = alias_stats_by_doc.setdefault(doc_id, {})
        current[key] = int(current.get(key, 0) or 0) + int(n)

    @staticmethod
    def _load_resolved_chunks(
        session,
        config: ExtractConfig,
        chunks: Sequence[DocumentChunk] | None,
    ) -> list[DocumentChunk]:
        if chunks is None:
            return (
                session.query(DocumentChunk)
                .filter(DocumentChunk.id.in_(config.chunk_ids))
                .order_by(DocumentChunk.chunk_index)
                .all()
            )
        resolved_chunks = list(chunks)
        resolved_chunks.sort(key=lambda chunk: chunk.chunk_index)
        return resolved_chunks

    @staticmethod
    def _prepare_chunk_budget(
        resolved_chunks: list[DocumentChunk],
    ) -> tuple[int, str, list[DocumentChunk], dict[object, dict[str, int | str]], set[object]]:
        max_chunks_per_document = max(0, int(getattr(settings, "KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT", 0) or 0))
        chunk_budget_strategy = (
            str(getattr(settings, "KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT_STRATEGY", "uniform") or "uniform")
            .strip()
            .lower()
            or "uniform"
        )
        if max_chunks_per_document <= 0:
            return max_chunks_per_document, chunk_budget_strategy, resolved_chunks, {}, set()

        budgeted_chunks, budget_stats_by_doc = _apply_document_chunk_budget(
            resolved_chunks,
            max_chunks_per_document=max_chunks_per_document,
            strategy=chunk_budget_strategy,
        )
        kept_budget_ids = {getattr(chunk, "id", None) for chunk in budgeted_chunks}
        budget_skipped_chunk_ids = {
            getattr(chunk, "id", None) for chunk in resolved_chunks if getattr(chunk, "id", None) not in kept_budget_ids
        }
        return (
            max_chunks_per_document,
            chunk_budget_strategy,
            budgeted_chunks,
            budget_stats_by_doc,
            budget_skipped_chunk_ids,
        )

    def _plugin_writeback(
        self,
        *,
        session,
        tenant_id: object,
        resolved_chunks: list[DocumentChunk],
        kept_events: Sequence[KgSourceEvent],
        budget_skipped_chunk_ids: set[object],
        budget_stats_by_doc: dict[object, dict[str, int | str]],
    ) -> None:
        self._writeback_document_metadata(
            session=session,
            tenant_id=tenant_id,
            chunks=resolved_chunks,
            kept_events=kept_events,
            skipped_chunk_ids=set(),
            budget_skipped_chunk_ids=budget_skipped_chunk_ids,
            skipped_short_chunk_ids=set(),
            failed_chunk_ids=set(),
            retry_chunk_ids=set(),
            budget_stats_by_doc=budget_stats_by_doc,
            alias_stats_by_doc={},
        )

    def _cleanup_plugin_extract(
        self,
        *,
        session,
        config: ExtractConfig,
        tenant_id: object,
        chunk_ids_for_replace: list[object],
    ) -> None:
        if not bool(getattr(config, "replace_existing", False)) or not chunk_ids_for_replace:
            return
        try:
            RelationRepository(session).delete_relations_for_chunks(
                chunk_ids_for_replace,
                tenant_id=tenant_id,
                commit=False,
            )
            Indexer(session).delete_event_indexes_for_chunks(
                tenant_id=tenant_id,
                chunk_ids=chunk_ids_for_replace,
                commit=False,
                exclude_event_ids=[],
                prune_orphan_entities=bool(getattr(config, "prune_orphan_entities", False)),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to cleanup previous plugin KG events for chunks: %s", str(exc)[:200])

    def _plugin_metrics_payload(
        self,
        *,
        resolved_chunks: list[DocumentChunk],
        budgeted_chunks: list[DocumentChunk],
        budget_skipped_chunk_ids: set[object],
        chunk_budget_strategy: str,
        max_chunks_per_document: int,
        kg_plugin_ref: str,
        elapsed: float,
        event_total: int,
        entity_total: int | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "event": "kg.extract",
            "backend": "python_plugin",
            "kg_python_plugin": kg_plugin_ref,
            "chunk_count": len(resolved_chunks),
            "chunk_processed": int(len(budgeted_chunks)),
            "chunk_budget_skipped": int(len(budget_skipped_chunk_ids)),
            "chunk_budget_strategy": chunk_budget_strategy,
            "chunk_budget_max_per_document": int(max_chunks_per_document),
            "event_new": int(event_total),
            "event_total": int(event_total),
            "elapsed_sec": round(float(elapsed), 3),
        }
        if entity_total is not None:
            payload["entity_total"] = int(entity_total)
        return payload

    def _maybe_run_python_plugin(
        self,
        *,
        session,
        config: ExtractConfig,
        index_options: IndexingOptions | None,
        tenant_id: object,
        resolved_chunks: list[DocumentChunk],
        budgeted_chunks: list[DocumentChunk],
        budget_skipped_chunk_ids: set[object],
        budget_stats_by_doc: dict[object, dict[str, int | str]],
        max_chunks_per_document: int,
        chunk_budget_strategy: str,
        t0: float,
    ) -> list[KgSourceEvent] | None:
        kg_plugin_ref = str(getattr(config, "kg_python_plugin", "") or "").strip()
        if not kg_plugin_ref:
            return None

        plugin_docs = [_document_from_chunk(chunk) for chunk in budgeted_chunks]
        events_to_index = apply_kg_python_plugin(
            plugin_docs,
            plugin_ref=kg_plugin_ref,
            params=dict(getattr(config, "kg_python_params", None) or {}),
            context={"tenant_id": str(tenant_id)},
        )
        chunk_ids_for_replace = [chunk.id for chunk in resolved_chunks if getattr(chunk, "id", None) is not None]
        self._cleanup_plugin_extract(
            session=session,
            config=config,
            tenant_id=tenant_id,
            chunk_ids_for_replace=chunk_ids_for_replace,
        )
        if not events_to_index:
            if bool(getattr(config, "replace_existing", False)) and chunk_ids_for_replace:
                session.commit()
            elapsed = time.perf_counter() - t0
            log_metrics(
                self._plugin_metrics_payload(
                    resolved_chunks=resolved_chunks,
                    budgeted_chunks=budgeted_chunks,
                    budget_skipped_chunk_ids=budget_skipped_chunk_ids,
                    chunk_budget_strategy=chunk_budget_strategy,
                    max_chunks_per_document=max_chunks_per_document,
                    kg_plugin_ref=kg_plugin_ref,
                    elapsed=elapsed,
                    event_total=0,
                )
            )
            self._plugin_writeback(
                session=session,
                tenant_id=tenant_id,
                resolved_chunks=resolved_chunks,
                kept_events=[],
                budget_skipped_chunk_ids=budget_skipped_chunk_ids,
                budget_stats_by_doc=budget_stats_by_doc,
            )
            return []

        result = (
            Indexer(session)
            .upsert(
                tenant_id=tenant_id,
                records=events_to_index,
                options=index_options,
            )
            .event_result
        )
        events = result.events if result else []
        entity_total = len(result.entities) if result else 0
        elapsed = time.perf_counter() - t0
        log_metrics(
            self._plugin_metrics_payload(
                resolved_chunks=resolved_chunks,
                budgeted_chunks=budgeted_chunks,
                budget_skipped_chunk_ids=budget_skipped_chunk_ids,
                chunk_budget_strategy=chunk_budget_strategy,
                max_chunks_per_document=max_chunks_per_document,
                kg_plugin_ref=kg_plugin_ref,
                elapsed=elapsed,
                event_total=len(events),
                entity_total=entity_total,
            )
        )
        self._plugin_writeback(
            session=session,
            tenant_id=tenant_id,
            resolved_chunks=resolved_chunks,
            kept_events=events,
            budget_skipped_chunk_ids=budget_skipped_chunk_ids,
            budget_stats_by_doc=budget_stats_by_doc,
        )
        return events

    @staticmethod
    def _resolve_prompt_template_content(
        session,
        tenant_id: object,
        config: ExtractConfig,
    ) -> tuple[str | None, str | None]:
        if not (config.prompt_template_id or config.prompt_template_key or config.prompt_ab_experiment_key):
            return None, None

        chosen = resolve_prompt_template(
            db=session,
            tenant_id=tenant_id,
            prompt_template_id=config.prompt_template_id,
            template_key=config.prompt_template_key,
            ab_experiment_key=config.prompt_ab_experiment_key,
            ab_user_key=config.ab_user_key,
        )
        if not (chosen and chosen.content):
            return None, None

        prompt_template_content = str(chosen.content).strip() or None
        chosen_template_id = str(chosen.id)
        try:
            chosen.usage_count += 1
            session.commit()
        except Exception:
            session.rollback()
            logger.warning("Failed to update kg extract prompt usage_count for template %s", chosen_template_id)
        return prompt_template_content, chosen_template_id

    async def _resolve_backend_runtime(
        self,
        *,
        config: ExtractConfig,
        resolved_chunks: list[DocumentChunk],
        prompt_template_content: str | None,
    ) -> tuple[SimpleNamespace, object | None]:
        requested_backend = str(getattr(config, "extraction_backend", "") or "").strip().lower() or None
        auto_backend_reason: str | None = None
        if requested_backend is None:
            long_doc_backend = str(getattr(settings, "KG_EXTRACT_LONG_DOC_BACKEND", "") or "").strip().lower() or None
            long_doc_min_chunks = max(0, int(getattr(settings, "KG_EXTRACT_LONG_DOC_MIN_CHUNKS", 0) or 0))
            if long_doc_backend and long_doc_min_chunks > 0 and len(resolved_chunks) >= long_doc_min_chunks:
                requested_backend = long_doc_backend
                auto_backend_reason = f"long_doc_chunk_threshold:{len(resolved_chunks)}"

        if requested_backend == "heuristic":
            return (
                SimpleNamespace(
                    backend="heuristic",
                    processor=HeuristicExtractor(),
                    fallback_reason=auto_backend_reason,
                ),
                None,
            )

        llm_client = await create_llm_client(scenario="extract", model_config=self.model_config)
        llm_processor = EventProcessor(llm_client=llm_client, prompt_template=prompt_template_content)
        backend_selection = resolve_extraction_backend(
            llm_processor=llm_processor,
            requested_backend=requested_backend,
        )
        if auto_backend_reason and not getattr(backend_selection, "fallback_reason", None):
            backend_selection.fallback_reason = auto_backend_reason
        return backend_selection, llm_client

    async def _build_extract_state(
        self,
        *,
        session,
        config: ExtractConfig,
        resolved_chunks: list[DocumentChunk],
        budgeted_chunks: list[DocumentChunk],
        max_chunks_per_document: int,
        chunk_budget_strategy: str,
        budget_stats_by_doc: dict[object, dict[str, int | str]],
        budget_skipped_chunk_ids: set[object],
    ) -> tuple[_ExtractState, object | None]:
        tenant_id = config.tenant_id or resolved_chunks[0].tenant_id
        prompt_template_content, chosen_template_id = self._resolve_prompt_template_content(session, tenant_id, config)
        backend_selection, llm_client = await self._resolve_backend_runtime(
            config=config,
            resolved_chunks=resolved_chunks,
            prompt_template_content=prompt_template_content,
        )
        max_concurrency = max(
            1,
            int(getattr(settings, "KG_EXTRACT_MAX_CONCURRENCY", 0) or 0)
            or int(getattr(config, "max_concurrency", 3) or 3),
        )
        chunk_timeout_sec = float(getattr(settings, "KG_EXTRACT_CHUNK_TIMEOUT_SEC", 0) or 0)
        chunk_timeout_sec = max(0.0, chunk_timeout_sec)
        retry_backoff_sec = float(getattr(settings, "KG_EXTRACT_CHUNK_RETRY_BACKOFF_SEC", 0.5) or 0.5)
        retry_backoff_sec = max(0.0, retry_backoff_sec)
        extract_relations_enabled = (
            bool(getattr(settings, "KG_RELATION_ENABLED", False))
            if config.extract_relations is None
            else bool(config.extract_relations)
        )
        extract_skills_enabled = (
            bool(getattr(settings, "KG_SKILL_ENABLED", False))
            if config.extract_skills is None
            else bool(config.extract_skills)
        )
        state = _ExtractState(
            tenant_id=tenant_id,
            resolved_chunks=resolved_chunks,
            budgeted_chunks=budgeted_chunks,
            max_chunks_per_document=max_chunks_per_document,
            chunk_budget_strategy=chunk_budget_strategy,
            budget_stats_by_doc=budget_stats_by_doc,
            budget_skipped_chunk_ids=budget_skipped_chunk_ids,
            processor=backend_selection.processor,
            embedder=DocumentProcessor(),
            backend_selection=backend_selection,
            backend_reason=getattr(backend_selection, "fallback_reason", None),
            prompt_template_content=prompt_template_content,
            chosen_template_id=chosen_template_id,
            max_concurrency=max_concurrency,
            max_events_per_chunk=max(1, int(getattr(settings, "KG_EXTRACT_MAX_EVENTS_PER_CHUNK", 6) or 6)),
            max_entities_per_event=max(1, int(getattr(settings, "KG_EXTRACT_MAX_ENTITIES_PER_EVENT", 30) or 30)),
            embed_batch_size=max(1, int(getattr(settings, "KG_EXTRACT_EMBED_BATCH_SIZE", 128) or 128)),
            chunk_timeout_sec=chunk_timeout_sec,
            context_window=max(0, min(int(getattr(settings, "KG_EXTRACT_CONTEXT_WINDOW_CHUNKS", 0) or 0), 20)),
            min_chars=max(0, int(getattr(settings, "KG_EXTRACT_MIN_CHARS", 0) or 0)),
            chunk_max_retries=max(0, int(getattr(settings, "KG_EXTRACT_CHUNK_MAX_RETRIES", 0) or 0)),
            retry_backoff_sec=retry_backoff_sec,
            replace_existing=bool(getattr(config, "replace_existing", False)),
            skip_unchanged=bool(getattr(settings, "KG_EXTRACT_SKIP_UNCHANGED_CHUNKS", False))
            and bool(getattr(config, "replace_existing", False)),
            extract_relations_enabled=extract_relations_enabled,
            extract_skills_enabled=extract_skills_enabled,
            prompt_selector_expected={
                "kg_prompt_template_id": _normalize_prompt_selector_value(chosen_template_id),
                "kg_prompt_template_key": _normalize_prompt_selector_value(config.prompt_template_key),
                "kg_prompt_ab_experiment_key": _normalize_prompt_selector_value(config.prompt_ab_experiment_key),
            },
            sem=asyncio.Semaphore(max_concurrency),
        )
        return state, llm_client

    @staticmethod
    def _populate_chunk_content_maps(state: _ExtractState) -> None:
        for chunk in state.resolved_chunks:
            meta = getattr(chunk, "doc_metadata", None)
            meta_dict = meta if isinstance(meta, dict) else {}
            raw_hash = meta_dict.get("content_hash")
            content_hash = raw_hash.strip() if isinstance(raw_hash, str) and raw_hash.strip() else ""
            raw_len = meta_dict.get("content_len")
            try:
                content_len = int(raw_len) if raw_len is not None else None
            except Exception:
                content_len = None

            computed_digest = ""
            computed_len = 0
            if not content_hash or content_len is None:
                computed_digest, computed_len = _compute_content_stats(getattr(chunk, "content", "") or "")
            if not content_hash:
                content_hash = computed_digest
            if content_len is None:
                content_len = computed_len

            state.chunk_hash_by_id[chunk.id] = content_hash
            state.chunk_len_by_id[chunk.id] = max(0, int(content_len))

            raw_key = meta_dict.get("chunk_key")
            chunk_key = raw_key.strip() if isinstance(raw_key, str) and raw_key.strip() else ""
            if not chunk_key:
                chunk_key = str(getattr(chunk, "chunk_index", "") or "")
            state.chunk_key_by_id[chunk.id] = chunk_key

    @staticmethod
    def _load_skip_unchanged_events(session, state: _ExtractState, progress: _ExtractProgress) -> None:
        if not state.skip_unchanged:
            state.chunks_to_process = list(state.budgeted_chunks)
            state.chunk_id_to_pos = {chunk.id: index for index, chunk in enumerate(state.chunks_to_process)}
            return

        existing = (
            session.query(KgSourceEvent)
            .filter(
                KgSourceEvent.tenant_id == state.tenant_id,
                KgSourceEvent.chunk_id.in_([chunk.id for chunk in state.resolved_chunks]),
            )
            .all()
        )
        for event in existing:
            if not getattr(event, "chunk_id", None):
                continue
            state.existing_events_by_chunk.setdefault(event.chunk_id, []).append(event)

        for chunk in state.budgeted_chunks:
            prior = state.existing_events_by_chunk.get(chunk.id) or []
            current_hash = state.chunk_hash_by_id.get(chunk.id) or ""
            if not prior or not current_hash:
                continue
            if _is_chunk_unchanged(
                prior,
                content_hash=current_hash,
                prompt_selector_expected=state.prompt_selector_expected,
            ):
                progress.skipped_chunk_ids.add(chunk.id)
                state.kept_events.extend(prior)

        state.chunks_to_process = [
            chunk for chunk in state.budgeted_chunks if chunk.id not in progress.skipped_chunk_ids
        ]
        state.chunk_id_to_pos = {chunk.id: index for index, chunk in enumerate(state.chunks_to_process)}

    async def _initialize_extract_context(
        self,
        *,
        session,
        config: ExtractConfig,
        chunks: Sequence[DocumentChunk] | None,
        index_options: IndexingOptions | None,
        t0: float,
    ) -> (
        tuple[_ExtractState, _ExtractProgress, dict[str, object], dict[object, dict[str, int]], object | None]
        | list[KgSourceEvent]
    ):
        alias_diag = self._new_alias_diag()
        alias_stats_by_doc: dict[object, dict[str, int]] = {}
        resolved_chunks = self._load_resolved_chunks(session, config, chunks)
        if not resolved_chunks:
            logger.warning("No chunks found for extraction")
            return []

        (
            max_chunks_per_document,
            chunk_budget_strategy,
            budgeted_chunks,
            budget_stats_by_doc,
            budget_skipped_chunk_ids,
        ) = self._prepare_chunk_budget(resolved_chunks)
        tenant_id = config.tenant_id or resolved_chunks[0].tenant_id
        plugin_result = self._maybe_run_python_plugin(
            session=session,
            config=config,
            index_options=index_options,
            tenant_id=tenant_id,
            resolved_chunks=resolved_chunks,
            budgeted_chunks=budgeted_chunks,
            budget_skipped_chunk_ids=budget_skipped_chunk_ids,
            budget_stats_by_doc=budget_stats_by_doc,
            max_chunks_per_document=max_chunks_per_document,
            chunk_budget_strategy=chunk_budget_strategy,
            t0=t0,
        )
        if plugin_result is not None:
            return plugin_result

        state, llm_client = await self._build_extract_state(
            session=session,
            config=config,
            resolved_chunks=resolved_chunks,
            budgeted_chunks=budgeted_chunks,
            max_chunks_per_document=max_chunks_per_document,
            chunk_budget_strategy=chunk_budget_strategy,
            budget_stats_by_doc=budget_stats_by_doc,
            budget_skipped_chunk_ids=budget_skipped_chunk_ids,
        )
        progress = _ExtractProgress()
        self._populate_chunk_content_maps(state)
        self._load_skip_unchanged_events(session, state, progress)
        _release_idle_transaction(session)
        return state, progress, alias_diag, alias_stats_by_doc, llm_client

    @staticmethod
    def _normalize_event_payload(
        *,
        chunk: DocumentChunk,
        event_data: dict,
        max_entities_per_event: int,
        parser: EntityValueParser,
    ) -> tuple[tuple[str, str], dict[str, object]]:
        title = (event_data.get("title") or "").strip()
        summary = (event_data.get("summary") or "").strip()
        content = (event_data.get("content") or "").strip()
        if not title:
            title = (summary[:50] if summary else (chunk.content or "")[:50]).strip() or "Event"
        if not content:
            content = (summary or chunk.content or "Event").strip()
        if not summary:
            summary = (content[:200] if content else "Event").strip() or "Event"

        entities = event_data.get("entities") if isinstance(event_data.get("entities"), list) else []
        entities = [entity for entity in entities if isinstance(entity, dict)]
        if len(entities) > max_entities_per_event:
            entities = entities[:max_entities_per_event]
        entities = _canonicalize_entities_for_chunk(
            entities,
            chunk_text=(chunk.content or ""),
            max_entities=max_entities_per_event,
            parser=parser,
        )
        payload = {
            "title": title,
            "summary": summary,
            "content": content,
            "entities": entities,
        }
        return (title.casefold(), summary.casefold()), payload

    @staticmethod
    def _build_processed_events(
        extracted: list[tuple[DocumentChunk, list[dict]]],
        *,
        max_events_per_chunk: int,
        max_entities_per_event: int,
    ) -> list[tuple[DocumentChunk, dict]]:
        processed_events: list[tuple[DocumentChunk, dict]] = []
        entity_parser = EntityValueParser()
        for chunk, events_data in extracted:
            if not events_data:
                continue

            seen_keys: set[tuple[str, str]] = set()
            kept = 0
            for event_data in events_data:
                if not isinstance(event_data, dict):
                    continue
                if kept >= max_events_per_chunk:
                    break

                key, payload = EventExtractor._normalize_event_payload(
                    chunk=chunk,
                    event_data=event_data,
                    max_entities_per_event=max_entities_per_event,
                    parser=entity_parser,
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                processed_events.append((chunk, payload))
                kept += 1
        return processed_events

    @staticmethod
    def _build_entity_candidates(
        processed_events: list[tuple[DocumentChunk, dict]],
        *,
        parser: EntityValueParser,
    ) -> dict[object, list[EntityCandidate]]:
        candidates_by_chunk: dict[object, list[EntityCandidate]] = {}
        cid_by_key_by_chunk: dict[object, dict[tuple[str, str], str]] = {}
        for chunk, event_payload in processed_events:
            ent_list = event_payload.get("entities") if isinstance(event_payload, dict) else None
            if not isinstance(ent_list, list) or not ent_list:
                continue
            cid_by_key = cid_by_key_by_chunk.setdefault(chunk.id, {})
            candidate_list = candidates_by_chunk.setdefault(chunk.id, [])
            for ent in ent_list:
                if not isinstance(ent, dict):
                    continue
                name = str(ent.get("name") or "").strip()
                if not name:
                    continue
                normalized = str(ent.get("normalized_name") or "").strip()
                if not normalized:
                    normalized = parser.normalize_name(name)
                    ent["normalized_name"] = normalized
                ent_type = str(ent.get("type") or "unknown").strip() or "unknown"
                key = (ent_type, normalized)
                cid = cid_by_key.get(key)
                if cid is None:
                    cid = f"E{len(cid_by_key) + 1}"
                    cid_by_key[key] = cid
                    candidate_list.append(
                        EntityCandidate(
                            cid=cid,
                            name=name,
                            type=ent_type,
                            description=str(ent.get("description") or "").strip(),
                            evidence_quote=str(ent.get("evidence_quote") or "").strip() or None,
                        )
                    )
                ent["_cid"] = cid
        return candidates_by_chunk

    async def _verify_entities_for_chunk(
        self,
        *,
        chunk_id: object,
        chunk_by_id: dict[object, DocumentChunk],
        verifier: EntityVerifier,
        candidates_by_chunk: dict[object, list[EntityCandidate]],
        state: _ExtractState,
    ) -> tuple[object, dict[str, object], bool]:
        chunk = chunk_by_id.get(chunk_id)
        if chunk is None:
            return chunk_id, {"kept": [], "aliases": []}, False
        candidates = candidates_by_chunk.get(chunk_id) or []
        if not candidates:
            return chunk_id, {"kept": [], "aliases": []}, True
        try:
            async with state.sem:
                verify_coro = verifier.verify(
                    text=(chunk.content or ""),
                    candidates=candidates,
                    max_keep=max(5, int(state.max_entities_per_event or 0)),
                    max_alias_edges=10,
                )
                if state.chunk_timeout_sec > 0:
                    verify_output = await asyncio.wait_for(verify_coro, timeout=state.chunk_timeout_sec)
                else:
                    verify_output = await verify_coro
            if isinstance(verify_output, dict):
                return chunk_id, verify_output, True
            return chunk_id, {"kept": [], "aliases": []}, True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "KG entity verify failed for chunk %s: %s",
                str(getattr(chunk, "id", "") or ""),
                str(exc)[:200],
            )
            return chunk_id, {"kept": [], "aliases": []}, False

    @staticmethod
    def _build_keep_map(verify_output: dict[str, object]) -> dict[str, dict[str, object]]:
        kept = verify_output.get("kept") if isinstance(verify_output, dict) else None
        if not isinstance(kept, list) or not kept:
            return {}
        keep_map: dict[str, dict[str, object]] = {}
        for item in kept:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id") or "").strip()
            if cid:
                keep_map[cid] = dict(item)
        return keep_map

    @staticmethod
    def _clean_llm_aliases(verify_output: dict[str, object]) -> list[dict[str, object]]:
        aliases = verify_output.get("aliases") if isinstance(verify_output, dict) else None
        if not isinstance(aliases, list) or not aliases:
            return []
        cleaned: list[dict[str, object]] = []
        for item in aliases:
            if not isinstance(item, dict):
                continue
            alias_id = str(item.get("alias_id") or "").strip()
            canonical_id = str(item.get("canonical_id") or "").strip()
            if not alias_id or not canonical_id or alias_id == canonical_id:
                continue
            cleaned.append(dict(item))
        return cleaned

    @staticmethod
    def _apply_keep_map_to_entity(ent: dict, keep_map: dict[str, dict[str, object]]) -> dict | None:
        cid = str(ent.get("_cid") or "").strip()
        if not cid or cid not in keep_map:
            return None
        info = keep_map.get(cid) or {}
        if info.get("type"):
            ent["type"] = info.get("type")
        if info.get("description"):
            ent["description"] = info.get("description")
        if info.get("evidence_quote"):
            ent["evidence_quote"] = info.get("evidence_quote")
        if info.get("confidence") is not None:
            ent["_confidence"] = info.get("confidence")
        return ent

    @staticmethod
    def _apply_keep_map_to_events(
        processed_events: list[tuple[DocumentChunk, dict]],
        keep_map_by_chunk: dict[object, dict[str, dict[str, object]]],
    ) -> None:
        for chunk, event_payload in processed_events:
            keep_map = keep_map_by_chunk.get(chunk.id)
            if not keep_map:
                continue
            ent_list = event_payload.get("entities") if isinstance(event_payload, dict) else None
            if not isinstance(ent_list, list) or not ent_list:
                continue
            kept_entities: list[dict] = []
            for ent in ent_list:
                if not isinstance(ent, dict):
                    continue
                kept_ent = EventExtractor._apply_keep_map_to_entity(ent, keep_map)
                if kept_ent is not None:
                    kept_entities.append(kept_ent)
            event_payload["entities"] = kept_entities

    async def _run_entity_verification(
        self,
        *,
        state: _ExtractState,
        processed_events: list[tuple[DocumentChunk, dict]],
        llm_client: object | None,
        candidates_by_chunk: dict[object, list[EntityCandidate]],
    ) -> dict[object, list[dict[str, object]]]:
        if not candidates_by_chunk or llm_client is None:
            return {}
        verifier = EntityVerifier(llm_client=llm_client)
        chunk_by_id = {chunk.id: chunk for chunk in state.resolved_chunks if getattr(chunk, "id", None) is not None}
        verify_results = await asyncio.gather(
            *[
                self._verify_entities_for_chunk(
                    chunk_id=chunk_id,
                    chunk_by_id=chunk_by_id,
                    verifier=verifier,
                    candidates_by_chunk=candidates_by_chunk,
                    state=state,
                )
                for chunk_id in candidates_by_chunk.keys()
            ]
        )
        keep_map_by_chunk: dict[object, dict[str, dict[str, object]]] = {}
        llm_aliases_by_chunk: dict[object, list[dict[str, object]]] = {}
        for chunk_id, verify_output, ok in verify_results:
            if not ok:
                continue
            keep_map = self._build_keep_map(verify_output)
            if keep_map:
                keep_map_by_chunk[chunk_id] = keep_map
            aliases = self._clean_llm_aliases(verify_output)
            if aliases:
                llm_aliases_by_chunk[chunk_id] = aliases
        self._apply_keep_map_to_events(processed_events, keep_map_by_chunk)
        return llm_aliases_by_chunk

    @staticmethod
    def _normalize_entity_for_evidence(ent: dict, *, parser: EntityValueParser) -> tuple[str, str] | None:
        name = str(ent.get("name") or "").strip()
        if not name:
            return None
        normalized = str(ent.get("normalized_name") or "").strip()
        if not normalized:
            normalized = parser.normalize_name(name)
            ent["normalized_name"] = normalized
        return name, normalized

    @staticmethod
    def _entity_noise_bucket(name: str, normalized: str) -> str | None:
        if normalized in _ENTITY_EVIDENCE_STOP_NORMS:
            return "dropped_stopword"
        if normalized.isascii() and len(normalized) < 2:
            return "dropped_noise_short"
        if normalized.isdigit():
            return "dropped_noise_digits"
        if not any(ch.isalnum() for ch in name):
            return "dropped_noise_punct"
        return None

    @staticmethod
    def _apply_entity_evidence(
        ent: dict,
        *,
        chunk: DocumentChunk,
        name: str,
        evidence_required: bool,
    ):
        evidence_quote = ent.get("evidence_quote")
        evidence = coerce_evidence(
            text=(chunk.content or ""),
            evidence_quote=(str(evidence_quote).strip() if isinstance(evidence_quote, str) else None),
            fallback_mention=name,
            max_quote_chars=240,
        )
        if evidence is None:
            return None if evidence_required else ent
        ent["evidence_quote"] = evidence.quote
        ent["evidence_start_char"] = int(evidence.start_char)
        ent["evidence_end_char"] = int(evidence.end_char)
        ent["evidence_source"] = str(getattr(evidence, "source", "") or "").strip() or "quote"
        return ent

    @staticmethod
    def _apply_entity_evidence_gates(
        processed_events: list[tuple[DocumentChunk, dict]],
        *,
        parser: EntityValueParser,
        evidence_required: bool,
    ) -> dict[str, int]:
        stats: dict[str, int] = {
            "total_raw": 0,
            "kept": 0,
            "dropped_stopword": 0,
            "dropped_noise_short": 0,
            "dropped_noise_digits": 0,
            "dropped_noise_punct": 0,
            "dropped_no_evidence": 0,
        }
        for chunk, event_payload in processed_events:
            ent_list = event_payload.get("entities") if isinstance(event_payload, dict) else None
            if not isinstance(ent_list, list) or not ent_list:
                continue
            cleaned: list[dict] = []
            for ent in ent_list:
                if not isinstance(ent, dict):
                    continue
                normalized_entity = EventExtractor._normalize_entity_for_evidence(ent, parser=parser)
                if normalized_entity is None:
                    continue
                name, normalized = normalized_entity
                stats["total_raw"] += 1
                noise_bucket = EventExtractor._entity_noise_bucket(name, normalized)
                if noise_bucket is not None:
                    stats[noise_bucket] += 1
                    continue
                kept_ent = EventExtractor._apply_entity_evidence(
                    ent,
                    chunk=chunk,
                    name=name,
                    evidence_required=evidence_required,
                )
                if kept_ent is None:
                    stats["dropped_no_evidence"] += 1
                    continue
                cleaned.append(kept_ent)
                stats["kept"] += 1
            event_payload["entities"] = cleaned
        return stats

    @staticmethod
    def _add_text_for_embedding(text: str, *, seen_text: set[str], to_embed: list[str]) -> None:
        if not text or text in seen_text:
            return
        seen_text.add(text)
        to_embed.append(text)

    @staticmethod
    def _collect_chunk_embed_texts(
        chunk: DocumentChunk,
        event_payload: dict,
        *,
        seen_text: set[str],
        to_embed: list[str],
    ) -> None:
        event_text = (
            event_payload.get("content") or event_payload.get("summary") or event_payload.get("title") or ""
        ).strip()
        if not event_text:
            event_text = (chunk.content or "")[:200].strip() or "Event"
        event_payload["_embed_text"] = event_text
        EventExtractor._add_text_for_embedding(event_text, seen_text=seen_text, to_embed=to_embed)
        for ent in event_payload.get("entities") or []:
            name = (ent.get("name") or "").strip()
            description = (ent.get("description") or "").strip()
            ent_text = (f"{name} {description}").strip() if description else name
            ent["_embed_text"] = ent_text
            EventExtractor._add_text_for_embedding(ent_text, seen_text=seen_text, to_embed=to_embed)

    @staticmethod
    async def _build_embedding_cache(
        state: _ExtractState,
        processed_events: list[tuple[DocumentChunk, dict]],
    ) -> dict[str, list[float]]:
        embed_cache: dict[str, list[float]] = {}
        to_embed: list[str] = []
        seen_text: set[str] = set()
        for chunk, event_payload in processed_events:
            EventExtractor._collect_chunk_embed_texts(
                chunk,
                event_payload,
                seen_text=seen_text,
                to_embed=to_embed,
            )
        if not to_embed:
            return embed_cache
        try:
            for offset in range(0, len(to_embed), state.embed_batch_size):
                batch = to_embed[offset : offset + state.embed_batch_size]
                vectors = await state.embedder.generate_batch(batch)
                for text, vector in zip(batch, vectors, strict=False):
                    if vector:
                        embed_cache[text] = vector
        except Exception as exc:  # noqa: BLE001
            logger.warning("KG embedding batch failed; proceeding without vectors: %s", str(exc)[:200])
            return {}
        return embed_cache

    @staticmethod
    def _build_event_index_records(
        *,
        state: _ExtractState,
        config: ExtractConfig,
        processed_events: list[tuple[DocumentChunk, dict]],
        embed_cache: dict[str, list[float]],
    ) -> tuple[list[IndexRecord], int]:
        events_to_index: list[IndexRecord] = []
        entity_total = 0
        for chunk, event_payload in processed_events:
            vector = embed_cache.get(str(event_payload.get("_embed_text") or ""))
            entity_inputs: list[EventEntityInput] = []
            for ent in event_payload.get("entities") or []:
                name = (ent.get("name") or "").strip()
                if not name:
                    continue
                normalized = (ent.get("normalized_name") or name).strip()
                ent_type = (ent.get("type") or "unknown").strip() or "unknown"
                ent_text = str(ent.get("_embed_text") or name)
                entity_inputs.append(
                    EventEntityInput(
                        name=name,
                        normalized_name=normalized,
                        type=ent_type,
                        description=(ent.get("description") or "").strip() or None,
                        vector=embed_cache.get(ent_text),
                        role=ent.get("role"),
                        evidence_quote=(str(ent.get("evidence_quote") or "").strip() or None),
                        evidence_source=(str(ent.get("evidence_source") or "").strip() or None),
                        evidence_start_char=(
                            int(ent.get("evidence_start_char")) if ent.get("evidence_start_char") is not None else None
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
            refs["chunk_key"] = state.chunk_key_by_id.get(chunk.id) or str(chunk.chunk_index)
            refs["content_hash"] = state.chunk_hash_by_id.get(chunk.id) or ""
            refs["content_len"] = int(state.chunk_len_by_id.get(chunk.id, 0) or 0)
            events_to_index.append(
                IndexRecord(
                    kind=IndexKind.EVENT,
                    title=str(event_payload.get("title") or "").strip() or "Event",
                    summary=str(event_payload.get("summary") or "").strip() or "Event",
                    content=str(event_payload.get("content") or "").strip() or "Event",
                    document_id=chunk.document_id,
                    chunk_id=chunk.id,
                    references=refs,
                    vector=vector,
                    entities=entity_inputs,
                    extra_data={
                        "kg_prompt_template_id": state.chosen_template_id,
                        "kg_prompt_template_key": config.prompt_template_key,
                        "kg_prompt_ab_experiment_key": config.prompt_ab_experiment_key,
                    },
                )
            )
        return events_to_index, entity_total

    async def _prepare_event_bundle(
        self,
        *,
        state: _ExtractState,
        config: ExtractConfig,
        processed_events: list[tuple[DocumentChunk, dict]],
        llm_client: object | None,
    ) -> _PreparedEventBundle:
        entity_parser = EntityValueParser()
        entity_verify_enabled = bool(getattr(settings, "KG_EXTRACT_ENTITY_VERIFY_ENABLED", False))
        relation_verify_enabled = bool(getattr(settings, "KG_EXTRACT_RELATION_VERIFY_ENABLED", False))
        evidence_required = bool(getattr(settings, "KG_EXTRACT_EVIDENCE_REQUIRED", False)) or bool(
            entity_verify_enabled or relation_verify_enabled
        )
        candidates_by_chunk = self._build_entity_candidates(processed_events, parser=entity_parser)
        llm_aliases_by_chunk: dict[object, list[dict[str, object]]] = {}
        if entity_verify_enabled and candidates_by_chunk:
            try:
                llm_aliases_by_chunk = await self._run_entity_verification(
                    state=state,
                    processed_events=processed_events,
                    llm_client=llm_client,
                    candidates_by_chunk=candidates_by_chunk,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("KG entity verify pass failed; continuing without verification: %s", str(exc)[:200])
        entity_evidence_stats = self._apply_entity_evidence_gates(
            processed_events,
            parser=entity_parser,
            evidence_required=evidence_required,
        )
        embed_cache = await self._build_embedding_cache(state, processed_events)
        events_to_index, entity_total = self._build_event_index_records(
            state=state,
            config=config,
            processed_events=processed_events,
            embed_cache=embed_cache,
        )

        return _PreparedEventBundle(
            processed_events=processed_events,
            events_to_index=events_to_index,
            entity_total=entity_total,
            entity_evidence_stats=entity_evidence_stats,
            relation_verify_enabled=relation_verify_enabled,
            evidence_required=evidence_required,
            llm_aliases_by_chunk=llm_aliases_by_chunk,
        )

    @staticmethod
    def _collect_kept_events_on_failure(
        session,
        *,
        tenant_id: object,
        existing_events_by_chunk: dict[object, list[KgSourceEvent]],
        failed_chunk_ids: set[object],
    ) -> list[KgSourceEvent]:
        if not failed_chunk_ids:
            return []
        if existing_events_by_chunk:
            kept_events: list[KgSourceEvent] = []
            for chunk_id in failed_chunk_ids:
                kept_events.extend(existing_events_by_chunk.get(chunk_id) or [])
            return kept_events

        existing = (
            session.query(KgSourceEvent)
            .filter(
                KgSourceEvent.tenant_id == tenant_id,
                KgSourceEvent.chunk_id.in_(list(failed_chunk_ids)),
            )
            .all()
        )
        return [event for event in existing if getattr(event, "chunk_id", None) in failed_chunk_ids]

    @staticmethod
    def _replace_cleanup_chunk_ids(
        *,
        processed_cleanup_chunk_ids: list[object],
        budget_skipped_chunk_ids: set[object],
        replace_existing: bool,
    ) -> list[object]:
        suffix = list(budget_skipped_chunk_ids) if replace_existing else []
        return list(dict.fromkeys(list(processed_cleanup_chunk_ids) + suffix))

    @staticmethod
    def _extract_metrics_payload(
        *,
        resolved_chunks: list[DocumentChunk],
        chunks_to_process: list[DocumentChunk],
        progress: _ExtractProgress,
        budget_skipped_chunk_ids: set[object],
        backend_selection: SimpleNamespace,
        backend_reason: str | None,
        chunk_budget_strategy: str,
        max_chunks_per_document: int,
        event_new: int,
        event_kept: int,
        event_total: int,
        alias_diag: dict[str, object],
        entity_evidence_stats: dict[str, int],
        elapsed: float,
        entity_count_new: int | None = None,
        relation_evidence_stats: dict[str, int] | None = None,
        skill_evidence_stats: dict[str, int] | None = None,
        evidence_required: bool | None = None,
        max_concurrency: int | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "event": "kg.extract",
            "chunk_count": len(resolved_chunks),
            "chunk_processed": int(len(chunks_to_process)),
            "chunk_skipped": int(len(progress.skipped_chunk_ids)),
            "chunk_budget_skipped": int(len(budget_skipped_chunk_ids)),
            "chunk_skipped_short": int(len(progress.skipped_short_chunk_ids)),
            "chunk_failed": int(progress.failed_chunks),
            "chunk_timeout": int(len(progress.timeout_chunk_ids)),
            "timeout_errors": int(progress.timed_out_chunks),
            "retry_chunks": int(len(progress.retry_chunk_ids)),
            "retry_attempts": int(progress.retry_attempts_total),
            "llm_called_chunks": int(len(progress.llm_called_chunk_ids)),
            "backend": str(getattr(backend_selection, "backend", "") or ""),
            "backend_reason": str(backend_reason or ""),
            "chunk_budget_strategy": chunk_budget_strategy,
            "chunk_budget_max_per_document": int(max_chunks_per_document),
            "event_new": int(event_new),
            "event_kept": int(event_kept),
            "event_total": int(event_total),
            "alias_heuristics": dict(alias_diag),
            "entity_evidence": dict(entity_evidence_stats),
            "elapsed_sec": round(float(elapsed), 3),
        }
        if evidence_required is not None:
            payload["evidence_required"] = bool(evidence_required)
        if entity_count_new is not None:
            payload["entity_count_new"] = int(entity_count_new)
        if relation_evidence_stats is not None:
            payload["relation_evidence"] = dict(relation_evidence_stats)
        if skill_evidence_stats is not None:
            payload["skill_evidence"] = dict(skill_evidence_stats)
        if max_concurrency is not None:
            payload["max_concurrency"] = int(max_concurrency)
        return payload

    def _handle_empty_extract_result(
        self,
        *,
        session,
        config: ExtractConfig,
        state: _ExtractState,
        progress: _ExtractProgress,
        processed_events: list[tuple[DocumentChunk, dict]],
        alias_diag: dict[str, object],
        alias_stats_by_doc: dict[object, dict[str, int]],
        entity_evidence_stats: dict[str, int],
        extract_relations_enabled: bool,
        t0: float,
        evidence_required: bool,
        backend_selection: SimpleNamespace,
        backend_reason: str | None,
    ) -> list[KgSourceEvent]:
        if (
            progress.failed_chunks > 0
            and not processed_events
            and progress.llm_called_chunk_ids
            and len(progress.failed_chunk_ids) >= len(progress.llm_called_chunk_ids)
            and not progress.timeout_chunk_ids
        ):
            unique_errors = list(dict.fromkeys(msg for msg in progress.failure_messages if msg))
            detail = "; ".join(unique_errors)[:500] if unique_errors else "unknown_error"
            raise RuntimeError(f"KG extraction failed for all attempted chunks ({progress.failed_chunks}); {detail}")

        kept_on_failure = (
            self._collect_kept_events_on_failure(
                session,
                tenant_id=state.tenant_id,
                existing_events_by_chunk=state.existing_events_by_chunk,
                failed_chunk_ids=progress.failed_chunk_ids,
            )
            if state.replace_existing
            else []
        )
        processed_cleanup_chunk_ids = [
            chunk_id for chunk_id in progress.succeeded_chunk_ids if chunk_id not in progress.skipped_chunk_ids
        ]
        replace_cleanup_chunk_ids = self._replace_cleanup_chunk_ids(
            processed_cleanup_chunk_ids=processed_cleanup_chunk_ids,
            budget_skipped_chunk_ids=state.budget_skipped_chunk_ids,
            replace_existing=state.replace_existing,
        )
        if state.replace_existing and replace_cleanup_chunk_ids:
            try:
                if extract_relations_enabled:
                    RelationRepository(session).delete_relations_for_chunks(
                        replace_cleanup_chunk_ids,
                        tenant_id=state.tenant_id,
                        commit=False,
                    )
                Indexer(session).delete_event_indexes_for_chunks(
                    tenant_id=state.tenant_id,
                    chunk_ids=list(replace_cleanup_chunk_ids),
                    exclude_event_ids=[],
                    prune_orphan_entities=bool(getattr(config, "prune_orphan_entities", False)),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to cleanup previous KG events for chunks: %s", str(exc)[:200])

        events = list(state.kept_events) + list(kept_on_failure)
        elapsed = time.perf_counter() - t0
        log_metrics(
            self._extract_metrics_payload(
                resolved_chunks=state.resolved_chunks,
                chunks_to_process=state.chunks_to_process,
                progress=progress,
                budget_skipped_chunk_ids=state.budget_skipped_chunk_ids,
                backend_selection=backend_selection,
                backend_reason=backend_reason,
                chunk_budget_strategy=state.chunk_budget_strategy,
                max_chunks_per_document=state.max_chunks_per_document,
                event_new=0,
                event_kept=len(events),
                event_total=len(events),
                alias_diag=alias_diag,
                entity_evidence_stats=entity_evidence_stats,
                elapsed=elapsed,
                evidence_required=evidence_required,
            )
        )
        self._writeback_document_metadata(
            session=session,
            tenant_id=state.tenant_id,
            chunks=state.resolved_chunks,
            kept_events=events,
            skipped_chunk_ids=progress.skipped_chunk_ids,
            budget_skipped_chunk_ids=state.budget_skipped_chunk_ids,
            skipped_short_chunk_ids=progress.skipped_short_chunk_ids,
            failed_chunk_ids=progress.failed_chunk_ids,
            retry_chunk_ids=progress.retry_chunk_ids,
            budget_stats_by_doc=state.budget_stats_by_doc,
            alias_stats_by_doc=alias_stats_by_doc,
        )
        return events

    def _finalize_extract_result(
        self,
        *,
        session,
        state: _ExtractState,
        progress: _ExtractProgress,
        new_events: Sequence[KgSourceEvent],
        alias_diag: dict[str, object],
        alias_stats_by_doc: dict[object, dict[str, int]],
        entity_evidence_stats: dict[str, int],
        relation_evidence_stats: dict[str, int],
        skill_evidence_stats: dict[str, int],
        entity_total: int,
        t0: float,
        evidence_required: bool,
    ) -> list[KgSourceEvent]:
        kept_on_failure = (
            self._collect_kept_events_on_failure(
                session,
                tenant_id=state.tenant_id,
                existing_events_by_chunk=state.existing_events_by_chunk,
                failed_chunk_ids=progress.failed_chunk_ids,
            )
            if state.replace_existing
            else []
        )
        events = list(state.kept_events) + list(kept_on_failure) + list(new_events)
        elapsed = time.perf_counter() - t0
        log_metrics(
            self._extract_metrics_payload(
                resolved_chunks=state.resolved_chunks,
                chunks_to_process=state.chunks_to_process,
                progress=progress,
                budget_skipped_chunk_ids=state.budget_skipped_chunk_ids,
                backend_selection=state.backend_selection,
                backend_reason=state.backend_reason,
                chunk_budget_strategy=state.chunk_budget_strategy,
                max_chunks_per_document=state.max_chunks_per_document,
                event_new=len(new_events),
                event_kept=len(state.kept_events) + len(kept_on_failure),
                event_total=len(events),
                alias_diag=alias_diag,
                entity_evidence_stats=entity_evidence_stats,
                elapsed=elapsed,
                evidence_required=evidence_required,
                entity_count_new=entity_total,
                relation_evidence_stats=relation_evidence_stats,
                skill_evidence_stats=skill_evidence_stats,
                max_concurrency=state.max_concurrency,
            )
        )
        self._writeback_document_metadata(
            session=session,
            tenant_id=state.tenant_id,
            chunks=state.resolved_chunks,
            kept_events=events,
            skipped_chunk_ids=progress.skipped_chunk_ids,
            budget_skipped_chunk_ids=state.budget_skipped_chunk_ids,
            skipped_short_chunk_ids=progress.skipped_short_chunk_ids,
            failed_chunk_ids=progress.failed_chunk_ids,
            retry_chunk_ids=progress.retry_chunk_ids,
            budget_stats_by_doc=state.budget_stats_by_doc,
            alias_stats_by_doc=alias_stats_by_doc,
        )
        return events

    @staticmethod
    def _build_relation_candidates(
        processed_events: list[tuple[DocumentChunk, dict]],
        *,
        cleanup_chunk_ids: list[object],
    ) -> dict[object, list[CandidateEntity]]:
        candidate_rows_by_chunk: dict[object, list[tuple[str, str, str, str]]] = {}
        seen_by_chunk: dict[object, set[tuple[str, str]]] = {}
        for chunk, event_payload in processed_events:
            if chunk.id not in cleanup_chunk_ids:
                continue
            entities = event_payload.get("entities") if isinstance(event_payload, dict) else None
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
                cid = str(ent.get("_cid") or "").strip() or f"E{len(seen)}"
                rows.append((cid, name, ent_type, normalized))

        candidates_by_chunk: dict[object, list[CandidateEntity]] = {}
        for chunk_id in cleanup_chunk_ids:
            rows = candidate_rows_by_chunk.get(chunk_id) or []
            candidates_by_chunk[chunk_id] = [
                CandidateEntity(cid=cid, name=name, type=ent_type, normalized_name=normalized)
                for (cid, name, ent_type, normalized) in rows
            ]
        return candidates_by_chunk

    @staticmethod
    def _build_relation_entity_lookup(result) -> dict[tuple[str, str], object]:
        entity_id_by_key: dict[tuple[str, str], object] = {}
        for ent in list(result.entities) if result else []:
            normalized = str(getattr(ent, "normalized_name", "") or "").strip()
            ent_type = str(getattr(ent, "type", "") or "unknown").strip() or "unknown"
            ent_id = getattr(ent, "id", None)
            if normalized and ent_id is not None:
                entity_id_by_key[(ent_type, normalized)] = ent_id
        return entity_id_by_key

    def _build_relation_pass_data(self, context: _RelationPostIndexContext) -> _RelationPassData:
        return _RelationPassData(
            candidates_by_chunk=self._build_relation_candidates(
                context.processed_events,
                cleanup_chunk_ids=context.cleanup_chunk_ids,
            ),
            entity_id_by_key=self._build_relation_entity_lookup(context.result),
            chunk_by_id={
                chunk.id: chunk for chunk in context.state.resolved_chunks if getattr(chunk, "id", None) is not None
            },
        )

    @staticmethod
    def _relation_alias_confidence() -> float:
        alias_conf_raw = getattr(settings, "KG_RELATION_ALIAS_CONFIDENCE", 0.95)
        try:
            alias_conf = float(alias_conf_raw) if alias_conf_raw is not None else 0.95
        except Exception:
            alias_conf = 0.95
        return max(0.0, min(alias_conf, 1.0))

    @staticmethod
    def _record_alias_candidate_methods(
        alias_diag: dict[str, object],
        alias_stats_by_doc: dict[object, dict[str, int]],
        *,
        chunk: DocumentChunk,
        alias_candidates: list[object],
    ) -> None:
        alias_diag["chunks_considered"] = int(alias_diag.get("chunks_considered", 0) or 0) + 1
        alias_diag["candidates_total"] = int(alias_diag.get("candidates_total", 0) or 0) + int(len(alias_candidates))
        for cand in alias_candidates:
            method = str(getattr(cand, "method", "") or "").strip() or "unknown"
            by_method = alias_diag.get("candidates_by_method")
            if isinstance(by_method, dict):
                by_method[method] = int(by_method.get(method, 0) or 0) + 1
            EventExtractor._alias_bump(
                alias_stats_by_doc,
                chunk.document_id,
                f"kg_alias_candidates_{method}",
                1,
            )
        EventExtractor._alias_bump(
            alias_stats_by_doc,
            chunk.document_id,
            "kg_alias_candidates_total",
            len(alias_candidates),
        )

    @staticmethod
    def _relation_candidate_norm_map(
        candidates: list[CandidateEntity],
        *,
        parser: EntityValueParser,
    ) -> dict[str, tuple[str, str]]:
        by_norm: dict[str, tuple[str, str]] = {}
        for candidate in candidates:
            normalized = str(getattr(candidate, "normalized_name", "") or "").strip() or parser.normalize_name(
                str(getattr(candidate, "name", "") or "")
            )
            ent_type = str(getattr(candidate, "type", "") or "unknown").strip() or "unknown"
            name = str(getattr(candidate, "name", "") or "").strip()
            if normalized and name:
                by_norm.setdefault(normalized, (ent_type, name))
        return by_norm

    @staticmethod
    def _resolve_canonical_anchor(
        canonical_norm_raw: str,
        canonical_surface: str,
        cand_by_norm: dict[str, tuple[str, str]],
    ) -> tuple[str, str, str]:
        canonical_norm = canonical_norm_raw
        canonical_surface_resolved = canonical_surface
        anchored = "exact" if canonical_norm in cand_by_norm else ""
        if canonical_norm not in cand_by_norm:
            match = best_suffix_match(canonical_norm, list(cand_by_norm.keys()), min_chars=2)
            if match and match in cand_by_norm:
                canonical_norm = match
                canonical_surface_resolved = cand_by_norm[match][1]
                anchored = "suffix"
        return canonical_norm, canonical_surface_resolved, anchored

    @staticmethod
    def _record_anchor_result(
        alias_diag: dict[str, object],
        alias_stats_by_doc: dict[object, dict[str, int]],
        *,
        chunk: DocumentChunk,
        canonical_norm: str,
        cand_by_norm: dict[str, tuple[str, str]],
        anchored: str,
    ) -> bool:
        if canonical_norm not in cand_by_norm:
            alias_diag["canonical_anchor_failed"] = int(alias_diag.get("canonical_anchor_failed", 0) or 0) + 1
            EventExtractor._alias_bump(alias_stats_by_doc, chunk.document_id, "kg_alias_anchor_failed", 1)
            return False
        if anchored == "exact":
            alias_diag["canonical_anchor_exact"] = int(alias_diag.get("canonical_anchor_exact", 0) or 0) + 1
            EventExtractor._alias_bump(alias_stats_by_doc, chunk.document_id, "kg_alias_anchor_exact", 1)
        elif anchored == "suffix":
            alias_diag["canonical_anchor_suffix"] = int(alias_diag.get("canonical_anchor_suffix", 0) or 0) + 1
            EventExtractor._alias_bump(alias_stats_by_doc, chunk.document_id, "kg_alias_anchor_suffix", 1)
        return True

    @staticmethod
    def _record_missing_alias_entities(
        *,
        inferred_type: str,
        canonical_norm: str,
        canonical_surface_resolved: str,
        alias_norm: str,
        alias_surface_resolved: str,
        cand_by_norm: dict[str, tuple[str, str]],
        entity_id_by_key: dict[tuple[str, str], object],
        missing_entities: dict[tuple[str, str], str],
    ) -> bool:
        if (inferred_type, canonical_norm) not in entity_id_by_key:
            missing_entities[(inferred_type, canonical_norm)] = canonical_surface_resolved
        if (inferred_type, alias_norm) in entity_id_by_key:
            return True
        if alias_norm in cand_by_norm or is_abbrev_token(alias_surface_resolved):
            missing_entities[(inferred_type, alias_norm)] = alias_surface_resolved
            return True
        return False

    def _build_alias_spec(
        self,
        *,
        context: _RelationPostIndexContext,
        chunk: DocumentChunk,
        cand: object,
        cand_by_norm: dict[str, tuple[str, str]],
        entity_id_by_key: dict[tuple[str, str], object],
        alias_parser: EntityValueParser,
        missing_entities: dict[tuple[str, str], str],
    ) -> tuple[str, str, str, str, str] | None:
        direction = choose_alias_direction(cand.a, cand.b)
        if not direction:
            context.alias_diag["direction_skipped"] = int(context.alias_diag.get("direction_skipped", 0) or 0) + 1
            self._alias_bump(context.alias_stats_by_doc, chunk.document_id, "kg_alias_direction_skipped", 1)
            return None
        context.alias_diag["direction_ok"] = int(context.alias_diag.get("direction_ok", 0) or 0) + 1
        self._alias_bump(context.alias_stats_by_doc, chunk.document_id, "kg_alias_direction_ok", 1)
        alias_surface, canonical_surface = direction
        alias_norm_raw = alias_parser.normalize_name(alias_surface)
        canonical_norm_raw = alias_parser.normalize_name(canonical_surface)
        if not alias_norm_raw or not canonical_norm_raw or alias_norm_raw == canonical_norm_raw:
            return None
        canonical_norm, canonical_surface_resolved, anchored = self._resolve_canonical_anchor(
            canonical_norm_raw,
            canonical_surface,
            cand_by_norm,
        )
        if not self._record_anchor_result(
            context.alias_diag,
            context.alias_stats_by_doc,
            chunk=chunk,
            canonical_norm=canonical_norm,
            cand_by_norm=cand_by_norm,
            anchored=anchored,
        ):
            return None
        inferred_type = cand_by_norm[canonical_norm][0]
        alias_norm = alias_norm_raw
        alias_surface_resolved = cand_by_norm.get(alias_norm, ("", alias_surface))[1] or alias_surface
        if not self._record_missing_alias_entities(
            inferred_type=inferred_type,
            canonical_norm=canonical_norm,
            canonical_surface_resolved=canonical_surface_resolved,
            alias_norm=alias_norm,
            alias_surface_resolved=alias_surface_resolved,
            cand_by_norm=cand_by_norm,
            entity_id_by_key=entity_id_by_key,
            missing_entities=missing_entities,
        ):
            context.alias_diag["alias_skipped_non_abbrev"] = (
                int(context.alias_diag.get("alias_skipped_non_abbrev", 0) or 0) + 1
            )
            self._alias_bump(context.alias_stats_by_doc, chunk.document_id, "kg_alias_skipped_non_abbrev", 1)
            return None
        return (
            inferred_type,
            alias_norm,
            canonical_norm,
            str(cand.method or ""),
            str(getattr(cand, "quote", "") or "").strip(),
        )

    def _build_alias_specs_for_chunk(
        self,
        *,
        context: _RelationPostIndexContext,
        chunk: DocumentChunk,
        candidates: list[CandidateEntity],
        cand_by_norm: dict[str, tuple[str, str]],
        alias_candidates: list[object],
        entity_id_by_key: dict[tuple[str, str], object],
        alias_parser: EntityValueParser,
        missing_entities: dict[tuple[str, str], str],
    ) -> list[tuple[str, str, str, str, str]]:
        self._record_alias_candidate_methods(
            context.alias_diag,
            context.alias_stats_by_doc,
            chunk=chunk,
            alias_candidates=alias_candidates,
        )
        specs: list[tuple[str, str, str, str, str]] = []
        for cand in alias_candidates:
            spec = self._build_alias_spec(
                context=context,
                chunk=chunk,
                cand=cand,
                cand_by_norm=cand_by_norm,
                entity_id_by_key=entity_id_by_key,
                alias_parser=alias_parser,
                missing_entities=missing_entities,
            )
            if spec is not None:
                specs.append(spec)
        return specs

    def _record_alias_specs(
        self,
        context: _RelationPostIndexContext,
        *,
        chunk: DocumentChunk,
        chunk_id: object,
        specs: list[tuple[str, str, str, str, str]],
        data: _RelationPassData,
    ) -> None:
        if not specs:
            return
        data.alias_specs_by_chunk[chunk_id] = specs
        context.alias_diag["edges_planned"] = int(context.alias_diag.get("edges_planned", 0) or 0) + int(len(specs))
        self._alias_bump(context.alias_stats_by_doc, chunk.document_id, "kg_alias_edges_planned", len(specs))

    @staticmethod
    def _alias_upsert_payload(
        missing_entities: dict[tuple[str, str], str],
        vectors: list[list[float]],
    ) -> list[dict]:
        payload: list[dict] = []
        for (ent_type, normalized), surface, vector in zip(
            list(missing_entities.keys()),
            list(missing_entities.values()),
            vectors,
            strict=False,
        ):
            payload.append(
                {
                    "name": surface,
                    "normalized_name": normalized,
                    "type": ent_type,
                    "description": None,
                    "vector": list(vector) if isinstance(vector, list) and vector else None,
                    "extra_data": {"source": "alias_heuristic"},
                }
            )
        return payload

    def _merge_upserted_alias_entities(
        self,
        context: _RelationPostIndexContext,
        data: _RelationPassData,
        upserted: object,
    ) -> None:
        context.alias_diag["entities_upserted"] = int(len(upserted or []))
        for ent in upserted or []:
            normalized = str(getattr(ent, "normalized_name", "") or "").strip()
            ent_type = str(getattr(ent, "type", "") or "unknown").strip() or "unknown"
            ent_id = getattr(ent, "id", None)
            if normalized and ent_id is not None:
                data.entity_id_by_key[(ent_type, normalized)] = ent_id

    async def _upsert_missing_alias_entities(
        self,
        context: _RelationPostIndexContext,
        data: _RelationPassData,
        missing_entities: dict[tuple[str, str], str],
    ) -> None:
        if not missing_entities:
            return
        context.alias_diag["entities_upsert_attempted"] = int(len(missing_entities))
        alias_texts = list(missing_entities.values())
        try:
            vectors = await context.state.embedder.generate_batch(alias_texts)
        except Exception as exc:  # noqa: BLE001
            logger.warning("KG alias embedding failed; proceeding without vectors: %s", str(exc)[:200])
            vectors = [[] for _ in alias_texts]
        try:
            upserted = context.indexer.upsert_entities(
                tenant_id=context.state.tenant_id,
                entities=self._alias_upsert_payload(missing_entities, vectors),
                options=context.index_options,
                commit=True,
            )
            self._merge_upserted_alias_entities(context, data, upserted)
        except Exception as exc:  # noqa: BLE001
            logger.warning("KG alias entity upsert failed; continuing: %s", str(exc)[:200])

    async def _prepare_relation_alias_data(
        self,
        context: _RelationPostIndexContext,
        data: _RelationPassData,
    ) -> None:
        alias_enabled = bool(getattr(settings, "KG_RELATION_ALIAS_HEURISTIC_ENABLED", True))
        alias_max_candidates = max(
            0,
            int(getattr(settings, "KG_RELATION_ALIAS_MAX_CANDIDATES_PER_CHUNK", 10) or 10),
        )
        if not alias_enabled or alias_max_candidates <= 0:
            return

        data.alias_conf = self._relation_alias_confidence()
        context.alias_diag["enabled"] = True
        missing_entities: dict[tuple[str, str], str] = {}
        alias_parser = EntityValueParser()
        for chunk_id in context.cleanup_chunk_ids:
            chunk = data.chunk_by_id.get(chunk_id)
            if chunk is None:
                continue
            candidates = data.candidates_by_chunk.get(chunk_id) or []
            if not candidates:
                continue
            cand_by_norm = self._relation_candidate_norm_map(candidates, parser=alias_parser)
            alias_candidates = extract_alias_candidates(
                text=(chunk.content or ""),
                max_candidates=alias_max_candidates,
            )
            if not alias_candidates:
                continue
            specs = self._build_alias_specs_for_chunk(
                context=context,
                chunk=chunk,
                candidates=candidates,
                cand_by_norm=cand_by_norm,
                alias_candidates=alias_candidates,
                entity_id_by_key=data.entity_id_by_key,
                alias_parser=alias_parser,
                missing_entities=missing_entities,
            )
            self._record_alias_specs(
                context,
                chunk=chunk,
                chunk_id=chunk_id,
                specs=specs,
                data=data,
            )

        await self._upsert_missing_alias_entities(context, data, missing_entities)

    async def _extract_relations_for_chunk(
        self,
        *,
        chunk_id: object,
        chunk_by_id: dict[object, DocumentChunk],
        candidates_by_chunk: dict[object, list[CandidateEntity]],
        relation_processor: RelationProcessor,
        max_relations_per_chunk: int,
        sem: asyncio.Semaphore,
        chunk_timeout_sec: float,
    ) -> tuple[object, list[dict[str, object]], bool]:
        chunk = chunk_by_id.get(chunk_id)
        if chunk is None:
            return chunk_id, [], False
        candidates = candidates_by_chunk.get(chunk_id) or []
        if len(candidates) < 2:
            return chunk_id, [], True
        try:
            async with sem:
                coro = relation_processor.extract_relations(
                    text=(chunk.content or ""),
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
                str(getattr(chunk, "id", "") or ""),
                str(exc)[:200],
            )
            return chunk_id, [], False

    async def _populate_relation_extraction_results(
        self,
        context: _RelationPostIndexContext,
        data: _RelationPassData,
    ) -> None:
        from app.rag.kg.ontology import resolve_allowed_predicates  # noqa: WPS433

        allowed_predicates: Sequence[str] = resolve_allowed_predicates(
            db=context.session,
            tenant_id=context.state.tenant_id,
            fallback_default=_DEFAULT_RELATION_PREDICATES,
            raw_override=str(getattr(settings, "KG_RELATION_ALLOWED_PREDICATES", "") or "").strip(),
        )
        max_relations_per_chunk = max(
            0,
            int(getattr(settings, "KG_RELATION_MAX_RELATIONS_PER_CHUNK", 20) or 20),
        )
        if max_relations_per_chunk <= 0:
            raise RuntimeError("KG_RELATION_MAX_RELATIONS_PER_CHUNK must be > 0 when relations are enabled")

        relation_processor = RelationProcessor(
            llm_client=context.llm_client,
            allowed_predicates=allowed_predicates,
        )
        data.rel_results = await asyncio.gather(
            *[
                self._extract_relations_for_chunk(
                    chunk_id=chunk_id,
                    chunk_by_id=data.chunk_by_id,
                    candidates_by_chunk=data.candidates_by_chunk,
                    relation_processor=relation_processor,
                    max_relations_per_chunk=max_relations_per_chunk,
                    sem=context.state.sem,
                    chunk_timeout_sec=context.state.chunk_timeout_sec,
                )
                for chunk_id in context.cleanup_chunk_ids
            ]
        )

        for chunk_id, rels, ok in data.rel_results:
            if ok and isinstance(rels, list) and rels:
                data.rels_by_chunk[chunk_id] = [rel for rel in rels if isinstance(rel, dict)]

        if not context.relation_verify_enabled or not data.rels_by_chunk:
            return
        try:
            verifier = RelationVerifier(llm_client=context.llm_client, allowed_predicates=allowed_predicates)
            verify_results = await asyncio.gather(
                *[
                    self._verify_relations_for_chunk(
                        chunk_id=chunk_id,
                        chunk_by_id=data.chunk_by_id,
                        rels_by_chunk=data.rels_by_chunk,
                        verifier=verifier,
                        sem=context.state.sem,
                        chunk_timeout_sec=context.state.chunk_timeout_sec,
                        max_relations_per_chunk=max_relations_per_chunk,
                    )
                    for chunk_id in data.rels_by_chunk.keys()
                ]
            )
            for chunk_id, verified, ok in verify_results:
                if ok and verified is not None:
                    data.rels_by_chunk[chunk_id] = verified
        except Exception as exc:  # noqa: BLE001
            logger.warning("KG relation verify pass failed; continuing without verification: %s", str(exc)[:200])

    @staticmethod
    def _relation_refs_for_chunk(
        chunk: DocumentChunk,
        *,
        chunk_key_by_id: dict[object, str],
        chunk_hash_by_id: dict[object, str],
        chunk_len_by_id: dict[object, int],
    ) -> tuple[dict[str, object], str | None]:
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
        pipeline_hash = str(refs.get("pipeline_hash") or "").strip() or None
        return refs, pipeline_hash

    @staticmethod
    def _build_relation_evidence(
        *,
        chunk: DocumentChunk,
        rel: dict[str, object],
        subj_cand: CandidateEntity,
        obj_cand: CandidateEntity,
        evidence_required: bool,
    ) -> tuple[object | None, bool]:
        evidence = coerce_evidence(
            text=(chunk.content or ""),
            evidence_quote=(
                str(rel.get("evidence_quote")).strip() if isinstance(rel.get("evidence_quote"), str) else None
            ),
            fallback_mention=None,
            max_quote_chars=240,
        )
        if evidence is None and evidence_required:
            return None, False
        if evidence is None:
            return None, True
        subj_ok = surface_mentioned(quote=evidence.quote, surface=str(subj_cand.name or "")) or surface_mentioned(
            quote=evidence.quote,
            surface=str(subj_cand.normalized_name or ""),
        )
        obj_ok = surface_mentioned(quote=evidence.quote, surface=str(obj_cand.name or "")) or surface_mentioned(
            quote=evidence.quote,
            surface=str(obj_cand.normalized_name or ""),
        )
        if evidence_required and not (subj_ok and obj_ok):
            return evidence, False
        return evidence, True

    def _append_relation_rows_for_chunk(
        self,
        *,
        context: _RelationPostIndexContext,
        data: _RelationPassData,
        chunk: DocumentChunk,
        rels: list[dict[str, object]],
        ok: bool,
        relation_evidence_stats: dict[str, int],
        rel_rows: list[KgRelation],
    ) -> None:
        refs, pipeline_hash = self._relation_refs_for_chunk(
            chunk,
            chunk_key_by_id=context.state.chunk_key_by_id,
            chunk_hash_by_id=context.state.chunk_hash_by_id,
            chunk_len_by_id=context.state.chunk_len_by_id,
        )
        seen_rel_keys = self._existing_alias_relation_keys(context, data, chunk, ok)
        self._append_extracted_relation_rows(
            context=context,
            data=data,
            chunk=chunk,
            rels=rels,
            seen_rel_keys=seen_rel_keys,
            refs=refs,
            pipeline_hash=pipeline_hash,
            relation_evidence_stats=relation_evidence_stats,
            rel_rows=rel_rows,
        )

        self._append_alias_relation_rows(
            context=context,
            data=data,
            chunk=chunk,
            refs=refs,
            pipeline_hash=pipeline_hash,
            seen_rel_keys=seen_rel_keys,
            rel_rows=rel_rows,
        )

    def _existing_alias_relation_keys(
        self,
        context: _RelationPostIndexContext,
        data: _RelationPassData,
        chunk: DocumentChunk,
        ok: bool,
    ) -> set[tuple[object, str, object]]:
        seen_rel_keys: set[tuple[object, str, object]] = set()
        alias_specs = data.alias_specs_by_chunk.get(chunk.id) or []
        llm_aliases_existing = context.llm_aliases_by_chunk.get(chunk.id) or []
        if ok or not (alias_specs or llm_aliases_existing):
            return seen_rel_keys
        try:
            existing = (
                context.session.query(
                    KgRelation.subject_entity_id,
                    KgRelation.predicate,
                    KgRelation.object_entity_id,
                )
                .filter(
                    KgRelation.tenant_id == context.state.tenant_id,
                    KgRelation.chunk_id == chunk.id,
                    KgRelation.predicate.in_(["alias_of", "same_as"]),
                )
                .all()
            )
            for subj_id, pred, obj_id in existing:
                if subj_id is not None and obj_id is not None:
                    seen_rel_keys.add((subj_id, str(pred or "").strip(), obj_id))
        except Exception as exc:
            logger.debug(_KG_EXTRACTOR_FALLBACK_LOG_MESSAGE, exc)
        return seen_rel_keys

    @staticmethod
    def _relation_entity_ids(
        data: _RelationPassData,
        subj_cand: CandidateEntity,
        obj_cand: CandidateEntity,
    ) -> tuple[object | None, object | None]:
        subj_key = (
            str(subj_cand.type or "unknown").strip() or "unknown",
            str(subj_cand.normalized_name or "").strip(),
        )
        obj_key = (
            str(obj_cand.type or "unknown").strip() or "unknown",
            str(obj_cand.normalized_name or "").strip(),
        )
        return data.entity_id_by_key.get(subj_key), data.entity_id_by_key.get(obj_key)

    @staticmethod
    def _relation_confidence(rel: dict[str, object]) -> float:
        conf_raw = rel.get("confidence")
        try:
            conf = float(conf_raw) if conf_raw is not None else 0.5
        except Exception:
            conf = 0.5
        return max(0.0, min(1.0, conf))

    def _append_extracted_relation_rows(
        self,
        *,
        context: _RelationPostIndexContext,
        data: _RelationPassData,
        chunk: DocumentChunk,
        rels: list[dict[str, object]],
        seen_rel_keys: set[tuple[object, str, object]],
        refs: dict[str, object],
        pipeline_hash: str | None,
        relation_evidence_stats: dict[str, int],
        rel_rows: list[KgRelation],
    ) -> None:
        cand_map = {candidate.cid: candidate for candidate in (data.candidates_by_chunk.get(chunk.id) or [])}
        for rel in rels:
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
            subj_ent_id, obj_ent_id = self._relation_entity_ids(data, subj_cand, obj_cand)
            if subj_ent_id is None or obj_ent_id is None:
                continue
            rel_key = (subj_ent_id, pred, obj_ent_id)
            if rel_key in seen_rel_keys:
                continue
            seen_rel_keys.add(rel_key)
            self._append_extracted_relation_row(
                context=context,
                chunk=chunk,
                rel=rel,
                subj_cand=subj_cand,
                obj_cand=obj_cand,
                subj_ent_id=subj_ent_id,
                obj_ent_id=obj_ent_id,
                pred=pred,
                refs=refs,
                pipeline_hash=pipeline_hash,
                relation_evidence_stats=relation_evidence_stats,
                rel_rows=rel_rows,
            )

    def _append_extracted_relation_row(
        self,
        *,
        context: _RelationPostIndexContext,
        chunk: DocumentChunk,
        rel: dict[str, object],
        subj_cand: CandidateEntity,
        obj_cand: CandidateEntity,
        subj_ent_id: object,
        obj_ent_id: object,
        pred: str,
        refs: dict[str, object],
        pipeline_hash: str | None,
        relation_evidence_stats: dict[str, int],
        rel_rows: list[KgRelation],
    ) -> None:
        conf = self._relation_confidence(rel)
        rel_refs = dict(refs)
        evidence, evidence_ok = self._build_relation_evidence(
            chunk=chunk,
            rel=rel,
            subj_cand=subj_cand,
            obj_cand=obj_cand,
            evidence_required=context.evidence_required,
        )
        if evidence is None and context.evidence_required:
            relation_evidence_stats["dropped_no_evidence"] += 1
            return
        if evidence is not None and not evidence_ok:
            relation_evidence_stats["dropped_missing_endpoints"] += 1
            return
        if evidence is not None:
            rel_refs["evidence_quote"] = evidence.quote
            rel_refs["evidence_start_char"] = int(evidence.start_char)
            rel_refs["evidence_end_char"] = int(evidence.end_char)
            rel_refs["evidence_source"] = str(getattr(evidence, "source", "") or "").strip() or "quote"
        relation_evidence_stats["kept"] += 1
        rel_rows.append(
            KgRelation(
                tenant_id=context.state.tenant_id,
                pipeline_hash=pipeline_hash,
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                event_id=None,
                subject_entity_id=subj_ent_id,
                predicate=pred,
                predicate_raw=(str(rel.get("predicate_raw") or "").strip() or None),
                object_entity_id=obj_ent_id,
                confidence=conf,
                qualifiers=rel.get("qualifiers") if isinstance(rel.get("qualifiers"), dict) else None,
                references=rel_refs,
                extra_data={
                    "kg_prompt_template_id": context.chosen_template_id,
                    "kg_prompt_template_key": context.config.prompt_template_key,
                    "kg_prompt_ab_experiment_key": context.config.prompt_ab_experiment_key,
                },
            )
        )

    @staticmethod
    def _heuristic_alias_entity_ids(
        data: _RelationPassData,
        ent_type: str,
        alias_norm: str,
        canonical_norm: str,
    ) -> tuple[object | None, object | None]:
        return data.entity_id_by_key.get((ent_type, alias_norm)), data.entity_id_by_key.get((ent_type, canonical_norm))

    def _append_heuristic_alias_relation_rows(
        self,
        *,
        context: _RelationPostIndexContext,
        data: _RelationPassData,
        chunk: DocumentChunk,
        refs: dict[str, object],
        pipeline_hash: str | None,
        seen_rel_keys: set[tuple[object, str, object]],
        rel_rows: list[KgRelation],
    ) -> None:
        for ent_type, alias_norm, canonical_norm, method, alias_quote in data.alias_specs_by_chunk.get(chunk.id) or []:
            subj_ent_id, obj_ent_id = self._heuristic_alias_entity_ids(data, ent_type, alias_norm, canonical_norm)
            if subj_ent_id is None or obj_ent_id is None or subj_ent_id == obj_ent_id:
                context.alias_diag["edges_skipped_missing_entities"] = (
                    int(context.alias_diag.get("edges_skipped_missing_entities", 0) or 0) + 1
                )
                self._alias_bump(
                    context.alias_stats_by_doc,
                    chunk.document_id,
                    "kg_alias_edges_skipped_missing_entities",
                    1,
                )
                continue
            rel_key = (subj_ent_id, "alias_of", obj_ent_id)
            if rel_key in seen_rel_keys or (obj_ent_id, "alias_of", subj_ent_id) in seen_rel_keys:
                context.alias_diag["edges_skipped_duplicate"] = (
                    int(context.alias_diag.get("edges_skipped_duplicate", 0) or 0) + 1
                )
                self._alias_bump(context.alias_stats_by_doc, chunk.document_id, "kg_alias_edges_skipped_duplicate", 1)
                continue
            seen_rel_keys.add(rel_key)
            context.alias_diag["edges_appended"] = int(context.alias_diag.get("edges_appended", 0) or 0) + 1
            self._alias_bump(context.alias_stats_by_doc, chunk.document_id, "kg_alias_edges_appended", 1)
            alias_refs = dict(refs)
            evidence = coerce_evidence(
                text=(chunk.content or ""),
                evidence_quote=(str(alias_quote).strip() or None),
                fallback_mention=None,
                max_quote_chars=240,
            )
            if evidence is None and context.evidence_required:
                continue
            if evidence is not None:
                alias_refs["evidence_quote"] = evidence.quote
                alias_refs["evidence_start_char"] = int(evidence.start_char)
                alias_refs["evidence_end_char"] = int(evidence.end_char)
                alias_refs["evidence_source"] = str(getattr(evidence, "source", "") or "").strip() or "quote"
            rel_rows.append(
                KgRelation(
                    tenant_id=context.state.tenant_id,
                    pipeline_hash=pipeline_hash,
                    document_id=chunk.document_id,
                    chunk_id=chunk.id,
                    event_id=None,
                    subject_entity_id=subj_ent_id,
                    predicate="alias_of",
                    predicate_raw=None,
                    object_entity_id=obj_ent_id,
                    confidence=float(data.alias_conf),
                    qualifiers={"method": "heuristic_alias", "pattern": str(method or "")},
                    references=alias_refs,
                    extra_data={
                        "kg_prompt_template_id": context.chosen_template_id,
                        "kg_prompt_template_key": context.config.prompt_template_key,
                        "kg_prompt_ab_experiment_key": context.config.prompt_ab_experiment_key,
                    },
                )
            )

    @staticmethod
    def _llm_alias_entity_ids(
        data: _RelationPassData,
        alias_cand: CandidateEntity,
        canon_cand: CandidateEntity,
    ) -> tuple[object | None, object | None]:
        ent_type = str(alias_cand.type or "unknown").strip() or "unknown"
        if str(canon_cand.type or "unknown").strip() != ent_type:
            return None, None
        alias_key = (ent_type, str(alias_cand.normalized_name or "").strip())
        canon_key = (ent_type, str(canon_cand.normalized_name or "").strip())
        return data.entity_id_by_key.get(alias_key), data.entity_id_by_key.get(canon_key)

    def _append_llm_alias_relation_rows(
        self,
        *,
        context: _RelationPostIndexContext,
        data: _RelationPassData,
        chunk: DocumentChunk,
        refs: dict[str, object],
        pipeline_hash: str | None,
        seen_rel_keys: set[tuple[object, str, object]],
        rel_rows: list[KgRelation],
    ) -> None:
        cand_map = {candidate.cid: candidate for candidate in (data.candidates_by_chunk.get(chunk.id) or [])}
        for item in context.llm_aliases_by_chunk.get(chunk.id) or []:
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
            subj_ent_id, obj_ent_id = self._llm_alias_entity_ids(data, alias_cand, canon_cand)
            if subj_ent_id is None or obj_ent_id is None or subj_ent_id == obj_ent_id:
                continue
            rel_key = (subj_ent_id, "alias_of", obj_ent_id)
            if rel_key in seen_rel_keys or (obj_ent_id, "alias_of", subj_ent_id) in seen_rel_keys:
                continue
            seen_rel_keys.add(rel_key)
            llm_refs = dict(refs)
            evidence = coerce_evidence(
                text=(chunk.content or ""),
                evidence_quote=(str(item.get("evidence_quote") or "").strip() or None),
                fallback_mention=None,
                max_quote_chars=240,
            )
            if evidence is None and context.evidence_required:
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
                    tenant_id=context.state.tenant_id,
                    pipeline_hash=pipeline_hash,
                    document_id=chunk.document_id,
                    chunk_id=chunk.id,
                    event_id=None,
                    subject_entity_id=subj_ent_id,
                    predicate="alias_of",
                    predicate_raw=None,
                    object_entity_id=obj_ent_id,
                    confidence=conf,
                    qualifiers={"method": "llm_entity_verify", "kind": "alias"},
                    references=llm_refs,
                    extra_data={
                        "kg_prompt_template_id": context.chosen_template_id,
                        "kg_prompt_template_key": context.config.prompt_template_key,
                        "kg_prompt_ab_experiment_key": context.config.prompt_ab_experiment_key,
                    },
                )
            )

    def _append_alias_relation_rows(
        self,
        *,
        context: _RelationPostIndexContext,
        data: _RelationPassData,
        chunk: DocumentChunk,
        refs: dict[str, object],
        pipeline_hash: str | None,
        seen_rel_keys: set[tuple[object, str, object]],
        rel_rows: list[KgRelation],
    ) -> None:
        self._append_heuristic_alias_relation_rows(
            context=context,
            data=data,
            chunk=chunk,
            refs=refs,
            pipeline_hash=pipeline_hash,
            seen_rel_keys=seen_rel_keys,
            rel_rows=rel_rows,
        )
        self._append_llm_alias_relation_rows(
            context=context,
            data=data,
            chunk=chunk,
            refs=refs,
            pipeline_hash=pipeline_hash,
            seen_rel_keys=seen_rel_keys,
            rel_rows=rel_rows,
        )

    def _build_relation_rows(
        self,
        context: _RelationPostIndexContext,
        data: _RelationPassData,
        relation_evidence_stats: dict[str, int],
    ) -> tuple[list[object], list[KgRelation]]:
        succeeded_chunk_ids: list[object] = []
        rel_rows: list[KgRelation] = []
        for chunk_id, rels, ok in data.rel_results:
            chunk = data.chunk_by_id.get(chunk_id)
            if chunk is None:
                continue
            if ok and chunk_id in data.rels_by_chunk:
                rels = data.rels_by_chunk.get(chunk_id) or []
            if ok:
                succeeded_chunk_ids.append(chunk_id)
            self._append_relation_rows_for_chunk(
                context=context,
                data=data,
                chunk=chunk,
                rels=rels,
                ok=ok,
                relation_evidence_stats=relation_evidence_stats,
                rel_rows=rel_rows,
            )
        return succeeded_chunk_ids, rel_rows

    @staticmethod
    def _relation_cleanup_chunk_ids(
        *,
        succeeded_chunk_ids: list[object],
        budget_skipped_chunk_ids: set[object],
        replace_existing: bool,
    ) -> list[object]:
        suffix = list(budget_skipped_chunk_ids) if replace_existing else []
        return list(dict.fromkeys(list(succeeded_chunk_ids) + suffix))

    def _persist_relation_rows(
        self,
        context: _RelationPostIndexContext,
        *,
        succeeded_chunk_ids: list[object],
        rel_rows: list[KgRelation],
    ) -> None:
        rel_cleanup_chunk_ids = self._relation_cleanup_chunk_ids(
            succeeded_chunk_ids=succeeded_chunk_ids,
            budget_skipped_chunk_ids=context.state.budget_skipped_chunk_ids,
            replace_existing=context.state.replace_existing,
        )
        if context.state.replace_existing and rel_cleanup_chunk_ids:
            RelationRepository(context.session).delete_relations_for_chunks(
                rel_cleanup_chunk_ids,
                tenant_id=context.state.tenant_id,
                commit=False,
            )
        if succeeded_chunk_ids or rel_rows:
            if rel_rows:
                context.session.add_all(rel_rows)
            context.session.commit()

    async def _run_post_index_passes(
        self,
        *,
        session,
        config: ExtractConfig,
        index_options: IndexingOptions | None,
        indexer,
        state: _ExtractState,
        progress: _ExtractProgress,
        processed_events: list[tuple[DocumentChunk, dict]],
        result,
        new_events: Sequence[KgSourceEvent],
        cleanup_chunk_ids: list[object],
        llm_client: object | None,
        alias_diag: dict[str, object],
        alias_stats_by_doc: dict[object, dict[str, int]],
        llm_aliases_by_chunk: dict[object, list[dict[str, object]]],
        relation_verify_enabled: bool,
        chosen_template_id: str | None,
        evidence_required: bool,
    ) -> tuple[dict[str, int], dict[str, int]]:
        relation_context = _RelationPostIndexContext(
            session=session,
            config=config,
            index_options=index_options,
            indexer=indexer,
            state=state,
            processed_events=processed_events,
            result=result,
            cleanup_chunk_ids=cleanup_chunk_ids,
            llm_client=llm_client,
            alias_diag=alias_diag,
            alias_stats_by_doc=alias_stats_by_doc,
            llm_aliases_by_chunk=llm_aliases_by_chunk,
            relation_verify_enabled=relation_verify_enabled,
            chosen_template_id=chosen_template_id,
            evidence_required=evidence_required,
        )
        skill_context = _SkillPostIndexContext(
            session=session,
            config=config,
            index_options=index_options,
            indexer=indexer,
            state=state,
            cleanup_chunk_ids=cleanup_chunk_ids,
            llm_client=llm_client,
            chosen_template_id=chosen_template_id,
            evidence_required=evidence_required,
            new_events=new_events,
        )
        relation_evidence_stats = await self._run_relation_post_index_pass(relation_context)
        skill_evidence_stats = await self._run_skill_post_index_pass(skill_context)
        return relation_evidence_stats, skill_evidence_stats

    async def _run_relation_post_index_pass(self, context: _RelationPostIndexContext) -> dict[str, int]:
        relation_evidence_stats: dict[str, int] = {
            "total_raw": 0,
            "kept": 0,
            "dropped_no_evidence": 0,
            "dropped_missing_endpoints": 0,
        }
        if not context.state.extract_relations_enabled or not context.cleanup_chunk_ids:
            return relation_evidence_stats

        try:
            data = self._build_relation_pass_data(context)
            await self._prepare_relation_alias_data(context, data)
            await self._populate_relation_extraction_results(context, data)
            succeeded_chunk_ids, rel_rows = self._build_relation_rows(
                context,
                data,
                relation_evidence_stats,
            )
            self._persist_relation_rows(
                context,
                succeeded_chunk_ids=succeeded_chunk_ids,
                rel_rows=rel_rows,
            )
        except Exception as exc:  # noqa: BLE001
            try:
                context.session.rollback()
            except Exception as rollback_exc:
                logger.debug(_KG_EXTRACTOR_FALLBACK_LOG_MESSAGE, rollback_exc)
            logger.warning("KG relation pass failed; continuing without relations: %s", str(exc)[:200])

        return relation_evidence_stats

    @staticmethod
    def _build_skill_pass_data(context: _SkillPostIndexContext) -> _SkillPassData:
        chunk_by_id = {
            chunk.id: chunk for chunk in context.state.resolved_chunks if getattr(chunk, "id", None) is not None
        }
        events_by_chunk: dict[object, list[object]] = {}
        for event in context.new_events:
            chunk_id = getattr(event, "chunk_id", None)
            if chunk_id is None or chunk_id not in context.cleanup_chunk_ids:
                continue
            events_by_chunk.setdefault(chunk_id, []).append(event)
        return _SkillPassData(chunk_by_id=chunk_by_id, events_by_chunk=events_by_chunk)

    @staticmethod
    def _dedupe_surfaces(values: object, *, limit: int) -> list[str]:
        lim = max(0, int(limit or 0))
        if lim <= 0:
            return []
        seq = values if isinstance(values, list) else []
        out: list[str] = []
        seen: set[str] = set()
        for item in seq:
            surface = str(item or "").strip()
            if not surface:
                continue
            key = surface.casefold() if surface.isascii() else surface
            if key in seen:
                continue
            seen.add(key)
            out.append(surface)
            if len(out) >= lim:
                break
        return out

    @staticmethod
    def _skill_embed_text(name: str, summary: str | None, steps: list[object]) -> str:
        embed_text = name
        if summary:
            embed_text += f"\n{summary}"
        if steps:
            embed_text += "\n" + "\n".join([str(step).strip() for step in steps[:6] if str(step).strip()])
        return embed_text[:2000]

    async def _extract_skills_for_chunk(
        self,
        *,
        chunk_id: object,
        data: _SkillPassData,
        skill_processor: SkillProcessor,
        max_skills_per_chunk: int,
        sem: asyncio.Semaphore,
        chunk_timeout_sec: float,
    ) -> tuple[object, list[dict[str, object]], bool]:
        chunk = data.chunk_by_id.get(chunk_id)
        if chunk is None or chunk_id not in data.events_by_chunk:
            return chunk_id, [], False
        try:
            async with sem:
                coro = skill_processor.extract_skills(
                    text=(chunk.content or ""),
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
                str(getattr(chunk, "id", "") or ""),
                str(exc)[:200],
            )
            return chunk_id, [], False

    def _normalize_skill_item(
        self,
        *,
        raw: dict,
        chunk_id: object,
        chunk: DocumentChunk,
        parser: EntityValueParser,
        skill_evidence_required: bool,
        skill_evidence_stats: dict[str, int],
    ) -> dict | None:
        name = str(raw.get("name") or "").strip()
        if not name:
            return None
        normalized = parser.normalize_name(name)
        if not normalized:
            return None
        skill_evidence_stats["total_raw"] += 1
        evidence_quote = raw.get("evidence_quote")
        evidence = coerce_evidence(
            text=(chunk.content or ""),
            evidence_quote=(str(evidence_quote).strip() if isinstance(evidence_quote, str) else None),
            fallback_mention=name,
            max_quote_chars=240,
        )
        if evidence is None and skill_evidence_required:
            skill_evidence_stats["dropped_no_evidence"] += 1
            return None
        summary = str(raw.get("summary") or "").strip() or None
        category = str(raw.get("category") or "").strip() or None
        steps = raw.get("steps") if isinstance(raw.get("steps"), list) else []
        inputs = raw.get("inputs") if isinstance(raw.get("inputs"), list) else []
        outputs = raw.get("outputs") if isinstance(raw.get("outputs"), list) else []
        tools = raw.get("tools") if isinstance(raw.get("tools"), list) else []
        tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
        skill_evidence_stats["kept"] += 1
        return {
            "name": name,
            "normalized_name": normalized,
            "type": "Skill",
            "description": summary,
            "vector": None,
            "extra_data": {
                "summary": summary,
                "category": category,
                "steps": [str(step).strip() for step in steps if str(step).strip()][:50],
                "inputs": [str(item).strip() for item in inputs if str(item).strip()][:50],
                "outputs": [str(item).strip() for item in outputs if str(item).strip()][:50],
                "tools": [str(item).strip() for item in tools if str(item).strip()][:50],
                "tags": self._dedupe_surfaces(tags, limit=10),
                "confidence": raw.get("confidence"),
            },
            "_embed_text": self._skill_embed_text(name, summary, steps),
            "_chunk_id": chunk_id,
            "_evidence_quote": evidence.quote if evidence is not None else None,
            "_evidence_start_char": int(evidence.start_char) if evidence is not None else None,
            "_evidence_end_char": int(evidence.end_char) if evidence is not None else None,
            "_evidence_source": (str(getattr(evidence, "source", "") or "").strip() if evidence is not None else None),
        }

    def _collect_skill_items_for_chunk(
        self,
        *,
        chunk_id: object,
        skills: list[dict[str, object]],
        data: _SkillPassData,
        parser: EntityValueParser,
        max_skills_per_chunk: int,
        skill_evidence_required: bool,
        skill_evidence_stats: dict[str, int],
    ) -> None:
        chunk = data.chunk_by_id.get(chunk_id)
        if chunk is None:
            return
        kept: list[dict] = []
        seen_norm: set[str] = set()
        for raw in skills:
            if not isinstance(raw, dict):
                continue
            item = self._normalize_skill_item(
                raw=raw,
                chunk_id=chunk_id,
                chunk=chunk,
                parser=parser,
                skill_evidence_required=skill_evidence_required,
                skill_evidence_stats=skill_evidence_stats,
            )
            if item is None:
                continue
            normalized = str(item.get("normalized_name") or "").strip()
            if normalized in seen_norm:
                continue
            seen_norm.add(normalized)
            kept.append(item)
            text = str(item.get("_embed_text") or "").strip()
            if text:
                data.skill_embed_texts.append(text)
            if len(kept) >= max_skills_per_chunk:
                break
        if kept:
            data.skills_by_chunk[chunk_id] = kept

    async def _collect_skills_by_chunk(
        self,
        context: _SkillPostIndexContext,
        data: _SkillPassData,
        *,
        max_skills_per_chunk: int,
        skill_evidence_required: bool,
        skill_evidence_stats: dict[str, int],
    ) -> None:
        parser = EntityValueParser()
        skill_processor = SkillProcessor(llm_client=context.llm_client)
        skill_results = await asyncio.gather(
            *[
                self._extract_skills_for_chunk(
                    chunk_id=chunk_id,
                    data=data,
                    skill_processor=skill_processor,
                    max_skills_per_chunk=max_skills_per_chunk,
                    sem=context.state.sem,
                    chunk_timeout_sec=context.state.chunk_timeout_sec,
                )
                for chunk_id in context.cleanup_chunk_ids
            ]
        )
        for chunk_id, skills, ok in skill_results:
            if ok and skills:
                self._collect_skill_items_for_chunk(
                    chunk_id=chunk_id,
                    skills=skills,
                    data=data,
                    parser=parser,
                    max_skills_per_chunk=max_skills_per_chunk,
                    skill_evidence_required=skill_evidence_required,
                    skill_evidence_stats=skill_evidence_stats,
                )

    async def _embed_skill_items(self, embedder: object, data: _SkillPassData) -> None:
        if not data.skill_embed_texts:
            return
        skill_vectors_by_text: dict[str, list[float]] = {}
        try:
            vectors = await embedder.generate_batch(data.skill_embed_texts)
            for text, vec in zip(data.skill_embed_texts, vectors, strict=False):
                if vec:
                    skill_vectors_by_text[str(text)] = list(vec)
        except Exception as exc:  # noqa: BLE001
            logger.warning("KG skill embedding failed; proceeding without vectors: %s", str(exc)[:200])
            skill_vectors_by_text = {}
        for chunk_skills in data.skills_by_chunk.values():
            for item in chunk_skills:
                embed_text = str(item.get("_embed_text") or "").strip()
                if embed_text and embed_text in skill_vectors_by_text:
                    item["vector"] = skill_vectors_by_text.get(embed_text)
                item.pop("_embed_text", None)
                try:
                    item["_confidence"] = float(item.get("extra_data", {}).get("confidence") or 0.6)
                except Exception:
                    item["_confidence"] = 0.6
                data.skill_entity_inputs.append(item)

    def _upsert_skill_entities(self, context: _SkillPostIndexContext, data: _SkillPassData) -> None:
        if not data.skill_entity_inputs:
            return
        upserted = context.indexer.upsert_entities(
            tenant_id=context.state.tenant_id,
            entities=[
                {key: value for key, value in item.items() if not str(key).startswith("_")}
                for item in data.skill_entity_inputs
                if isinstance(item, dict)
            ],
            options=context.index_options,
            commit=True,
        )
        for ent in upserted or []:
            if str(getattr(ent, "type", "") or "") != "Skill":
                continue
            normalized = str(getattr(ent, "normalized_name", "") or "").strip()
            if normalized:
                data.skill_id_by_norm[normalized] = getattr(ent, "id", None)

    @staticmethod
    def _collect_taxonomy_surfaces(
        skills_by_chunk: dict[object, list[dict]],
        parser: EntityValueParser,
    ) -> tuple[dict[str, str], dict[str, str]]:
        tag_surface_by_norm: dict[str, str] = {}
        category_surface_by_norm: dict[str, str] = {}
        for items in skills_by_chunk.values():
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                extra = item.get("extra_data") if isinstance(item.get("extra_data"), dict) else {}
                tags = extra.get("tags") if isinstance(extra.get("tags"), list) else []
                for tag in tags:
                    surface = str(tag or "").strip()
                    if not surface:
                        continue
                    normalized = parser.normalize_name(surface)
                    if normalized:
                        tag_surface_by_norm.setdefault(normalized, surface)
                category = str(extra.get("category") or "").strip()
                if category:
                    normalized = parser.normalize_name(category)
                    if normalized:
                        category_surface_by_norm.setdefault(normalized, category)
        return tag_surface_by_norm, category_surface_by_norm

    async def _embed_taxonomy_surfaces(
        self,
        embedder: object,
        tag_surface_by_norm: dict[str, str],
        category_surface_by_norm: dict[str, str],
        parser: EntityValueParser,
    ) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
        tag_vectors_by_norm: dict[str, list[float]] = {}
        category_vectors_by_norm: dict[str, list[float]] = {}
        to_embed = list(tag_surface_by_norm.values()) + list(category_surface_by_norm.values())
        if not to_embed:
            return tag_vectors_by_norm, category_vectors_by_norm
        try:
            vectors = await embedder.generate_batch(to_embed)
        except Exception as exc:  # noqa: BLE001
            logger.warning("KG skill taxonomy embedding failed; proceeding without vectors: %s", str(exc)[:200])
            vectors = [[] for _ in to_embed]
        for idx, vec in enumerate(list(vectors or [])):
            surface = str(to_embed[idx] or "").strip()
            if not surface:
                continue
            normalized = parser.normalize_name(surface)
            if not normalized:
                continue
            if surface in tag_surface_by_norm.values() and vec:
                tag_vectors_by_norm[normalized] = list(vec)
            elif surface in category_surface_by_norm.values() and vec:
                category_vectors_by_norm[normalized] = list(vec)
        return tag_vectors_by_norm, category_vectors_by_norm

    @staticmethod
    def _taxonomy_inputs(
        *,
        type_name: str,
        surfaces_by_norm: dict[str, str],
        vectors_by_norm: dict[str, list[float]],
    ) -> list[dict]:
        return [
            {
                "name": surface,
                "normalized_name": normalized,
                "type": type_name,
                "description": None,
                "vector": vectors_by_norm.get(normalized),
                "extra_data": {"source": "skill_taxonomy"},
            }
            for normalized, surface in surfaces_by_norm.items()
        ]

    def _merge_taxonomy_entities(self, upserted: object, *, expected_type: str, target: dict[str, object]) -> None:
        for ent in upserted or []:
            if str(getattr(ent, "type", "") or "") != expected_type:
                continue
            normalized = str(getattr(ent, "normalized_name", "") or "").strip()
            if normalized:
                target[normalized] = getattr(ent, "id", None)

    async def _upsert_skill_taxonomy(
        self,
        context: _SkillPostIndexContext,
        data: _SkillPassData,
    ) -> None:
        if not context.state.extract_relations_enabled:
            return
        parser = EntityValueParser()
        tag_surface_by_norm, category_surface_by_norm = self._collect_taxonomy_surfaces(data.skills_by_chunk, parser)
        try:
            tag_vectors_by_norm, category_vectors_by_norm = await self._embed_taxonomy_surfaces(
                context.state.embedder,
                tag_surface_by_norm,
                category_surface_by_norm,
                parser,
            )
            tag_inputs = self._taxonomy_inputs(
                type_name="SkillTag",
                surfaces_by_norm=tag_surface_by_norm,
                vectors_by_norm=tag_vectors_by_norm,
            )
            category_inputs = self._taxonomy_inputs(
                type_name="SkillCategory",
                surfaces_by_norm=category_surface_by_norm,
                vectors_by_norm=category_vectors_by_norm,
            )
            if tag_inputs:
                upserted_tags = context.indexer.upsert_entities(
                    tenant_id=context.state.tenant_id,
                    entities=tag_inputs,
                    options=context.index_options,
                    commit=True,
                )
                self._merge_taxonomy_entities(upserted_tags, expected_type="SkillTag", target=data.tag_id_by_norm)
            if category_inputs:
                upserted_categories = context.indexer.upsert_entities(
                    tenant_id=context.state.tenant_id,
                    entities=category_inputs,
                    options=context.index_options,
                    commit=True,
                )
                self._merge_taxonomy_entities(
                    upserted_categories,
                    expected_type="SkillCategory",
                    target=data.category_id_by_norm,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("KG skill taxonomy upsert failed; continuing without taxonomy nodes: %s", str(exc)[:200])

    def _skill_refs_base(
        self,
        chunk: DocumentChunk,
        state: _ExtractState,
    ) -> tuple[dict[str, object], str | None, dict[str, object], str]:
        refs_base, pipeline_hash = self._relation_refs_for_chunk(
            chunk,
            chunk_key_by_id=state.chunk_key_by_id,
            chunk_hash_by_id=state.chunk_hash_by_id,
            chunk_len_by_id=state.chunk_len_by_id,
        )
        link_extra_base = build_event_entity_provenance(
            document_id=chunk.document_id,
            chunk_id=chunk.id,
            references=refs_base,
        )
        return refs_base, pipeline_hash, link_extra_base, str(getattr(chunk, "content", "") or "")

    @staticmethod
    def _existing_skill_relation_keys(
        session,
        *,
        tenant_id: object,
        chunk_id: object,
    ) -> set[tuple[object, str, object]]:
        seen_skill_rel_keys: set[tuple[object, str, object]] = set()
        try:
            existing = (
                session.query(
                    KgRelation.subject_entity_id,
                    KgRelation.predicate,
                    KgRelation.object_entity_id,
                )
                .filter(
                    KgRelation.tenant_id == tenant_id,
                    KgRelation.chunk_id == chunk_id,
                    KgRelation.predicate.in_(["belong_to", "compose_with", "depends_on"]),
                )
                .all()
            )
            for subj_id, pred, obj_id in existing:
                if subj_id is not None and obj_id is not None:
                    seen_skill_rel_keys.add((subj_id, str(pred or "").strip(), obj_id))
        except Exception as exc:
            logger.debug(_KG_EXTRACTOR_FALLBACK_LOG_MESSAGE, exc)
        return seen_skill_rel_keys

    @staticmethod
    def _skill_ids_in_chunk(items: list[dict], skill_id_by_norm: dict[str, object]) -> list[tuple[object, float, dict]]:
        skill_ids: list[tuple[object, float, dict]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized = str(item.get("normalized_name") or "").strip()
            skill_id = skill_id_by_norm.get(normalized)
            if not skill_id:
                continue
            conf = float(item.get("_confidence") or 0.6)
            conf = max(0.0, min(1.0, conf))
            skill_ids.append((skill_id, conf, item))
        return skill_ids

    @staticmethod
    def _edge_refs_from_evidence(
        refs_base: dict[str, object],
        evidence,
        *,
        default_source: str,
    ) -> dict[str, object]:
        edge_refs = dict(refs_base)
        if evidence is None:
            return edge_refs
        edge_refs["evidence_quote"] = evidence.quote
        edge_refs["evidence_start_char"] = int(evidence.start_char)
        edge_refs["evidence_end_char"] = int(evidence.end_char)
        edge_refs["evidence_source"] = str(getattr(evidence, "source", "") or "").strip() or default_source
        return edge_refs

    @staticmethod
    def _skill_relation_extra_data(context: _SkillPostIndexContext) -> dict[str, object]:
        return {
            "kg_prompt_template_id": context.chosen_template_id,
            "kg_prompt_template_key": context.config.prompt_template_key,
            "kg_prompt_ab_experiment_key": context.config.prompt_ab_experiment_key,
        }

    def _append_skill_belong_to_edge(
        self,
        *,
        context: _SkillPostIndexContext,
        skill_id: object,
        object_id: object,
        conf: float,
        kind: str,
        surface: str,
        chunk_text: str,
        refs_base: dict[str, object],
        pipeline_hash: str | None,
        chunk: DocumentChunk,
        seen_skill_rel_keys: set[tuple[object, str, object]],
        skill_evidence_required: bool,
        skill_evidence_stats: dict[str, int],
        skill_rel_rows: list[KgRelation],
    ) -> None:
        rel_key = (skill_id, "belong_to", object_id)
        if rel_key in seen_skill_rel_keys:
            return
        evidence = coerce_evidence(
            text=chunk_text,
            evidence_quote=None,
            fallback_mention=surface,
            max_quote_chars=240,
        )
        if evidence is None and skill_evidence_required:
            skill_evidence_stats["taxonomy_edges_dropped_no_evidence"] += 1
            return
        seen_skill_rel_keys.add(rel_key)
        skill_rel_rows.append(
            KgRelation(
                tenant_id=context.state.tenant_id,
                pipeline_hash=pipeline_hash,
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                event_id=None,
                subject_entity_id=skill_id,
                predicate="belong_to",
                predicate_raw=None,
                object_entity_id=object_id,
                confidence=conf,
                qualifiers={"method": "skill_taxonomy", "kind": kind},
                references=self._edge_refs_from_evidence(refs_base, evidence, default_source="mention"),
                extra_data=self._skill_relation_extra_data(context),
            )
        )
        skill_evidence_stats["taxonomy_edges_kept"] += 1

    @staticmethod
    def _compose_pair_quote(a_item: dict, b_item: dict, chunk_text: str) -> tuple[str | None, int | None, int | None]:
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
                        quote = chunk_text[start2:end2]
                        if quote and len(quote) <= 240:
                            return quote, int(start2), int(end2)
        except Exception:
            return None, None, None
        return None, None, None

    def _append_compose_with_edges(
        self,
        *,
        context: _SkillPostIndexContext,
        chunk: DocumentChunk,
        pipeline_hash: str | None,
        refs_base: dict[str, object],
        chunk_text: str,
        skill_ids_in_chunk: list[tuple[object, float, dict]],
        seen_skill_rel_keys: set[tuple[object, str, object]],
        skill_evidence_required: bool,
        skill_evidence_stats: dict[str, int],
        skill_rel_rows: list[KgRelation],
    ) -> None:
        if len(skill_ids_in_chunk) < 2:
            return
        for i in range(len(skill_ids_in_chunk)):
            for j in range(i + 1, len(skill_ids_in_chunk)):
                a_id, a_conf, a_item = skill_ids_in_chunk[i]
                b_id, b_conf, b_item = skill_ids_in_chunk[j]
                conf = max(0.0, min(1.0, float(min(a_conf, b_conf) * 0.8)))
                pair_quote, pair_start, pair_end = self._compose_pair_quote(a_item, b_item, chunk_text)
                if pair_quote is None and skill_evidence_required:
                    skill_evidence_stats["taxonomy_edges_dropped_no_evidence"] += 1
                    continue
                pair_refs = dict(refs_base)
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
                            tenant_id=context.state.tenant_id,
                            pipeline_hash=pipeline_hash,
                            document_id=chunk.document_id,
                            chunk_id=chunk.id,
                            event_id=None,
                            subject_entity_id=subj,
                            predicate="compose_with",
                            predicate_raw=None,
                            object_entity_id=obj,
                            confidence=conf,
                            qualifiers={"method": "skill_taxonomy", "kind": "compose_with"},
                            references=pair_refs,
                            extra_data=self._skill_relation_extra_data(context),
                        )
                    )
                    skill_evidence_stats["taxonomy_edges_kept"] += 1

    def _append_skill_links(
        self,
        *,
        events: list[object],
        items: list[dict],
        skill_id_by_norm: dict[str, object],
        link_extra_base: dict[str, object],
        links: list[KgEventEntity],
    ) -> None:
        for event in events or []:
            event_id = getattr(event, "id", None)
            if event_id is None:
                continue
            for item in items:
                normalized = str(item.get("normalized_name") or "").strip()
                skill_id = skill_id_by_norm.get(normalized)
                if not skill_id:
                    continue
                conf = float(item.get("_confidence") or 0.6)
                conf = max(0.0, min(1.0, conf))
                link_extra = dict(link_extra_base or {})
                evidence_quote = item.get("_evidence_quote")
                if isinstance(evidence_quote, str) and evidence_quote.strip():
                    link_extra["evidence_quote"] = evidence_quote.strip()[:240]
                evidence_source = item.get("_evidence_source")
                if isinstance(evidence_source, str) and evidence_source.strip():
                    link_extra["evidence_source"] = evidence_source.strip()
                evidence_start = item.get("_evidence_start_char")
                evidence_end = item.get("_evidence_end_char")
                if isinstance(evidence_start, int):
                    link_extra["evidence_start_char"] = int(evidence_start)
                if isinstance(evidence_end, int):
                    link_extra["evidence_end_char"] = int(evidence_end)
                links.append(
                    KgEventEntity(
                        event_id=event_id,
                        entity_id=skill_id,
                        weight=conf,
                        role="skill",
                        extra_data=(link_extra or None),
                    )
                )

    def _build_skill_links_and_relations(
        self,
        context: _SkillPostIndexContext,
        data: _SkillPassData,
        *,
        skill_evidence_required: bool,
        skill_evidence_stats: dict[str, int],
    ) -> tuple[list[KgEventEntity], list[KgRelation]]:
        links: list[KgEventEntity] = []
        skill_rel_rows: list[KgRelation] = []
        parser = EntityValueParser()
        for chunk_id, items in data.skills_by_chunk.items():
            chunk = data.chunk_by_id.get(chunk_id)
            if chunk is None:
                continue
            refs_base, pipeline_hash, link_extra_base, chunk_text = self._skill_refs_base(chunk, context.state)
            if context.state.extract_relations_enabled:
                seen_skill_rel_keys = self._existing_skill_relation_keys(
                    context.session,
                    tenant_id=context.state.tenant_id,
                    chunk_id=chunk.id,
                )
                skill_ids_in_chunk = self._skill_ids_in_chunk(items, data.skill_id_by_norm)
                for skill_id, conf, item in skill_ids_in_chunk:
                    extra = item.get("extra_data") if isinstance(item.get("extra_data"), dict) else {}
                    for tag in extra.get("tags") if isinstance(extra.get("tags"), list) else []:
                        surface = str(tag or "").strip()
                        tag_id = data.tag_id_by_norm.get(parser.normalize_name(surface))
                        if surface and tag_id:
                            self._append_skill_belong_to_edge(
                                context=context,
                                skill_id=skill_id,
                                object_id=tag_id,
                                conf=conf,
                                kind="tag",
                                surface=surface,
                                chunk_text=chunk_text,
                                refs_base=refs_base,
                                pipeline_hash=pipeline_hash,
                                chunk=chunk,
                                seen_skill_rel_keys=seen_skill_rel_keys,
                                skill_evidence_required=skill_evidence_required,
                                skill_evidence_stats=skill_evidence_stats,
                                skill_rel_rows=skill_rel_rows,
                            )
                    category = str(extra.get("category") or "").strip()
                    category_id = data.category_id_by_norm.get(parser.normalize_name(category)) if category else None
                    if category and category_id:
                        self._append_skill_belong_to_edge(
                            context=context,
                            skill_id=skill_id,
                            object_id=category_id,
                            conf=conf,
                            kind="category",
                            surface=category,
                            chunk_text=chunk_text,
                            refs_base=refs_base,
                            pipeline_hash=pipeline_hash,
                            chunk=chunk,
                            seen_skill_rel_keys=seen_skill_rel_keys,
                            skill_evidence_required=skill_evidence_required,
                            skill_evidence_stats=skill_evidence_stats,
                            skill_rel_rows=skill_rel_rows,
                        )
                self._append_compose_with_edges(
                    context=context,
                    chunk=chunk,
                    pipeline_hash=pipeline_hash,
                    refs_base=refs_base,
                    chunk_text=chunk_text,
                    skill_ids_in_chunk=skill_ids_in_chunk,
                    seen_skill_rel_keys=seen_skill_rel_keys,
                    skill_evidence_required=skill_evidence_required,
                    skill_evidence_stats=skill_evidence_stats,
                    skill_rel_rows=skill_rel_rows,
                )
            self._append_skill_links(
                events=data.events_by_chunk.get(chunk_id) or [],
                items=items,
                skill_id_by_norm=data.skill_id_by_norm,
                link_extra_base=link_extra_base,
                links=links,
            )
        return links, skill_rel_rows

    @staticmethod
    def _persist_skill_links_and_relations(
        session,
        *,
        links: list[KgEventEntity],
        skill_rel_rows: list[KgRelation],
    ) -> None:
        if not links and not skill_rel_rows:
            return
        if links:
            session.add_all(links)
        if skill_rel_rows:
            session.add_all(skill_rel_rows)
        session.commit()

    async def _run_skill_post_index_pass(self, context: _SkillPostIndexContext) -> dict[str, int]:
        skill_evidence_stats: dict[str, int] = {
            "total_raw": 0,
            "kept": 0,
            "dropped_no_evidence": 0,
            "taxonomy_edges_kept": 0,
            "taxonomy_edges_dropped_no_evidence": 0,
        }
        if not context.state.extract_skills_enabled or not context.cleanup_chunk_ids:
            return skill_evidence_stats

        try:
            max_skills_per_chunk = max(
                0,
                int(getattr(settings, "KG_SKILL_MAX_SKILLS_PER_CHUNK", 3) or 3),
            )
            if max_skills_per_chunk <= 0:
                raise RuntimeError("KG_SKILL_MAX_SKILLS_PER_CHUNK must be > 0 when skills are enabled")
            skill_evidence_required = bool(getattr(settings, "KG_SKILL_EVIDENCE_REQUIRED", False))
            data = self._build_skill_pass_data(context)
            await self._collect_skills_by_chunk(
                context,
                data,
                max_skills_per_chunk=max_skills_per_chunk,
                skill_evidence_required=skill_evidence_required,
                skill_evidence_stats=skill_evidence_stats,
            )
            await self._embed_skill_items(context.state.embedder, data)
            self._upsert_skill_entities(context, data)
            await self._upsert_skill_taxonomy(context, data)
            links, skill_rel_rows = self._build_skill_links_and_relations(
                context,
                data,
                skill_evidence_required=skill_evidence_required,
                skill_evidence_stats=skill_evidence_stats,
            )
            self._persist_skill_links_and_relations(
                context.session,
                links=links,
                skill_rel_rows=skill_rel_rows,
            )
        except Exception as exc:  # noqa: BLE001
            try:
                context.session.rollback()
            except Exception as rollback_exc:
                logger.debug(_KG_EXTRACTOR_FALLBACK_LOG_MESSAGE, rollback_exc)
            logger.warning("KG skill pass failed; continuing without skills: %s", str(exc)[:200])

        return skill_evidence_stats

    def _writeback_document_metadata(
        self,
        *,
        session,
        tenant_id,
        chunks: Sequence[DocumentChunk],
        kept_events: Sequence[KgSourceEvent],
        skipped_chunk_ids: set[object],
        budget_skipped_chunk_ids: set[object],
        skipped_short_chunk_ids: set[object],
        failed_chunk_ids: set[object],
        retry_chunk_ids: set[object],
        budget_stats_by_doc: dict[object, dict[str, int | str]] | None = None,
        alias_stats_by_doc: dict[object, dict[str, int]] | None = None,
    ) -> None:
        try:
            from app.models.document import Document as DBDocument

            if not chunks:
                return

            doc_ids, _chunk_id_to_doc_id, counts = self._document_metadata_counts(
                chunks=chunks,
                kept_events=kept_events,
                skipped_chunk_ids=skipped_chunk_ids,
                budget_skipped_chunk_ids=budget_skipped_chunk_ids,
                skipped_short_chunk_ids=skipped_short_chunk_ids,
                failed_chunk_ids=failed_chunk_ids,
                retry_chunk_ids=retry_chunk_ids,
            )
            if not doc_ids:
                return

            extracted_at = datetime.now(UTC).isoformat()
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
                meta["kg_event_count"] = int(counts["events"].get(doc.id, 0))
                meta["kg_skipped_chunks"] = int(counts["skipped"].get(doc.id, 0))
                meta["kg_budget_skipped_chunks"] = int(counts["budget_skipped"].get(doc.id, 0))
                meta["kg_skipped_short_chunks"] = int(counts["short_skipped"].get(doc.id, 0))
                meta["kg_failed_chunks"] = int(counts["failed"].get(doc.id, 0))
                meta["kg_retry_chunks"] = int(counts["retry"].get(doc.id, 0))
                meta["kg_extracted_at"] = extracted_at
                budget_stats = budget_stats_by_doc.get(doc.id, {}) if isinstance(budget_stats_by_doc, dict) else {}
                self._apply_budget_metadata(meta, budget_stats)
                alias_stats = alias_stats_by_doc.get(doc.id, {}) if isinstance(alias_stats_by_doc, dict) else {}
                if isinstance(alias_stats, dict):
                    self._apply_alias_metadata(meta, alias_stats)
                doc.doc_metadata = meta
            session.commit()
        except Exception as exc:  # noqa: BLE001
            try:
                session.rollback()
            except Exception as rollback_exc:
                logger.debug(_KG_EXTRACTOR_FALLBACK_LOG_MESSAGE, rollback_exc)
            logger.warning("Failed to write back kg metrics to document metadata: %s", str(exc)[:200])
