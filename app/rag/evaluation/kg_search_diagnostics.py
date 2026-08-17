"""
Dynamic OneEval-style diagnostics for KG search.

Seed source: RAGAS regression cases (question + human-verified evidence chunk ids).

This module intentionally avoids adding new tables: it computes an on-demand report
that helps drive iterative improvements to:
- KG extraction quality (events/entities/relations/skills)
- KG search quality (recall/expand/rerank)

Optional persistence (compact run snapshots) is handled at the API layer.
"""

import asyncio
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.schemas.kg_diagnostics import (
    KGEvalAttribution,
    KGHardcaseOut,
    KGSearchDiagnosticsItem,
    KGSearchDiagnosticsRequest,
    KGSearchDiagnosticsResponse,
    KGSearchDiagnosticsSummary,
    KGSearchEntityOut,
    KGSearchEventOut,
    KGSearchRunMetrics,
    KGSearchRunResult,
)
from app.core.config import settings
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.models.evaluation import RagasRegressionCase
from app.rag.evaluation.kg_hardcase_deterministic import generate_hardcases_deterministic
from app.rag.evaluation.kg_hardcase_generator import generate_hardcases_llm
from app.rag.evaluation.kg_search_diagnostics_metrics import compute_kg_hit_metrics
from app.rag.kg.models import KgEntity, KgEventEntity, KgRelation, KgSourceEvent
from app.rag.kg.search.config import RerankStrategy, SearchConfig
from app.rag.kg.search.searcher import KGSearcher
from app.rag.kg.utils import get_logger
from app.services.regression_run_scope import validate_case_ids_belong_to_dataset

logger = get_logger("eval.kg_search_diagnostics")
_KG_DIAGNOSTICS_FALLBACK_LOG_MESSAGE = "Ignoring non-critical KG diagnostics fallback failure: %s"
_KG_RELATION_DEBUG_KEYS = (
    "enabled",
    "edges_fetched",
    "edges_used",
    "neighbors_selected",
    "neighbors_total",
    "min_confidence",
    "max_edges",
    "max_neighbors",
)
_KG_SKILL_ENTITY_TYPES = {"Skill", "SkillTag", "SkillCategory"}


@dataclass(frozen=True)
class _DiagnosticsLimits:
    dataset_id: UUID
    max_cases: int
    k: int
    diag_max_results: int
    hardcase_mode: str
    hardcases_per_failed: int
    max_failed_for_hardcase: int
    llm_temperature: float
    extract_skills: bool | None
    extract_relations: bool | None


@dataclass(frozen=True)
class _CaseContext:
    case: RagasRegressionCase
    question: str
    chunk_ids: list[str]
    evidence_snips: list[str]
    evidence_set: set[str]
    gt_event_ids: list[str]
    gt_has_skill: bool
    scope_doc_uuids: list[UUID]


@dataclass(frozen=True)
class _SearchScope:
    tenant_id: UUID
    dataset_id: UUID
    account_id: str
    document_ids: list[UUID]
    max_results: int


@dataclass
class _SearchOutcome:
    cfg: SearchConfig
    raw_events: list[dict[str, Any]]
    raw_entities: list[dict[str, Any]]
    raw_clues: list[dict[str, Any]]
    raw_stats: dict[str, Any]
    error: str | None


@dataclass
class _EvaluatedSearch:
    outcome: _SearchOutcome
    metrics: KGSearchRunMetrics
    clue_counts: dict[str, int]
    first_hit_rank: int | None
    selected_has_skill: bool
    relation_debug: dict[str, Any] | None


@dataclass(frozen=True)
class _PendingLLMHardcase:
    case: RagasRegressionCase
    evidence_snips: list[str]
    entity_hints: list[str]
    scope_doc_uuids: list[UUID]
    evidence_set: set[str]


@dataclass
class _CaseEvaluation:
    ctx: _CaseContext
    scope: _SearchScope
    baseline: _EvaluatedSearch
    item: KGSearchDiagnosticsItem


@dataclass
class _DiagnosticsRunState:
    preflight: dict[str, Any]
    items_out: list[KGSearchDiagnosticsItem] = field(default_factory=list)
    failure_breakdown: dict[str, int] = field(default_factory=dict)
    baseline_hits: list[float] = field(default_factory=list)
    baseline_mrrs: list[float] = field(default_factory=list)
    baseline_recalls: list[float] = field(default_factory=list)
    baseline_ndcgs: list[float] = field(default_factory=list)
    baseline_maps: list[float] = field(default_factory=list)
    hardcase_hits: list[float] = field(default_factory=list)
    hardcase_mrrs: list[float] = field(default_factory=list)
    hardcase_recalls: list[float] = field(default_factory=list)
    hardcase_ndcgs: list[float] = field(default_factory=list)
    hardcase_maps: list[float] = field(default_factory=list)
    hardcases_generated: int = 0
    failed_for_hardcase: list[_PendingLLMHardcase] = field(default_factory=list)
    deterministic_failed_cases_used: int = 0

    def record_baseline(self, metrics: KGSearchRunMetrics) -> None:
        self.baseline_hits.append(1.0 if metrics.hit_at_k else 0.0)
        self.baseline_mrrs.append(float(metrics.mrr))
        self.baseline_recalls.append(float(metrics.recall))
        self.baseline_ndcgs.append(float(metrics.ndcg))
        self.baseline_maps.append(float(metrics.map))

    def record_hardcase(self, metrics: KGSearchRunMetrics) -> None:
        self.hardcase_hits.append(1.0 if metrics.hit_at_k else 0.0)
        self.hardcase_mrrs.append(float(metrics.mrr))
        self.hardcase_recalls.append(float(metrics.recall))
        self.hardcase_ndcgs.append(float(metrics.ndcg))
        self.hardcase_maps.append(float(metrics.map))

    def record_failure(self, primary_cause: str) -> None:
        if primary_cause == "ok":
            return
        self.failure_breakdown[primary_cause] = int(self.failure_breakdown.get(primary_cause, 0) or 0) + 1

    def can_generate_deterministic_hardcases(self, limits: _DiagnosticsLimits) -> bool:
        return int(self.deterministic_failed_cases_used) < int(limits.max_failed_for_hardcase)

    def note_deterministic_case_used(self) -> None:
        self.deterministic_failed_cases_used += 1


def _collapse_ws(text: Any) -> str:
    s = "" if text is None else str(text)
    return " ".join(s.strip().split())


def _coerce_uuid_list(values: Iterable[Any]) -> list[UUID]:
    out: list[UUID] = []
    seen: set[UUID] = set()
    for v in values or []:
        if v is None:
            continue
        try:
            u = UUID(str(v))
        except Exception:
            logger.debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _truncate_text(text: Any, *, max_chars: int) -> str:
    s = "" if text is None else str(text)
    lim = max(0, int(max_chars or 0))
    if lim <= 0 or len(s) <= lim:
        return s
    return s[:lim] + "..."


def _extract_evidence_fields(case: RagasRegressionCase) -> tuple[list[str], list[str], list[str]]:
    """
    Returns: (chunk_ids, document_ids, evidence_snippets)
    """
    refs = getattr(case, "reference_sources", None) or []
    chunk_ids: list[str] = []
    doc_ids: list[str] = []
    snippets: list[str] = []
    seen_chunks: set[str] = set()
    seen_docs: set[str] = set()
    for src in refs or []:
        if not isinstance(src, dict):
            continue
        cid = str(src.get("chunk_id") or "").strip()
        if cid and cid not in seen_chunks:
            seen_chunks.add(cid)
            chunk_ids.append(cid)
        did = str(src.get("document_id") or "").strip()
        if did and did not in seen_docs:
            seen_docs.add(did)
            doc_ids.append(did)
        quote = str(src.get("quote") or "").strip()
        if quote and len(snippets) < 2:
            snippets.append(_truncate_text(quote, max_chars=800))
    return chunk_ids, doc_ids, snippets


def _first_hit_rank(events: Sequence[dict[str, Any]], evidence_chunk_ids: set[str]) -> int | None:
    ev_set = {str(x).strip() for x in (evidence_chunk_ids or set()) if str(x).strip()}
    if not ev_set:
        return None
    for idx, ev in enumerate(events or [], 1):
        if not isinstance(ev, dict):
            continue
        cid = str(ev.get("chunk_id") or "").strip()
        if cid and cid in ev_set:
            return idx
    return None


def _summarize_clues(clues: Any) -> dict[str, int]:
    if not isinstance(clues, list):
        return {"total": 0, "query_to_entity": 0, "query_to_event": 0}
    q2e = 0
    q2v = 0
    for c in clues:
        if not isinstance(c, dict):
            continue
        rel = str(c.get("relation") or "").strip()
        if rel == "query->entity":
            q2e += 1
        if rel == "query->event":
            q2v += 1
    return {"total": int(len(clues)), "query_to_entity": int(q2e), "query_to_event": int(q2v)}


def _event_out(ev: dict[str, Any]) -> KGSearchEventOut:
    return KGSearchEventOut(
        id=str(ev.get("id") or ""),
        title=_truncate_text(ev.get("title") or "", max_chars=160),
        summary=_truncate_text(ev.get("summary") or "", max_chars=600),
        content=_truncate_text(ev.get("content") or "", max_chars=600),
        document_id=(str(ev.get("document_id")) if ev.get("document_id") is not None else None),
        chunk_id=(str(ev.get("chunk_id")) if ev.get("chunk_id") is not None else None),
        score=float(ev.get("score", 0.0) or 0.0),
    )


def _entity_out(ent: dict[str, Any]) -> KGSearchEntityOut:
    return KGSearchEntityOut(
        entity_id=str(ent.get("entity_id") or ""),
        name=_truncate_text(ent.get("name") or "", max_chars=160),
        type=str(ent.get("type") or "unknown"),
        weight=float(ent.get("weight", 0.0) or 0.0),
    )


async def _ensure_kg_extracted_for_document(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    document_id: UUID,
    extract_skills: bool | None,
    extract_relations: bool | None,
) -> tuple[bool, str | None, int]:
    """
    Returns: (ok, error, event_count)
    """
    # Load chunks from the request-scoped session (fast path for checking empties).
    chunks: list[DocumentChunk] = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    if not chunks:
        return False, "document has no chunks", 0

    # Use the existing KG extraction engine (which manages its own DB session).
    from app.rag.kg.pipeline import extract_events

    try:
        events = await extract_events(
            [c.id for c in chunks],
            tenant_id=tenant_id,
            chunks=chunks,
            ab_user_key=account_id,
            extract_skills=extract_skills,
            extract_relations=extract_relations,
            replace_existing=True,
            prune_orphan_entities=True,
        )
        return True, None, int(len(events or []))
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:200], 0


def _resolve_ground_truth_event_ids(
    db: Session,
    *,
    tenant_id: UUID,
    evidence_chunk_ids: Sequence[str],
) -> list[str]:
    chunk_uuids = _coerce_uuid_list(evidence_chunk_ids)
    if not chunk_uuids:
        return []
    rows = (
        db.query(KgSourceEvent.id)
        .filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.chunk_id.in_(chunk_uuids))
        .all()
    )
    return [str(r[0]) for r in rows if r and r[0] is not None]


def _ground_truth_has_skill(
    db: Session,
    *,
    ground_truth_event_ids: Sequence[str],
) -> bool:
    ev_ids = _coerce_uuid_list(ground_truth_event_ids)
    if not ev_ids:
        return False

    # Cheap existence query: any Skill-like entity linked to any ground-truth event.
    row = (
        db.query(KgEntity.id)
        .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
        .filter(KgEventEntity.event_id.in_(ev_ids), KgEntity.type.in_(["Skill", "SkillTag", "SkillCategory"]))
        .limit(1)
        .first()
    )
    return bool(row)


def _entity_hints_for_events(
    db: Session,
    *,
    ground_truth_event_ids: Sequence[str],
    limit: int = 12,
) -> list[str]:
    ev_ids = _coerce_uuid_list(ground_truth_event_ids)
    if not ev_ids:
        return []

    lim = max(0, int(limit or 0))
    if lim <= 0:
        return []

    # Rank entities by max observed edge weight across the ground-truth events.
    rows = (
        db.query(KgEntity.name, func.max(KgEventEntity.weight).label("w"))
        .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
        .filter(KgEventEntity.event_id.in_(ev_ids))
        .group_by(KgEntity.name)
        .order_by(func.max(KgEventEntity.weight).desc(), KgEntity.name.asc())
        .limit(lim)
        .all()
    )
    out: list[str] = []
    for name, _w in rows:
        s = _collapse_ws(name)
        if s:
            out.append(s)
    return out


def _dedupe_strs(values: Sequence[Any], *, limit: int) -> list[str]:
    lim = max(0, int(limit or 0))
    if lim <= 0:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for v in values or []:
        s = _collapse_ws(v)
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= lim:
            break
    return out


def _normalize_limits(req: KGSearchDiagnosticsRequest) -> _DiagnosticsLimits:
    dataset_id = UUID(str(req.dataset_id))
    k = max(1, min(int(req.k or 0), 50))
    return _DiagnosticsLimits(
        dataset_id=dataset_id,
        max_cases=max(1, min(int(req.max_cases or 0), 200)),
        k=k,
        diag_max_results=max(k, 30),
        hardcase_mode=str(req.hardcase_mode or "llm").strip().lower(),
        hardcases_per_failed=max(0, min(int(req.hardcases_per_failed_case or 0), 20)),
        max_failed_for_hardcase=max(0, min(int(req.max_failed_cases_for_hardcase or 0), 200)),
        llm_temperature=float(req.llm_temperature or 0.2),
        extract_skills=req.extract_skills,
        extract_relations=req.extract_relations,
    )


def _new_preflight_state(*, enabled: bool) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "documents_total": 0,
        "documents_missing_kg": 0,
        "documents_extracted_ok": 0,
        "documents_extracted_failed": 0,
        "elapsed_sec": 0.0,
        "errors": [],
    }


def _load_cases(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    req: KGSearchDiagnosticsRequest,
    max_cases: int,
) -> tuple[int, list[RagasRegressionCase]]:
    query = db.query(RagasRegressionCase).filter(
        RagasRegressionCase.tenant_id == tenant_id,
        RagasRegressionCase.dataset_id == dataset_id,
    )
    if req.case_ids:
        want = _coerce_uuid_list(req.case_ids)
        rows = (
            db.query(RagasRegressionCase.id, RagasRegressionCase.dataset_id)
            .filter(RagasRegressionCase.tenant_id == tenant_id, RagasRegressionCase.id.in_(want))
            .all()
        )
        validate_case_ids_belong_to_dataset(dataset_id=dataset_id, case_ids=want, rows=rows)
        query = query.filter(RagasRegressionCase.id.in_(want))
    total = int(query.count())
    cases = query.order_by(RagasRegressionCase.updated_at.desc()).limit(max_cases).all()
    return total, list(cases)


def _collect_case_document_ids(cases: Sequence[RagasRegressionCase]) -> list[UUID]:
    all_doc_ids: list[str] = []
    for case in cases:
        _chunk_ids, doc_ids, _snips = _extract_evidence_fields(case)
        all_doc_ids.extend(doc_ids)
    return _coerce_uuid_list(all_doc_ids)


def _load_missing_kg_document_ids(
    db: Session,
    *,
    tenant_id: UUID,
    document_ids: Sequence[UUID],
) -> list[UUID]:
    if not document_ids:
        return []
    docs = (
        db.query(DBDocument.id, DBDocument.doc_metadata)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(document_ids))
        .all()
    )
    missing: list[UUID] = []
    for doc_id, meta in docs:
        md = meta if isinstance(meta, dict) else {}
        kg_extracted_at = str(md.get("kg_extracted_at") or "").strip()
        if not kg_extracted_at:
            missing.append(UUID(str(doc_id)))
    return missing


def _increment_preflight(preflight: dict[str, Any], key: str) -> None:
    preflight[key] = int(preflight.get(key, 0) or 0) + 1


def _append_preflight_error(
    preflight: dict[str, Any],
    *,
    document_id: UUID,
    error: str | None,
    event_count: int,
) -> None:
    if not error:
        return
    errors = preflight.get("errors")
    if not isinstance(errors, list):
        errors = []
        preflight["errors"] = errors
    errors.append(
        {
            "document_id": str(document_id),
            "error": str(error)[:200],
            "event_count": int(event_count),
        }
    )


async def _run_preflight_extraction(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    cases: Sequence[RagasRegressionCase],
    limits: _DiagnosticsLimits,
    preflight: dict[str, Any],
) -> None:
    if not preflight.get("enabled") or not cases:
        return

    t0 = time.perf_counter()
    doc_uuids = _collect_case_document_ids(cases)
    preflight["documents_total"] = int(len(doc_uuids))
    if not doc_uuids:
        preflight["elapsed_sec"] = round(float(time.perf_counter() - t0), 3)
        return

    missing = _load_missing_kg_document_ids(db, tenant_id=tenant_id, document_ids=doc_uuids)
    preflight["documents_missing_kg"] = int(len(missing))
    if missing:
        max_conc = max(
            1,
            min(int(getattr(settings, "KG_EXTRACT_MAX_CONCURRENCY", 3) or 3), 5),
        )
        sem = asyncio.Semaphore(max_conc)

        async def _one(document_id: UUID) -> None:
            async with sem:
                ok, err, ev_count = await _ensure_kg_extracted_for_document(
                    db=db,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    document_id=document_id,
                    extract_skills=limits.extract_skills,
                    extract_relations=limits.extract_relations,
                )
                if ok:
                    _increment_preflight(preflight, "documents_extracted_ok")
                    return
                _increment_preflight(preflight, "documents_extracted_failed")
                _append_preflight_error(
                    preflight,
                    document_id=document_id,
                    error=err,
                    event_count=ev_count,
                )

        await asyncio.gather(*[_one(document_id) for document_id in missing])
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(_KG_DIAGNOSTICS_FALLBACK_LOG_MESSAGE, exc)

    preflight["elapsed_sec"] = round(float(time.perf_counter() - t0), 3)


def _build_case_context(
    db: Session,
    *,
    tenant_id: UUID,
    case: RagasRegressionCase,
) -> _CaseContext:
    question = str(case.question or "").strip()
    chunk_ids, _doc_ids, evidence_snips = _extract_evidence_fields(case)
    evidence_set = {str(value).strip() for value in chunk_ids if str(value).strip()}
    gt_event_ids = _resolve_ground_truth_event_ids(
        db,
        tenant_id=tenant_id,
        evidence_chunk_ids=chunk_ids,
    )
    scope_doc_ids_raw = getattr(case, "document_ids", None) or []
    return _CaseContext(
        case=case,
        question=question,
        chunk_ids=chunk_ids,
        evidence_snips=evidence_snips,
        evidence_set=evidence_set,
        gt_event_ids=gt_event_ids,
        gt_has_skill=_ground_truth_has_skill(db, ground_truth_event_ids=gt_event_ids),
        scope_doc_uuids=_coerce_uuid_list(scope_doc_ids_raw),
    )


def _build_search_scope(
    *,
    tenant_id: UUID,
    account_id: str,
    limits: _DiagnosticsLimits,
    scope_doc_uuids: Sequence[UUID],
) -> _SearchScope:
    return _SearchScope(
        tenant_id=tenant_id,
        dataset_id=limits.dataset_id,
        account_id=account_id,
        document_ids=list(scope_doc_uuids),
        max_results=limits.diag_max_results,
    )


def _relation_debug_from_stats(stats: dict[str, Any]) -> dict[str, Any] | None:
    relation_debug = stats.get("relation_expansion")
    return relation_debug if isinstance(relation_debug, dict) else None


def _compact_relation_debug(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value.get(key) for key in _KG_RELATION_DEBUG_KEYS if key in value}


def _build_search_config(
    scope: _SearchScope,
    *,
    query: str,
    relation_expansion_enabled: bool | None = None,
    include_skill_entities: bool = True,
    expand_enabled: bool | None = None,
    expand_max_hops: int | None = None,
    rerank_strategy: RerankStrategy | None = None,
    vector_recall_enabled: bool | None = None,
    graph_embeddings_enabled: bool | None = None,
) -> SearchConfig:
    cfg = SearchConfig(
        query=str(query or ""),
        tenant_id=scope.tenant_id,
        dataset_id=(None if scope.document_ids else scope.dataset_id),
        account_id=scope.account_id,
        document_ids=(scope.document_ids or None),
        relation_expansion_enabled=relation_expansion_enabled,
        vector_recall_enabled=vector_recall_enabled,
        graph_embeddings_enabled=graph_embeddings_enabled,
        include_skill_entities=include_skill_entities,
    )
    if rerank_strategy is not None:
        cfg.rerank.strategy = rerank_strategy
    if expand_enabled is not None:
        cfg.expand.enabled = bool(expand_enabled)
    if expand_max_hops is not None:
        try:
            cfg.expand.max_hops = max(1, min(int(expand_max_hops), 5))
        except Exception as exc:
            logger.debug(_KG_DIAGNOSTICS_FALLBACK_LOG_MESSAGE, exc)
    cfg.rerank.max_results = int(scope.max_results)
    return cfg


async def _run_search(
    searcher: KGSearcher,
    *,
    scope: _SearchScope,
    query: str,
    relation_expansion_enabled: bool | None = None,
    include_skill_entities: bool = True,
    expand_enabled: bool | None = None,
    expand_max_hops: int | None = None,
    rerank_strategy: RerankStrategy | None = None,
    vector_recall_enabled: bool | None = None,
    graph_embeddings_enabled: bool | None = None,
) -> _SearchOutcome:
    cfg = _build_search_config(
        scope,
        query=query,
        relation_expansion_enabled=relation_expansion_enabled,
        include_skill_entities=include_skill_entities,
        expand_enabled=expand_enabled,
        expand_max_hops=expand_max_hops,
        rerank_strategy=rerank_strategy,
        vector_recall_enabled=vector_recall_enabled,
        graph_embeddings_enabled=graph_embeddings_enabled,
    )
    try:
        raw = await searcher.search(cfg)
        return _SearchOutcome(
            cfg=cfg,
            raw_events=list((raw or {}).get("events") or []),
            raw_entities=list((raw or {}).get("entities") or []),
            raw_clues=list((raw or {}).get("clues") or []),
            raw_stats=dict((raw or {}).get("stats") or {}),
            error=None,
        )
    except Exception as exc:
        return _SearchOutcome(
            cfg=cfg,
            raw_events=[],
            raw_entities=[],
            raw_clues=[],
            raw_stats={},
            error=str(exc)[:200],
        )


def _evaluate_search_outcome(
    outcome: _SearchOutcome,
    *,
    evidence_set: set[str],
    k: int,
) -> _EvaluatedSearch:
    metrics = KGSearchRunMetrics(
        **compute_kg_hit_metrics(
            events=outcome.raw_events,
            evidence_chunk_ids=evidence_set,
            k=k,
        )
    )
    return _EvaluatedSearch(
        outcome=outcome,
        metrics=metrics,
        clue_counts=_summarize_clues(outcome.raw_clues),
        first_hit_rank=_first_hit_rank(outcome.raw_events, evidence_set),
        selected_has_skill=any(
            isinstance(entity, dict) and str(entity.get("type") or "").strip() in _KG_SKILL_ENTITY_TYPES
            for entity in outcome.raw_entities
        ),
        relation_debug=_relation_debug_from_stats(outcome.raw_stats),
    )


def _evaluated_run_to_result(query: str, evaluated: _EvaluatedSearch) -> KGSearchRunResult:
    return KGSearchRunResult(
        query=query,
        events=[_event_out(event) for event in evaluated.outcome.raw_events if isinstance(event, dict)],
        entities=[_entity_out(entity) for entity in evaluated.outcome.raw_entities if isinstance(entity, dict)],
        clues=[clue for clue in evaluated.outcome.raw_clues if isinstance(clue, dict)],
        stats=evaluated.outcome.raw_stats,
        metrics=evaluated.metrics,
        error=evaluated.outcome.error,
    )


async def _run_evaluated_search(
    searcher: KGSearcher,
    *,
    scope: _SearchScope,
    query: str,
    evidence_set: set[str],
    k: int,
    relation_expansion_enabled: bool | None = None,
    include_skill_entities: bool = True,
    expand_enabled: bool | None = None,
    expand_max_hops: int | None = None,
    rerank_strategy: RerankStrategy | None = None,
    vector_recall_enabled: bool | None = None,
    graph_embeddings_enabled: bool | None = None,
) -> _EvaluatedSearch:
    outcome = await _run_search(
        searcher,
        scope=scope,
        query=query,
        relation_expansion_enabled=relation_expansion_enabled,
        include_skill_entities=include_skill_entities,
        expand_enabled=expand_enabled,
        expand_max_hops=expand_max_hops,
        rerank_strategy=rerank_strategy,
        vector_recall_enabled=vector_recall_enabled,
        graph_embeddings_enabled=graph_embeddings_enabled,
    )
    return _evaluate_search_outcome(outcome, evidence_set=evidence_set, k=k)


def _delta_vs_baseline(
    baseline: _EvaluatedSearch,
    alt_run: _EvaluatedSearch,
) -> dict[str, Any]:
    base_rank = baseline.first_hit_rank
    alt_rank = alt_run.first_hit_rank
    rank_delta = None
    if base_rank is not None and alt_rank is not None:
        rank_delta = int(base_rank) - int(alt_rank)
    return {
        "delta_hit_at_k": int(alt_run.metrics.hit_at_k) - int(baseline.metrics.hit_at_k),
        "delta_mrr": round(float(alt_run.metrics.mrr - baseline.metrics.mrr), 6),
        "delta_recall": round(float(alt_run.metrics.recall - baseline.metrics.recall), 6),
        "delta_first_hit_rank": rank_delta,
    }


def _ablation_result_payload(run: _EvaluatedSearch) -> dict[str, Any]:
    return {
        "hit_at_k": bool(run.metrics.hit_at_k),
        "mrr": float(run.metrics.mrr),
        "recall": float(run.metrics.recall),
        "first_hit_rank": int(run.first_hit_rank) if run.first_hit_rank is not None else None,
        "returned_events": int(len(run.outcome.raw_events)),
        "selected_entities": int(len(run.outcome.raw_entities)),
        "selected_has_skill": bool(run.selected_has_skill),
        "clues": run.clue_counts,
        "relation_expansion": _compact_relation_debug(run.relation_debug),
        "error": run.outcome.error,
    }


async def _run_rerank_ablation(
    searcher: KGSearcher,
    *,
    scope: _SearchScope,
    question: str,
    evidence_set: set[str],
    k: int,
    baseline: _EvaluatedSearch,
) -> tuple[dict[str, Any], bool]:
    base = baseline.outcome.cfg.rerank.strategy
    alt = RerankStrategy.RRF if base == RerankStrategy.PAGERANK else RerankStrategy.PAGERANK
    alt_run = await _run_evaluated_search(
        searcher,
        scope=scope,
        query=question,
        evidence_set=evidence_set,
        k=k,
        rerank_strategy=alt,
    )
    return (
        {
            "baseline": str(base),
            "alt": str(alt),
            "alt_run": _ablation_result_payload(alt_run),
            "delta": _delta_vs_baseline(baseline, alt_run),
        },
        bool(alt_run.metrics.hit_at_k),
    )


async def _run_relation_ablation(
    searcher: KGSearcher,
    *,
    scope: _SearchScope,
    question: str,
    evidence_set: set[str],
    k: int,
    baseline: _EvaluatedSearch,
) -> tuple[dict[str, Any], bool]:
    base_rel = bool((baseline.relation_debug or {}).get("enabled"))
    alt_run = await _run_evaluated_search(
        searcher,
        scope=scope,
        query=question,
        evidence_set=evidence_set,
        k=k,
        relation_expansion_enabled=(not base_rel),
    )
    return (
        {
            "baseline_enabled": base_rel,
            "alt_enabled": not base_rel,
            "alt_run": _ablation_result_payload(alt_run),
            "delta": _delta_vs_baseline(baseline, alt_run),
        },
        bool(alt_run.metrics.hit_at_k),
    )


async def _run_path_ablation(
    searcher: KGSearcher,
    *,
    scope: _SearchScope,
    question: str,
    evidence_set: set[str],
    k: int,
    baseline: _EvaluatedSearch,
) -> tuple[dict[str, Any], bool]:
    base_expand = bool(getattr(baseline.outcome.cfg.expand, "enabled", True))
    alt_run = await _run_evaluated_search(
        searcher,
        scope=scope,
        query=question,
        evidence_set=evidence_set,
        k=k,
        expand_enabled=(not base_expand),
    )
    return (
        {
            "baseline_enabled": base_expand,
            "alt_enabled": not base_expand,
            "alt_run": _ablation_result_payload(alt_run),
            "delta": _delta_vs_baseline(baseline, alt_run),
        },
        bool(alt_run.metrics.hit_at_k),
    )


async def _run_skill_nodes_ablation(
    searcher: KGSearcher,
    *,
    scope: _SearchScope,
    question: str,
    evidence_set: set[str],
    k: int,
    baseline: _EvaluatedSearch,
) -> tuple[dict[str, Any], bool]:
    alt_run = await _run_evaluated_search(
        searcher,
        scope=scope,
        query=question,
        evidence_set=evidence_set,
        k=k,
        include_skill_entities=False,
    )
    return (
        {
            "alt_enabled": False,
            "alt_run": _ablation_result_payload(alt_run),
            "delta": _delta_vs_baseline(baseline, alt_run),
        },
        bool(alt_run.metrics.hit_at_k),
    )


async def _run_case_ablations(
    searcher: KGSearcher,
    *,
    scope: _SearchScope,
    case_ctx: _CaseContext,
    baseline: _EvaluatedSearch,
    k: int,
) -> tuple[dict[str, Any], str | None]:
    if baseline.metrics.hit_at_k or not case_ctx.gt_event_ids or baseline.outcome.error is not None:
        return {}, None

    ablations: dict[str, Any] = {}
    override: str | None = None
    steps = (
        ("rerank_strategy", "rerank_cutoff", _run_rerank_ablation),
        ("relation_expansion", "relation", _run_relation_ablation),
        ("path_search", "path", _run_path_ablation),
        ("skill_nodes", "skill", _run_skill_nodes_ablation),
    )
    for key, cause, runner in steps:
        try:
            payload, hit = await runner(
                searcher,
                scope=scope,
                question=case_ctx.question,
                evidence_set=case_ctx.evidence_set,
                k=k,
                baseline=baseline,
            )
            ablations[key] = payload
            if override is None and hit:
                override = cause
        except Exception as exc:
            logger.debug(_KG_DIAGNOSTICS_FALLBACK_LOG_MESSAGE, exc)
    return ablations, override


def _build_attribution_signals(
    case_ctx: _CaseContext,
    evaluated: _EvaluatedSearch,
    *,
    ablations: dict[str, Any],
) -> dict[str, Any]:
    signals: dict[str, Any] = {
        "ground_truth_event_count": int(len(case_ctx.gt_event_ids)),
        "ground_truth_has_skill": bool(case_ctx.gt_has_skill),
        "selected_has_skill": bool(evaluated.selected_has_skill),
        "first_hit_rank": (int(evaluated.first_hit_rank) if evaluated.first_hit_rank is not None else None),
        "returned_events": int(len(evaluated.outcome.raw_events)),
        "selected_entities": int(len(evaluated.outcome.raw_entities)),
        "clues": evaluated.clue_counts,
        "relation_expansion": evaluated.relation_debug or {},
    }
    if ablations:
        signals["ablations"] = ablations
    return {key: value for key, value in signals.items() if value is not None}


def _determine_primary_cause(
    case_ctx: _CaseContext,
    evaluated: _EvaluatedSearch,
    *,
    ablation_override: str | None,
) -> str:
    primary_cause = _pick_primary_cause(
        gt_event_count=int(len(case_ctx.gt_event_ids)),
        metrics=evaluated.metrics,
        first_hit_rank=evaluated.first_hit_rank,
        relation_debug=evaluated.relation_debug,
        ground_truth_has_skill=case_ctx.gt_has_skill,
        selected_has_skill=bool(evaluated.selected_has_skill),
        clue_counts=evaluated.clue_counts,
        selected_entities=int(len(evaluated.outcome.raw_entities)),
        returned_events=int(len(evaluated.outcome.raw_events)),
    )
    if ablation_override is not None:
        return str(ablation_override)
    return primary_cause


def _build_case_item(
    case_ctx: _CaseContext,
    evaluated: _EvaluatedSearch,
    *,
    primary_cause: str,
    ablations: dict[str, Any],
) -> KGSearchDiagnosticsItem:
    return KGSearchDiagnosticsItem(
        case_id=case_ctx.case.id,
        question=case_ctx.question,
        tags=list(case_ctx.case.tags or []),
        evidence_chunk_ids=sorted(case_ctx.evidence_set),
        ground_truth_event_ids=list(case_ctx.gt_event_ids),
        baseline=_evaluated_run_to_result(case_ctx.question, evaluated),
        hardcases=[],
        attribution=KGEvalAttribution(
            primary_cause=primary_cause,
            signals=_build_attribution_signals(case_ctx, evaluated, ablations=ablations),
        ),
    )


async def _evaluate_case(
    searcher: KGSearcher,
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    limits: _DiagnosticsLimits,
    case: RagasRegressionCase,
) -> _CaseEvaluation:
    case_ctx = _build_case_context(db, tenant_id=tenant_id, case=case)
    scope = _build_search_scope(
        tenant_id=tenant_id,
        account_id=account_id,
        limits=limits,
        scope_doc_uuids=case_ctx.scope_doc_uuids,
    )
    baseline = await _run_evaluated_search(
        searcher,
        scope=scope,
        query=case_ctx.question,
        evidence_set=case_ctx.evidence_set,
        k=limits.k,
    )
    ablations, override = await _run_case_ablations(
        searcher,
        scope=scope,
        case_ctx=case_ctx,
        baseline=baseline,
        k=limits.k,
    )
    primary_cause = _determine_primary_cause(
        case_ctx,
        baseline,
        ablation_override=override,
    )
    return _CaseEvaluation(
        ctx=case_ctx,
        scope=scope,
        baseline=baseline,
        item=_build_case_item(
            case_ctx,
            baseline,
            primary_cause=primary_cause,
            ablations=ablations,
        ),
    )


def _load_deterministic_entity_rows(
    db: Session,
    *,
    tenant_id: UUID,
    event_ids: Sequence[UUID],
) -> list[tuple[UUID, str, str, float]]:
    return list(
        db.query(
            KgEntity.id,
            KgEntity.name,
            KgEntity.type,
            func.max(KgEventEntity.weight).label("w"),
        )
        .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
        .filter(KgEntity.tenant_id == tenant_id, KgEventEntity.event_id.in_(event_ids))
        .group_by(KgEntity.id, KgEntity.name, KgEntity.type)
        .order_by(func.max(KgEventEntity.weight).desc(), KgEntity.name.asc())
        .limit(80)
        .all()
    )


def _collect_skill_names(
    ent_rows: Sequence[tuple[UUID, str, str, float]],
) -> list[str]:
    skill_names = [row[1] for row in ent_rows if row and str(row[2] or "").strip() == "Skill" and row[1]]
    return _dedupe_strs(skill_names, limit=20)


def _load_relation_alias_pairs(
    db: Session,
    *,
    tenant_id: UUID,
    entity_ids: Sequence[UUID],
) -> list[tuple[str, str]]:
    if not entity_ids:
        return []
    try:
        from sqlalchemy.orm import aliased

        subj = aliased(KgEntity)
        obj = aliased(KgEntity)
        rel_rows = (
            db.query(KgRelation.confidence, subj.name, obj.name)
            .join(subj, subj.id == KgRelation.subject_entity_id)
            .join(obj, obj.id == KgRelation.object_entity_id)
            .filter(
                KgRelation.tenant_id == tenant_id,
                KgRelation.predicate.in_(["alias_of", "same_as"]),
                or_(
                    KgRelation.subject_entity_id.in_(entity_ids),
                    KgRelation.object_entity_id.in_(entity_ids),
                ),
            )
            .order_by(KgRelation.confidence.desc(), subj.name.asc(), obj.name.asc())
            .limit(60)
            .all()
        )
    except Exception:
        return []

    alias_pairs: list[tuple[str, str]] = []
    for _conf, alias_name, canonical_name in rel_rows:
        alias_surface = _collapse_ws(alias_name)
        canonical_surface = _collapse_ws(canonical_name)
        if alias_surface and canonical_surface and alias_surface.casefold() != canonical_surface.casefold():
            alias_pairs.append((alias_surface, canonical_surface))
    return alias_pairs


def _fallback_alias_pairs(entity_names: Sequence[str]) -> list[tuple[str, str]]:
    try:
        from app.rag.kg.extraction.alias import choose_alias_direction, split_trailing_parenthetical_alias
    except Exception as exc:
        logger.debug(_KG_DIAGNOSTICS_FALLBACK_LOG_MESSAGE, exc)
        return []

    alias_pairs: list[tuple[str, str]] = []
    for name in entity_names:
        split = split_trailing_parenthetical_alias(str(name or ""))
        if not split:
            continue
        head, tail = split
        direction = choose_alias_direction(head, tail)
        if not direction:
            continue
        alias_surface, canonical_surface = direction
        alias_norm = _collapse_ws(alias_surface)
        canonical_norm = _collapse_ws(canonical_surface)
        if alias_norm and canonical_norm and alias_norm.casefold() != canonical_norm.casefold():
            alias_pairs.append((alias_norm, canonical_norm))
    return alias_pairs


def _load_skill_tags(
    db: Session,
    *,
    tenant_id: UUID,
    skill_ids: Sequence[UUID],
) -> list[str]:
    if not skill_ids:
        return []
    try:
        from sqlalchemy.orm import aliased

        obj = aliased(KgEntity)
        tag_rows = (
            db.query(KgRelation.confidence, obj.name)
            .join(obj, obj.id == KgRelation.object_entity_id)
            .filter(
                KgRelation.tenant_id == tenant_id,
                KgRelation.subject_entity_id.in_(skill_ids),
                KgRelation.predicate == "belong_to",
                obj.type.in_(["SkillTag", "SkillCategory"]),
            )
            .order_by(KgRelation.confidence.desc(), obj.name.asc())
            .limit(40)
            .all()
        )
    except Exception:
        return []
    return _dedupe_strs([name for _conf, name in tag_rows if name], limit=40)


def _deterministic_hardcase_candidates(
    db: Session,
    *,
    tenant_id: UUID,
    ground_truth_event_ids: Sequence[str],
) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """
    Collect KG-derived candidates for deterministic hardcase generation.

    Returns: (alias_pairs, skills, tags)
    """
    ev_ids = _coerce_uuid_list(ground_truth_event_ids)
    if not ev_ids:
        return [], [], []

    ent_rows = _load_deterministic_entity_rows(db, tenant_id=tenant_id, event_ids=ev_ids)
    if not ent_rows:
        return [], [], []

    entity_ids = [row[0] for row in ent_rows if row and row[0] is not None]
    entity_names = [row[1] for row in ent_rows if row and row[1]]
    skill_names = _collect_skill_names(ent_rows)

    alias_pairs = _load_relation_alias_pairs(db, tenant_id=tenant_id, entity_ids=entity_ids)
    if not alias_pairs and entity_names:
        alias_pairs = _fallback_alias_pairs(entity_names)

    skill_ids = [row[0] for row in ent_rows if row and str(row[2] or "").strip() == "Skill" and row[0] is not None]
    tags = _load_skill_tags(
        db,
        tenant_id=tenant_id,
        skill_ids=list(dict.fromkeys(skill_ids))[:50],
    )
    return list(dict.fromkeys(alias_pairs))[:60], skill_names, tags


def _pick_primary_cause(
    *,
    gt_event_count: int,
    metrics: KGSearchRunMetrics,
    first_hit_rank: int | None,
    relation_debug: dict[str, Any] | None,
    ground_truth_has_skill: bool,
    selected_has_skill: bool,
    clue_counts: dict[str, int],
    selected_entities: int,
    returned_events: int,
) -> str:
    if gt_event_count <= 0:
        return "extraction_missing"
    if metrics.hit_at_k:
        return "ok"
    if first_hit_rank is not None and int(first_hit_rank) > int(metrics.k):
        return "rerank_cutoff"
    if ground_truth_has_skill and not selected_has_skill:
        return "skill"

    rel_dbg = relation_debug or {}
    if bool(rel_dbg.get("enabled")) and int(rel_dbg.get("edges_used", 0) or 0) <= 0:
        return "relation"

    if returned_events <= 0 and (clue_counts.get("query_to_entity", 0) + clue_counts.get("query_to_event", 0)) <= 0:
        return "vector"
    if selected_entities <= 0:
        return "entity"
    return "other"


def _should_generate_deterministic_hardcases(
    limits: _DiagnosticsLimits,
    state: _DiagnosticsRunState,
    evaluation: _CaseEvaluation,
) -> bool:
    baseline = evaluation.baseline.metrics
    return bool(
        limits.hardcase_mode == "deterministic"
        and not baseline.hit_at_k
        and evaluation.ctx.gt_event_ids
        and limits.hardcases_per_failed > 0
        and state.can_generate_deterministic_hardcases(limits)
    )


def _queue_llm_hardcase_case(
    db: Session,
    *,
    state: _DiagnosticsRunState,
    limits: _DiagnosticsLimits,
    evaluation: _CaseEvaluation,
) -> None:
    baseline = evaluation.baseline.metrics
    if not (
        limits.hardcase_mode == "llm"
        and not baseline.hit_at_k
        and evaluation.ctx.gt_event_ids
        and limits.hardcases_per_failed > 0
        and len(state.failed_for_hardcase) < limits.max_failed_for_hardcase
    ):
        return
    state.failed_for_hardcase.append(
        _PendingLLMHardcase(
            case=evaluation.ctx.case,
            evidence_snips=list(evaluation.ctx.evidence_snips),
            entity_hints=_entity_hints_for_events(
                db,
                ground_truth_event_ids=evaluation.ctx.gt_event_ids,
                limit=12,
            ),
            scope_doc_uuids=list(evaluation.ctx.scope_doc_uuids),
            evidence_set=set(evaluation.ctx.evidence_set),
        )
    )


async def _append_hardcase_runs(
    searcher: KGSearcher,
    *,
    scope: _SearchScope,
    evidence_set: set[str],
    k: int,
    target: KGSearchDiagnosticsItem,
    hardcases: Sequence[Any],
    state: _DiagnosticsRunState,
) -> None:
    for hardcase in hardcases:
        state.hardcases_generated += 1
        evaluated = await _run_evaluated_search(
            searcher,
            scope=scope,
            query=str(hardcase.question),
            evidence_set=set(evidence_set),
            k=k,
        )
        state.record_hardcase(evaluated.metrics)
        target.hardcases.append(
            KGHardcaseOut(
                kind=hardcase.kind,
                question=hardcase.question,
                rationale=hardcase.rationale,
                run=_evaluated_run_to_result(str(hardcase.question), evaluated),
            )
        )


async def _run_deterministic_hardcases_for_case(
    searcher: KGSearcher,
    *,
    db: Session,
    tenant_id: UUID,
    limits: _DiagnosticsLimits,
    state: _DiagnosticsRunState,
    evaluation: _CaseEvaluation,
) -> None:
    alias_pairs, skills, tags = _deterministic_hardcase_candidates(
        db,
        tenant_id=tenant_id,
        ground_truth_event_ids=evaluation.ctx.gt_event_ids,
    )
    hardcases = generate_hardcases_deterministic(
        question=evaluation.ctx.question,
        alias_pairs=alias_pairs,
        skills=skills,
        tags=tags,
        max_items=limits.hardcases_per_failed,
    )
    if hardcases:
        state.note_deterministic_case_used()
    await _append_hardcase_runs(
        searcher,
        scope=evaluation.scope,
        evidence_set=evaluation.ctx.evidence_set,
        k=limits.k,
        target=evaluation.item,
        hardcases=hardcases,
        state=state,
    )


async def _load_kg_diagnostics_llm_client() -> Any | None:
    try:
        from app.rag.llm.factory import create_llm_client

        return await create_llm_client(scenario="kg_diagnostics")
    except Exception as exc:
        logger.warning("KG diagnostics hardcase LLM unavailable: %s", str(exc)[:200])
        return None


async def _run_llm_hardcases(
    searcher: KGSearcher,
    *,
    tenant_id: UUID,
    account_id: str,
    limits: _DiagnosticsLimits,
    state: _DiagnosticsRunState,
) -> None:
    if limits.hardcase_mode != "llm" or not state.failed_for_hardcase or limits.hardcases_per_failed <= 0:
        return

    llm_client = await _load_kg_diagnostics_llm_client()
    if llm_client is None:
        return

    for pending in state.failed_for_hardcase:
        target = next((item for item in state.items_out if item.case_id == pending.case.id), None)
        if target is None:
            continue

        hardcases = await generate_hardcases_llm(
            llm_client=llm_client,
            question=str(pending.case.question or ""),
            evidence_snippets=list(pending.evidence_snips),
            entity_hints=list(pending.entity_hints),
            max_items=limits.hardcases_per_failed,
            temperature=limits.llm_temperature,
        )
        scope = _build_search_scope(
            tenant_id=tenant_id,
            account_id=account_id,
            limits=limits,
            scope_doc_uuids=pending.scope_doc_uuids,
        )
        await _append_hardcase_runs(
            searcher,
            scope=scope,
            evidence_set=pending.evidence_set,
            k=limits.k,
            target=target,
            hardcases=hardcases,
            state=state,
        )


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / max(1, len(values)))


def _build_summary(
    *,
    limits: _DiagnosticsLimits,
    total: int,
    cases: Sequence[RagasRegressionCase],
    state: _DiagnosticsRunState,
) -> KGSearchDiagnosticsSummary:
    return KGSearchDiagnosticsSummary(
        dataset_id=limits.dataset_id,
        cases_total=int(total),
        cases_evaluated=int(len(cases)),
        hardcases_generated=int(state.hardcases_generated),
        baseline_hit_rate=round(_mean(state.baseline_hits), 4),
        baseline_mrr=round(_mean(state.baseline_mrrs), 4),
        baseline_recall=round(_mean(state.baseline_recalls), 4),
        baseline_ndcg=round(_mean(state.baseline_ndcgs), 4),
        baseline_map=round(_mean(state.baseline_maps), 4),
        hardcase_hit_rate=(round(_mean(state.hardcase_hits), 4) if state.hardcase_hits else None),
        hardcase_mrr=(round(_mean(state.hardcase_mrrs), 4) if state.hardcase_mrrs else None),
        hardcase_recall=(round(_mean(state.hardcase_recalls), 4) if state.hardcase_recalls else None),
        hardcase_ndcg=(round(_mean(state.hardcase_ndcgs), 4) if state.hardcase_ndcgs else None),
        hardcase_map=(round(_mean(state.hardcase_maps), 4) if state.hardcase_maps else None),
        failure_breakdown=dict(
            sorted(
                state.failure_breakdown.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        preflight=state.preflight,
    )


async def run_kg_search_diagnostics(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    req: KGSearchDiagnosticsRequest,
) -> KGSearchDiagnosticsResponse:
    """
    Compute KG search diagnostics for a dataset-scoped regression suite.

    This is an on-demand evaluation, so it must be safe-by-default:
    - bounded case count
    - bounded hardcase generation
    - bounded preflight extraction concurrency
    """
    limits = _normalize_limits(req)
    total, cases = _load_cases(
        db,
        tenant_id=tenant_id,
        dataset_id=limits.dataset_id,
        req=req,
        max_cases=limits.max_cases,
    )
    state = _DiagnosticsRunState(preflight=_new_preflight_state(enabled=bool(req.auto_extract_kg)))
    await _run_preflight_extraction(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        cases=cases,
        limits=limits,
        preflight=state.preflight,
    )

    searcher = KGSearcher()
    for case in cases:
        evaluation = await _evaluate_case(
            searcher,
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            limits=limits,
            case=case,
        )
        state.items_out.append(evaluation.item)
        state.record_baseline(evaluation.baseline.metrics)
        state.record_failure(evaluation.item.attribution.primary_cause)

        if _should_generate_deterministic_hardcases(limits, state, evaluation):
            await _run_deterministic_hardcases_for_case(
                searcher,
                db=db,
                tenant_id=tenant_id,
                limits=limits,
                state=state,
                evaluation=evaluation,
            )

        _queue_llm_hardcase_case(
            db,
            state=state,
            limits=limits,
            evaluation=evaluation,
        )

    await _run_llm_hardcases(
        searcher,
        tenant_id=tenant_id,
        account_id=account_id,
        limits=limits,
        state=state,
    )
    summary = _build_summary(limits=limits, total=total, cases=cases, state=state)
    return KGSearchDiagnosticsResponse(summary=summary, items=state.items_out)


__all__ = ["run_kg_search_diagnostics"]
