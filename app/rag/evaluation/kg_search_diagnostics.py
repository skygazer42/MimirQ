"""
Dynamic OneEval-style diagnostics for KG search.

Seed source: RAGAS regression cases (question + human-verified evidence chunk ids).

This module intentionally avoids adding new tables: it computes an on-demand report
that helps drive iterative improvements to:
- KG extraction quality (events/entities/relations/skills)
- KG search quality (recall/expand/rerank)

Optional persistence (compact run snapshots) is handled at the API layer.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable, Sequence
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

    # 1) Entities linked to the ground-truth events (stable ordering by weight desc, then name asc).
    ent_rows = (
        db.query(
            KgEntity.id,
            KgEntity.name,
            KgEntity.type,
            func.max(KgEventEntity.weight).label("w"),
        )
        .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
        .filter(KgEntity.tenant_id == tenant_id, KgEventEntity.event_id.in_(ev_ids))
        .group_by(KgEntity.id, KgEntity.name, KgEntity.type)
        .order_by(func.max(KgEventEntity.weight).desc(), KgEntity.name.asc())
        .limit(80)
        .all()
    )
    ent_ids = [r[0] for r in ent_rows if r and r[0] is not None]
    ent_names = [r[1] for r in ent_rows if r and r[1]]

    skill_names = [r[1] for r in ent_rows if r and str(r[2] or "").strip() == "Skill" and r[1]]
    skill_names = _dedupe_strs(skill_names, limit=20)

    # 2) Alias pairs from relation edges around those entities.
    alias_pairs: list[tuple[str, str]] = []
    if ent_ids:
        try:
            from sqlalchemy.orm import aliased

            subj = aliased(KgEntity)
            obj = aliased(KgEntity)
            rel_rows = (
                db.query(
                    KgRelation.confidence,
                    subj.name,
                    obj.name,
                )
                .join(subj, subj.id == KgRelation.subject_entity_id)
                .join(obj, obj.id == KgRelation.object_entity_id)
                .filter(
                    KgRelation.tenant_id == tenant_id,
                    KgRelation.predicate.in_(["alias_of", "same_as"]),
                    or_(KgRelation.subject_entity_id.in_(ent_ids), KgRelation.object_entity_id.in_(ent_ids)),
                )
                .order_by(KgRelation.confidence.desc(), subj.name.asc(), obj.name.asc())
                .limit(60)
                .all()
            )
            for _conf, a, b in rel_rows:
                a_s = _collapse_ws(a)
                b_s = _collapse_ws(b)
                if a_s and b_s and a_s.casefold() != b_s.casefold():
                    alias_pairs.append((a_s, b_s))
        except Exception:
            alias_pairs = []

    # Fallback: infer alias pairs from trailing parentheticals in entity surfaces.
    if not alias_pairs and ent_names:
        try:
            from app.rag.kg.extraction.alias import choose_alias_direction, split_trailing_parenthetical_alias

            for name in ent_names:
                split = split_trailing_parenthetical_alias(str(name or ""))
                if not split:
                    continue
                head, tail = split
                direction = choose_alias_direction(head, tail)
                if not direction:
                    continue
                alias_surface, canonical_surface = direction
                a_s = _collapse_ws(alias_surface)
                b_s = _collapse_ws(canonical_surface)
                if a_s and b_s and a_s.casefold() != b_s.casefold():
                    alias_pairs.append((a_s, b_s))
        except Exception as exc:
            logger.debug(_KG_DIAGNOSTICS_FALLBACK_LOG_MESSAGE, exc)

    # 3) Tags/categories for the skills (Skill -> belong_to -> Tag/Category).
    tags: list[str] = []
    if ent_ids and skill_names:
        # Map skill names back to ids via the collected ent_rows to avoid extra queries.
        skill_ids = [r[0] for r in ent_rows if r and str(r[2] or "").strip() == "Skill" and r[0] is not None]
        skill_ids = list(dict.fromkeys(skill_ids))[:50]
        if skill_ids:
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
                tags = [name for _conf, name in tag_rows if name]
            except Exception:
                tags = []

    tags = _dedupe_strs(tags, limit=40)
    alias_pairs = list(dict.fromkeys(alias_pairs))[:60]

    return alias_pairs, skill_names, tags


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
    ds_id = UUID(str(req.dataset_id))

    max_cases = max(1, min(int(req.max_cases or 0), 200))
    k = max(1, min(int(req.k or 0), 50))
    diag_max_results = max(k, 30)

    hardcase_mode = str(req.hardcase_mode or "llm").strip().lower()
    hardcases_per_failed = max(0, min(int(req.hardcases_per_failed_case or 0), 20))
    max_failed_for_hardcase = max(0, min(int(req.max_failed_cases_for_hardcase or 0), 200))

    # --------------------------
    # Load regression cases
    # --------------------------
    query = db.query(RagasRegressionCase).filter(
        RagasRegressionCase.tenant_id == tenant_id,
        RagasRegressionCase.dataset_id == ds_id,
    )

    if req.case_ids:
        want = _coerce_uuid_list(req.case_ids)
        rows = (
            db.query(RagasRegressionCase.id, RagasRegressionCase.dataset_id)
            .filter(RagasRegressionCase.tenant_id == tenant_id, RagasRegressionCase.id.in_(want))
            .all()
        )
        validate_case_ids_belong_to_dataset(dataset_id=ds_id, case_ids=want, rows=rows)
        query = query.filter(RagasRegressionCase.id.in_(want))

    total = int(query.count())
    cases: list[RagasRegressionCase] = (
        query.order_by(RagasRegressionCase.updated_at.desc()).limit(max_cases).all()
    )

    # --------------------------
    # Preflight: auto-extract KG
    # --------------------------
    preflight: dict[str, Any] = {
        "enabled": bool(req.auto_extract_kg),
        "documents_total": 0,
        "documents_missing_kg": 0,
        "documents_extracted_ok": 0,
        "documents_extracted_failed": 0,
        "elapsed_sec": 0.0,
        "errors": [],
    }

    extract_skills_override = req.extract_skills
    extract_relations_override = req.extract_relations

    if bool(req.auto_extract_kg) and cases:
        t0 = time.perf_counter()
        all_doc_ids: list[str] = []
        for c in cases:
            _chunk_ids, doc_ids, _snips = _extract_evidence_fields(c)
            all_doc_ids.extend(doc_ids)

        doc_uuids = _coerce_uuid_list(all_doc_ids)
        preflight["documents_total"] = int(len(doc_uuids))

        if doc_uuids:
            docs = (
                db.query(DBDocument.id, DBDocument.doc_metadata)
                .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(doc_uuids))
                .all()
            )
            missing: list[UUID] = []
            for doc_id, meta in docs:
                md = meta if isinstance(meta, dict) else {}
                kg_extracted_at = str(md.get("kg_extracted_at") or "").strip()
                if not kg_extracted_at:
                    missing.append(UUID(str(doc_id)))
            preflight["documents_missing_kg"] = int(len(missing))

            if missing:
                # Conservative concurrency: extraction can involve LLM + embeddings.
                max_conc = max(1, min(int(getattr(settings, "KG_EXTRACT_MAX_CONCURRENCY", 3) or 3), 5))
                sem = asyncio.Semaphore(max_conc)

                async def _one(doc_id: UUID) -> None:
                    async with sem:
                        ok, err, ev_count = await _ensure_kg_extracted_for_document(
                            db=db,
                            tenant_id=tenant_id,
                            account_id=account_id,
                            document_id=doc_id,
                            extract_skills=extract_skills_override,
                            extract_relations=extract_relations_override,
                        )
                        if ok:
                            preflight["documents_extracted_ok"] = int(preflight.get("documents_extracted_ok", 0) or 0) + 1
                        else:
                            preflight["documents_extracted_failed"] = int(preflight.get("documents_extracted_failed", 0) or 0) + 1
                            if err:
                                (preflight["errors"] if isinstance(preflight.get("errors"), list) else []).append(
                                    {"document_id": str(doc_id), "error": str(err)[:200], "event_count": int(ev_count)}
                                )

                await asyncio.gather(*[_one(doc_id) for doc_id in missing])

                # Critical: end the current transaction so subsequent reads can see
                # committed KG rows from the extraction engine's separate session.
                try:
                    db.rollback()
                except Exception as exc:
                    logger.debug(_KG_DIAGNOSTICS_FALLBACK_LOG_MESSAGE, exc)

        preflight["elapsed_sec"] = round(float(time.perf_counter() - t0), 3)

    # --------------------------
    # Evaluate baseline + hardcases
    # --------------------------
    searcher = KGSearcher()
    items_out: list[KGSearchDiagnosticsItem] = []

    failure_breakdown: dict[str, int] = {}
    baseline_hits: list[float] = []
    baseline_mrrs: list[float] = []
    baseline_recalls: list[float] = []
    baseline_ndcgs: list[float] = []
    baseline_maps: list[float] = []

    hardcase_hits: list[float] = []
    hardcase_mrrs: list[float] = []
    hardcase_recalls: list[float] = []
    hardcase_ndcgs: list[float] = []
    hardcase_maps: list[float] = []
    hardcases_generated = 0

    failed_for_hardcase: list[tuple[RagasRegressionCase, dict[str, Any]]] = []
    deterministic_failed_cases_used = 0

    for case in cases:
        question = str(case.question or "").strip()
        chunk_ids, _doc_ids, evidence_snips = _extract_evidence_fields(case)
        evidence_set = {str(x).strip() for x in chunk_ids if str(x).strip()}

        gt_event_ids = _resolve_ground_truth_event_ids(db, tenant_id=tenant_id, evidence_chunk_ids=chunk_ids)
        gt_has_skill = _ground_truth_has_skill(db, ground_truth_event_ids=gt_event_ids)

        # Respect per-case scope when provided (document_ids overrides dataset scope).
        scope_doc_ids_raw = getattr(case, "document_ids", None) or []
        scope_doc_uuids = _coerce_uuid_list(scope_doc_ids_raw)

        try:
            cfg = SearchConfig(
                query=question,
                tenant_id=tenant_id,
                dataset_id=(None if scope_doc_uuids else ds_id),
                account_id=account_id,
                document_ids=scope_doc_uuids or None,
            )
            cfg.rerank.max_results = int(diag_max_results)
            raw = await searcher.search(cfg)
            raw_events = list((raw or {}).get("events") or [])
            raw_entities = list((raw or {}).get("entities") or [])
            raw_clues = list((raw or {}).get("clues") or [])
            raw_stats = dict((raw or {}).get("stats") or {})
            err = None
        except Exception as exc:  # noqa: BLE001
            raw_events = []
            raw_entities = []
            raw_clues = []
            raw_stats = {}
            err = str(exc)[:200]

        # Compute metrics @k.
        metrics_dict = compute_kg_hit_metrics(events=raw_events, evidence_chunk_ids=evidence_set, k=k)
        metrics = KGSearchRunMetrics(**metrics_dict)

        clue_counts = _summarize_clues(raw_clues)
        first_hit = _first_hit_rank(raw_events, evidence_set)

        selected_has_skill = any(
            isinstance(e, dict) and str(e.get("type") or "").strip() in {"Skill", "SkillTag", "SkillCategory"}
            for e in raw_entities
        )
        relation_debug = None
        try:
            relation_debug = raw_stats.get("relation_expansion") if isinstance(raw_stats.get("relation_expansion"), dict) else None
        except Exception:
            relation_debug = None

        # --------------------------
        # Attribution ablations (bounded extra searches)
        # --------------------------
        ablations: dict[str, Any] = {}

        def _compact_relation_dbg(value: Any) -> dict[str, Any]:
            if not isinstance(value, dict):
                return {}
            keep = {}
            for k in ("enabled", "edges_fetched", "edges_used", "neighbors_selected", "neighbors_total", "min_confidence", "max_edges", "max_neighbors"):
                if k in value:
                    keep[k] = value.get(k)
            return keep

        def _delta_vs_baseline(run: dict[str, Any]) -> dict[str, Any]:
            """
            Compute metric deltas for an ablation run vs the baseline for this case.

            Notes:
            - hit_at_k is treated as an int delta (0/1).
            - first_hit_rank delta uses baseline - alt so positive means improvement (smaller rank).
            """
            if not isinstance(run, dict):
                return {}
            try:
                alt_hit = bool(run.get("hit_at_k"))
                alt_mrr = float(run.get("mrr", 0.0) or 0.0)
                alt_recall = float(run.get("recall", 0.0) or 0.0)
            except Exception:
                return {}

            base_hit = bool(metrics.hit_at_k)
            base_mrr = float(metrics.mrr)
            base_recall = float(metrics.recall)

            base_rank = first_hit
            alt_rank = run.get("first_hit_rank")
            try:
                alt_rank_i = int(alt_rank) if alt_rank is not None else None
            except Exception:
                alt_rank_i = None

            rank_delta = None
            if base_rank is not None and alt_rank_i is not None:
                rank_delta = int(base_rank) - int(alt_rank_i)

            return {
                "delta_hit_at_k": int(alt_hit) - int(base_hit),
                "delta_mrr": round(float(alt_mrr - base_mrr), 6),
                "delta_recall": round(float(alt_recall - base_recall), 6),
                "delta_first_hit_rank": rank_delta,
            }

        async def _run_search_variant(
            *,
            query: str,
            relation_expansion_enabled: bool | None = None,
            include_skill_entities: bool = True,
            expand_enabled: bool | None = None,
            expand_max_hops: int | None = None,
            rerank_strategy: RerankStrategy | None = None,
            vector_recall_enabled: bool | None = None,
            graph_embeddings_enabled: bool | None = None,
        ) -> dict[str, Any]:
            try:
                cfg2 = SearchConfig(
                    query=str(query or ""),
                    tenant_id=tenant_id,
                    dataset_id=(None if scope_doc_uuids else ds_id),
                    account_id=account_id,
                    document_ids=scope_doc_uuids or None,
                    relation_expansion_enabled=relation_expansion_enabled,
                    vector_recall_enabled=vector_recall_enabled,
                    graph_embeddings_enabled=graph_embeddings_enabled,
                    include_skill_entities=include_skill_entities,
                )
                if rerank_strategy is not None:
                    cfg2.rerank.strategy = rerank_strategy
                if expand_enabled is not None:
                    cfg2.expand.enabled = bool(expand_enabled)
                if expand_max_hops is not None:
                    try:
                        cfg2.expand.max_hops = max(1, min(int(expand_max_hops), 5))
                    except Exception as exc:
                        logger.debug(_KG_DIAGNOSTICS_FALLBACK_LOG_MESSAGE, exc)
                cfg2.rerank.max_results = int(diag_max_results)
                raw2 = await searcher.search(cfg2)
                ev2 = list((raw2 or {}).get("events") or [])
                ent2 = list((raw2 or {}).get("entities") or [])
                clues2 = list((raw2 or {}).get("clues") or [])
                stats2 = dict((raw2 or {}).get("stats") or {})
                err2 = None
            except Exception as exc:  # noqa: BLE001
                ev2 = []
                ent2 = []
                clues2 = []
                stats2 = {}
                err2 = str(exc)[:200]

            m2 = KGSearchRunMetrics(**compute_kg_hit_metrics(events=ev2, evidence_chunk_ids=evidence_set, k=k))
            first2 = _first_hit_rank(ev2, evidence_set)
            clues_sum2 = _summarize_clues(clues2)
            selected_has_skill2 = any(
                isinstance(e, dict) and str(e.get("type") or "").strip() in {"Skill", "SkillTag", "SkillCategory"}
                for e in ent2
            )
            rel_dbg2 = None
            try:
                rel_dbg2 = stats2.get("relation_expansion") if isinstance(stats2.get("relation_expansion"), dict) else None
            except Exception:
                rel_dbg2 = None

            return {
                "hit_at_k": bool(m2.hit_at_k),
                "mrr": float(m2.mrr),
                "recall": float(m2.recall),
                "first_hit_rank": int(first2) if first2 is not None else None,
                "returned_events": int(len(ev2)),
                "selected_entities": int(len(ent2)),
                "selected_has_skill": bool(selected_has_skill2),
                "clues": clues_sum2,
                "relation_expansion": _compact_relation_dbg(rel_dbg2),
                "error": err2,
            }

        # Run ablations only on baseline failures with GT present (and only if baseline didn't error).
        ablation_override: str | None = None
        if (not metrics.hit_at_k) and int(len(gt_event_ids)) > 0 and err is None:
            # 1) Rerank strategy toggle.
            try:
                base = cfg.rerank.strategy
                alt = RerankStrategy.RRF if base == RerankStrategy.PAGERANK else RerankStrategy.PAGERANK
                out_alt = await _run_search_variant(query=question, rerank_strategy=alt)
                ablations["rerank_strategy"] = {
                    "baseline": str(base),
                    "alt": str(alt),
                    "alt_run": out_alt,
                    "delta": _delta_vs_baseline(out_alt),
                }
                if bool(out_alt.get("hit_at_k")):
                    ablation_override = "rerank_cutoff"
            except Exception as exc:
                logger.debug(_KG_DIAGNOSTICS_FALLBACK_LOG_MESSAGE, exc)

            # 2) Relation expansion toggle.
            try:
                base_rel = bool((relation_debug or {}).get("enabled"))
                alt_rel = not base_rel
                out_rel = await _run_search_variant(query=question, relation_expansion_enabled=alt_rel)
                ablations["relation_expansion"] = {
                    "baseline_enabled": bool(base_rel),
                    "alt_enabled": bool(alt_rel),
                    "alt_run": out_rel,
                    "delta": _delta_vs_baseline(out_rel),
                }
                if ablation_override is None and bool(out_rel.get("hit_at_k")):
                    ablation_override = "relation"
            except Exception as exc:
                logger.debug(_KG_DIAGNOSTICS_FALLBACK_LOG_MESSAGE, exc)

            # 3) Path search (multi-hop expand) off.
            try:
                base_expand = bool(getattr(cfg.expand, "enabled", True))
                alt_expand = not base_expand
                out_expand = await _run_search_variant(query=question, expand_enabled=alt_expand)
                ablations["path_search"] = {
                    "baseline_enabled": bool(base_expand),
                    "alt_enabled": bool(alt_expand),
                    "alt_run": out_expand,
                    "delta": _delta_vs_baseline(out_expand),
                }
                if ablation_override is None and bool(out_expand.get("hit_at_k")):
                    ablation_override = "path"
            except Exception as exc:
                logger.debug(_KG_DIAGNOSTICS_FALLBACK_LOG_MESSAGE, exc)

            # 4) Skill nodes off.
            try:
                out_skill_off = await _run_search_variant(query=question, include_skill_entities=False)
                ablations["skill_nodes"] = {
                    "alt_enabled": False,
                    "alt_run": out_skill_off,
                    "delta": _delta_vs_baseline(out_skill_off),
                }
                if ablation_override is None and bool(out_skill_off.get("hit_at_k")):
                    ablation_override = "skill"
            except Exception as exc:
                logger.debug(_KG_DIAGNOSTICS_FALLBACK_LOG_MESSAGE, exc)

        primary_cause = _pick_primary_cause(
            gt_event_count=int(len(gt_event_ids)),
            metrics=metrics,
            first_hit_rank=first_hit,
            relation_debug=relation_debug,
            ground_truth_has_skill=gt_has_skill,
            selected_has_skill=bool(selected_has_skill),
            clue_counts=clue_counts,
            selected_entities=int(len(raw_entities)),
            returned_events=int(len(raw_events)),
        )
        if ablation_override is not None:
            primary_cause = str(ablation_override)

        if primary_cause != "ok":
            failure_breakdown[primary_cause] = int(failure_breakdown.get(primary_cause, 0) or 0) + 1

        signals: dict[str, Any] = {
            "ground_truth_event_count": int(len(gt_event_ids)),
            "ground_truth_has_skill": bool(gt_has_skill),
            "selected_has_skill": bool(selected_has_skill),
            "first_hit_rank": int(first_hit) if first_hit is not None else None,
            "returned_events": int(len(raw_events)),
            "selected_entities": int(len(raw_entities)),
            "clues": clue_counts,
            "relation_expansion": relation_debug or {},
        }
        if ablations:
            signals["ablations"] = ablations
        # Drop None values to keep payload small/stable.
        signals = {k: v for k, v in signals.items() if v is not None}

        baseline_run = KGSearchRunResult(
            query=question,
            events=[_event_out(e) for e in raw_events if isinstance(e, dict)],
            entities=[_entity_out(e) for e in raw_entities if isinstance(e, dict)],
            clues=[c for c in raw_clues if isinstance(c, dict)],
            stats=raw_stats,
            metrics=metrics,
            error=err,
        )

        item = KGSearchDiagnosticsItem(
            case_id=case.id,
            question=question,
            tags=list(case.tags or []),
            evidence_chunk_ids=sorted(evidence_set),
            ground_truth_event_ids=list(gt_event_ids),
            baseline=baseline_run,
            hardcases=[],
            attribution=KGEvalAttribution(primary_cause=primary_cause, signals=signals),
        )

        items_out.append(item)
        baseline_hits.append(1.0 if metrics.hit_at_k else 0.0)
        baseline_mrrs.append(float(metrics.mrr))
        baseline_recalls.append(float(metrics.recall))
        baseline_ndcgs.append(float(metrics.ndcg))
        baseline_maps.append(float(metrics.map))

        if (
            hardcase_mode == "deterministic"
            and not metrics.hit_at_k
            and int(len(gt_event_ids)) > 0
            and hardcases_per_failed > 0
            and int(deterministic_failed_cases_used) < int(max_failed_for_hardcase)
        ):
            alias_pairs, skills, tags = _deterministic_hardcase_candidates(
                db,
                tenant_id=tenant_id,
                ground_truth_event_ids=gt_event_ids,
            )
            hardcases = generate_hardcases_deterministic(
                question=question,
                alias_pairs=alias_pairs,
                skills=skills,
                tags=tags,
                max_items=hardcases_per_failed,
            )
            if hardcases:
                deterministic_failed_cases_used += 1
            for hc in hardcases:
                hardcases_generated += 1
                try:
                    cfg = SearchConfig(
                        query=str(hc.question),
                        tenant_id=tenant_id,
                        dataset_id=(None if scope_doc_uuids else ds_id),
                        account_id=account_id,
                        document_ids=scope_doc_uuids or None,
                    )
                    cfg.rerank.max_results = int(diag_max_results)
                    raw = await searcher.search(cfg)
                    raw_events = list((raw or {}).get("events") or [])
                    raw_entities = list((raw or {}).get("entities") or [])
                    raw_clues = list((raw or {}).get("clues") or [])
                    raw_stats = dict((raw or {}).get("stats") or {})
                    err = None
                except Exception as exc:  # noqa: BLE001
                    raw_events = []
                    raw_entities = []
                    raw_clues = []
                    raw_stats = {}
                    err = str(exc)[:200]

                metrics_dict = compute_kg_hit_metrics(events=raw_events, evidence_chunk_ids=set(evidence_set), k=k)
                metrics2 = KGSearchRunMetrics(**metrics_dict)

                hardcase_hits.append(1.0 if metrics2.hit_at_k else 0.0)
                hardcase_mrrs.append(float(metrics2.mrr))
                hardcase_recalls.append(float(metrics2.recall))
                hardcase_ndcgs.append(float(metrics2.ndcg))
                hardcase_maps.append(float(metrics2.map))

                run = KGSearchRunResult(
                    query=str(hc.question),
                    events=[_event_out(e) for e in raw_events if isinstance(e, dict)],
                    entities=[_entity_out(e) for e in raw_entities if isinstance(e, dict)],
                    clues=[c for c in raw_clues if isinstance(c, dict)],
                    stats=raw_stats,
                    metrics=metrics2,
                    error=err,
                )
                item.hardcases.append(KGHardcaseOut(kind=hc.kind, question=hc.question, rationale=hc.rationale, run=run))

        if (
            hardcase_mode == "llm"
            and not metrics.hit_at_k
            and int(len(gt_event_ids)) > 0
            and hardcases_per_failed > 0
            and len(failed_for_hardcase) < max_failed_for_hardcase
        ):
            failed_for_hardcase.append(
                (
                    case,
                    {
                        "evidence_snips": evidence_snips,
                        "entity_hints": _entity_hints_for_events(db, ground_truth_event_ids=gt_event_ids, limit=12),
                        "scope_doc_uuids": scope_doc_uuids,
                        "evidence_set": evidence_set,
                    },
                )
            )

    # Hardcase generation + evaluation (LLM mode only for MVP).
    if hardcase_mode == "llm" and failed_for_hardcase and hardcases_per_failed > 0:
        try:
            from app.rag.llm.factory import create_llm_client

            llm_client = await create_llm_client(scenario="kg_diagnostics")
        except Exception as exc:  # noqa: BLE001
            logger.warning("KG diagnostics hardcase LLM unavailable: %s", str(exc)[:200])
            llm_client = None

        if llm_client is not None:
            for case, ctx in failed_for_hardcase:
                case_id = case.id
                # Find the already-emitted item and attach hardcases.
                target = next((it for it in items_out if it.case_id == case_id), None)
                if target is None:
                    continue

                evidence_snips = ctx.get("evidence_snips") or []
                entity_hints = ctx.get("entity_hints") or []
                scope_doc_uuids = ctx.get("scope_doc_uuids") or []
                evidence_set = ctx.get("evidence_set") or set()

                hardcases = await generate_hardcases_llm(
                    llm_client=llm_client,
                    question=str(case.question or ""),
                    evidence_snippets=list(evidence_snips),
                    entity_hints=list(entity_hints),
                    max_items=hardcases_per_failed,
                    temperature=float(req.llm_temperature or 0.2),
                )

                for hc in hardcases:
                    hardcases_generated += 1
                    try:
                        cfg = SearchConfig(
                            query=str(hc.question),
                            tenant_id=tenant_id,
                            dataset_id=(None if scope_doc_uuids else ds_id),
                            account_id=account_id,
                            document_ids=scope_doc_uuids or None,
                        )
                        cfg.rerank.max_results = int(diag_max_results)
                        raw = await searcher.search(cfg)
                        raw_events = list((raw or {}).get("events") or [])
                        raw_entities = list((raw or {}).get("entities") or [])
                        raw_clues = list((raw or {}).get("clues") or [])
                        raw_stats = dict((raw or {}).get("stats") or {})
                        err = None
                    except Exception as exc:  # noqa: BLE001
                        raw_events = []
                        raw_entities = []
                        raw_clues = []
                        raw_stats = {}
                        err = str(exc)[:200]

                    metrics_dict = compute_kg_hit_metrics(events=raw_events, evidence_chunk_ids=set(evidence_set), k=k)
                    metrics = KGSearchRunMetrics(**metrics_dict)

                    hardcase_hits.append(1.0 if metrics.hit_at_k else 0.0)
                    hardcase_mrrs.append(float(metrics.mrr))
                    hardcase_recalls.append(float(metrics.recall))
                    hardcase_ndcgs.append(float(metrics.ndcg))
                    hardcase_maps.append(float(metrics.map))

                    run = KGSearchRunResult(
                        query=str(hc.question),
                        events=[_event_out(e) for e in raw_events if isinstance(e, dict)],
                        entities=[_entity_out(e) for e in raw_entities if isinstance(e, dict)],
                        clues=[c for c in raw_clues if isinstance(c, dict)],
                        stats=raw_stats,
                        metrics=metrics,
                        error=err,
                    )
                    target.hardcases.append(
                        KGHardcaseOut(kind=hc.kind, question=hc.question, rationale=hc.rationale, run=run)
                    )

    def _mean(vals: list[float]) -> float:
        if not vals:
            return 0.0
        return float(sum(vals) / max(1, len(vals)))

    summary = KGSearchDiagnosticsSummary(
        dataset_id=ds_id,
        cases_total=int(total),
        cases_evaluated=int(len(cases)),
        hardcases_generated=int(hardcases_generated),
        baseline_hit_rate=round(_mean(baseline_hits), 4),
        baseline_mrr=round(_mean(baseline_mrrs), 4),
        baseline_recall=round(_mean(baseline_recalls), 4),
        baseline_ndcg=round(_mean(baseline_ndcgs), 4),
        baseline_map=round(_mean(baseline_maps), 4),
        hardcase_hit_rate=(round(_mean(hardcase_hits), 4) if hardcase_hits else None),
        hardcase_mrr=(round(_mean(hardcase_mrrs), 4) if hardcase_mrrs else None),
        hardcase_recall=(round(_mean(hardcase_recalls), 4) if hardcase_recalls else None),
        hardcase_ndcg=(round(_mean(hardcase_ndcgs), 4) if hardcase_ndcgs else None),
        hardcase_map=(round(_mean(hardcase_maps), 4) if hardcase_maps else None),
        failure_breakdown=dict(sorted(failure_breakdown.items(), key=lambda x: (-x[1], x[0]))),
        preflight=preflight,
    )

    return KGSearchDiagnosticsResponse(summary=summary, items=items_out)


__all__ = ["run_kg_search_diagnostics"]
