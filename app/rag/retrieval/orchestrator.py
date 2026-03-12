"""
Retrieval orchestration (evidence-first).

This module provides a *synchronous* retrieval runner that:
- rewrites/expands a query (optional, bounded)
- executes retrieval across one or more query variants
- fuses results and builds citation payloads
- computes abstain/guardrail signals
- emits a bounded, structured query_debug payload for downstream diagnostics

It is intentionally usable without the LangGraph orchestration layer.
"""

from __future__ import annotations

import concurrent.futures
import json
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from app.core.utils import parse_csv
from app.query.normalize import normalize_query
from app.rag.core.citations import build_citations_from_docs
from app.rag.core.conversation import format_history_text
from app.rag.core.hashing import stable_hash
from app.rag.core.query_rewrite_strategy import (
    build_query_rewrite_strategy_spec,
    get_query_rewrite_prompt_template,
)
from app.rag.core.retrieval_config_fingerprint import build_retrieval_config_fingerprint
from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides, is_recall_first_profile
from app.rag.core.text import (
    build_abstain_followup,
    guess_retrieval_mode,
    normalize_retrieval_mode,
    parse_json_from_text,
    should_rewrite_query,
)
from app.rag.engine import get_rag_engine
from app.rag.kg.pipeline import kg_search
from app.rag.policy.intent_router import route_retrieval_preset
from app.rag.policy.query_expansion import build_clause_fastlane_queries
from app.rag.query_expansion import generate_alias_queries
from app.rag.rerank_result_cache import (
    build_evidence_post_rerank_cache_key,
    fingerprint_rerank_candidates,
    get_cached_evidence_post_rerank_result,
    get_evidence_post_rerank_cache_backend,
    set_cached_evidence_post_rerank_result,
)
from app.rag.reranker.factory import describe_reranker_provider, get_reranker
from app.rag.reranker.types import RerankCandidate
from app.rag.retrieval.contract import resolve_retrieval_contract_policy
from app.rag.retriever import hybrid_retriever
from app.services.chunk_quality_scoring import summarize_retrieved_chunk_quality
from app.services.corpus_cache_tokens import resolve_corpus_cache_token
from app.services.hardcase_discovery_service import build_parse_risk_hardcase_candidate


def _build_history_text(history: Optional[List[Dict[str, str]]]) -> str:
    """Compress history to readable text, keep only within window."""
    return format_history_text(history, window=settings.CHAT_HISTORY_WINDOW)


def _sanitize_retriever_debug(dbg: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """
    Shrink retriever debug payloads for API responses / metrics.

    Rationale:
    - Debug payloads may include large generated queries (HyDE) and verbose internal stats.
    - Evidence API returns metrics to downstream systems; keep payloads bounded and avoid leaking scope identifiers.
    """
    if not isinstance(dbg, dict) or not dbg:
        return None

    out: Dict[str, Any] = {}
    for k in (
        "requested_k",
        "search_k",
        "fetch_k",
        "overfetch_enabled",
        "overfetch_multiplier",
        "overfetch_cap_k",
        "milvus_doc_id_pushdown_skipped",
        "milvus_expr_max_doc_ids",
    ):
        v = dbg.get(k)
        if v is not None:
            out[k] = v

    qn = dbg.get("query_normalization")
    qn = qn if isinstance(qn, dict) else {}
    normalized = qn.get("normalized") if isinstance(qn.get("normalized"), str) else ""
    applied_rules = qn.get("applied_rules") if isinstance(qn.get("applied_rules"), list) else []
    if normalized or applied_rules:
        out["query_normalization"] = {
            "applied_rules": [str(x) for x in applied_rules if x is not None][:20],
            "original_chars": len(str(qn.get("original") or "")),
            "normalized_chars": len(str(normalized or "")),
        }

    # Doc/page diversity caps (PII-safe): expose only bounded numeric counters/settings.
    div = dbg.get("diversity")
    if isinstance(div, dict):
        div_out: Dict[str, int] = {}
        for k in (
            "max_chunks_per_doc",
            "max_chunks_per_page",
            "min_distinct_docs",
            "pre_unique_docs",
            "post_unique_docs",
            "pre_unique_pages",
            "post_unique_pages",
            "moved_out",
            "moved_in",
        ):
            if k not in div:
                continue
            try:
                n = int(div.get(k))  # noqa: PERF401 - tiny dict; clarity > micro-opt
            except Exception:
                continue
            # Defense-in-depth: keep counters sane/bounded for downstream UI.
            if n < 0:
                n = 0
            if n > 1_000_000_000:
                n = 1_000_000_000
            div_out[k] = int(n)
        if div_out:
            out["diversity"] = div_out

    for key in ("enrich_pass1", "enrich_pass2"):
        ep = dbg.get(key)
        if not isinstance(ep, dict):
            continue
        out[key] = {
            "input_results": int(ep.get("input_results") or 0),
            "output_results": int(ep.get("output_results") or 0),
            "filtered_orphaned": int(ep.get("filtered_orphaned") or 0),
            "filtered_acl": int(ep.get("filtered_acl") or 0),
            "filtered_dataset": int(ep.get("filtered_dataset") or 0),
            "filtered_not_ready": int(ep.get("filtered_not_ready") or 0),
            "filtered_embedding_space": int(ep.get("filtered_embedding_space") or 0),
            "filtered_pipeline_version": int(ep.get("filtered_pipeline_version") or 0),
            "filtered_metadata_filter": int(ep.get("filtered_metadata_filter") or 0),
        }
        for k2 in ("metadata_filter_blocked", "metadata_filter_matched"):
            v2 = ep.get(k2)
            if v2 is not None:
                try:
                    out[key][k2] = int(v2 or 0)
                except Exception:
                    continue

        mf = ep.get("metadata_filter")
        if isinstance(mf, dict):
            keys_count = mf.get("keys_count")
            try:
                keys_count = int(keys_count) if keys_count is not None else None
            except Exception:
                keys_count = None

            keys_sample_raw = mf.get("keys_sample")
            keys_sample: list[str] = []
            if isinstance(keys_sample_raw, list):
                for x in keys_sample_raw:
                    if isinstance(x, str) and x.strip():
                        keys_sample.append(x.strip())
                    if len(keys_sample) >= 10:
                        break

            ops_raw = mf.get("ops")
            ops: dict[str, int] = {}
            if isinstance(ops_raw, dict):
                for ok, ov in ops_raw.items():
                    if not isinstance(ok, str) or not ok.startswith("$"):
                        continue
                    try:
                        ops[ok] = int(ov or 0)
                    except Exception:
                        continue
                    if len(ops) >= 30:
                        break
                ops = dict(sorted(ops.items(), key=lambda x: x[0]))

            out[key]["metadata_filter"] = {
                "keys_count": keys_count,
                "keys_sample": keys_sample,
                "ops": ops,
            }

    timing = dbg.get("timing")
    if isinstance(timing, dict):
        out["timing"] = {
            "vector_ms": float(timing.get("vector_ms") or 0.0),
            "bm25_ms": float(timing.get("bm25_ms") or 0.0),
            "fusion_ms": float(timing.get("fusion_ms") or 0.0),
        }

    counts = dbg.get("counts")
    if isinstance(counts, dict):
        out["counts"] = {
            "vector_candidates": int(counts.get("vector_candidates") or 0),
            "bm25_candidates": int(counts.get("bm25_candidates") or 0),
        }

    gp = dbg.get("governance_policy")
    if isinstance(gp, dict):
        gp_out: dict[str, Any] = {}
        for k in (
            "enabled",
            "prefer_authority",
            "prefer_latest",
            "filter_superseded",
            "reordered",
        ):
            if k in gp:
                gp_out[k] = bool(gp.get(k))
        for k in (
            "input_results",
            "output_results",
            "candidate_docs",
            "filtered_superseded",
        ):
            if k in gp:
                try:
                    gp_out[k] = int(gp.get(k) or 0)
                except Exception:
                    continue
        for k in ("avg_boost", "max_boost"):
            if k in gp:
                try:
                    gp_out[k] = float(gp.get(k) or 0.0)
                except Exception:
                    continue
        if gp.get("skip_reason") is not None:
            sr = str(gp.get("skip_reason") or "").strip()
            if sr:
                gp_out["skip_reason"] = sr[:80]
        if gp_out:
            out["governance_policy"] = gp_out

    channels = dbg.get("channels")
    if isinstance(channels, dict):
        out["channels"] = channels

    return out or None


def _is_recall_profile(profile: str | None) -> bool:
    return is_recall_first_profile(profile)


def _coverage_proxy_from_citations(citations: Any) -> dict[str, Any] | None:
    """
    Compute a lightweight, PII-safe coverage proxy from citations.

    This is intentionally *not* a semantic quality metric; it is used for:
    - quick diagnosis (e.g., "all citations come from 1 doc")
    - low-cost gating/alerts
    """
    if not isinstance(citations, list) or not citations:
        return None

    doc_ids: list[str] = []
    pipeline_keys: list[str] = []
    roles: list[str] = []

    for c in citations:
        if not isinstance(c, dict):
            continue
        did = c.get("document_id")
        if did is not None and str(did).strip():
            doc_ids.append(str(did).strip())

        pk = c.get("doc_pipeline_key") or c.get("pipeline_hash")
        if pk is not None and str(pk).strip():
            pipeline_keys.append(str(pk).strip())

        role = c.get("retrieval_role")
        if role is not None and str(role).strip():
            roles.append(str(role).strip().lower())

    total = len([c for c in citations if isinstance(c, dict)])
    if total <= 0:
        return None

    distinct_docs = len(set(doc_ids)) if doc_ids else 0
    distinct_pipelines = len(set(pipeline_keys)) if pipeline_keys else 0
    distinct_roles = len(set(roles)) if roles else 0

    top_doc_share: float | None = None
    if doc_ids:
        from collections import Counter  # local import: keep module import-light

        counts = Counter(doc_ids)
        if counts:
            top_doc_share = round(float(max(counts.values())) / float(len(doc_ids)), 3)

    out: dict[str, Any] = {
        "citations_total": int(total),
        "distinct_documents": int(distinct_docs),
        "distinct_pipeline_keys": int(distinct_pipelines),
        "distinct_roles": int(distinct_roles),
        "top_doc_share": top_doc_share,
    }
    return {k: v for k, v in out.items() if v is not None} or None


def _diagnose_empty_retrieval(retrieval_per_query: Any) -> dict[str, Any] | None:
    """
    Best-effort diagnosis for "no citations returned" cases.

    This is intentionally PII-safe: it only reports counters from retriever_debug.
    """
    if not isinstance(retrieval_per_query, list) or not retrieval_per_query:
        return None

    main: dict[str, Any] | None = None
    for item in retrieval_per_query:
        if isinstance(item, dict) and item.get("kind") == "main":
            main = item
            break
    if main is None:
        return None

    dbg = main.get("retriever_debug")
    if not isinstance(dbg, dict):
        return None

    ep = dbg.get("enrich_pass2")
    if not isinstance(ep, dict):
        ep = dbg.get("enrich_pass1")
    if not isinstance(ep, dict):
        return None

    signals: dict[str, int] = {}
    reason_counts: list[tuple[str, int]] = []
    for key, reason in (
        ("filtered_metadata_filter", "metadata_filter"),
        ("filtered_acl", "acl"),
        ("filtered_dataset", "dataset"),
        ("filtered_pipeline_version", "pipeline_version"),
        ("filtered_embedding_space", "embedding_space"),
        ("filtered_not_ready", "not_ready"),
        ("filtered_orphaned", "orphaned_vectors"),
    ):
        raw = ep.get(key)
        try:
            n = int(raw or 0)
        except Exception:
            n = 0
        if n > 0:
            signals[key] = int(n)
            reason_counts.append((reason, int(n)))

    if not reason_counts:
        return None

    reason_counts.sort(key=lambda x: (-x[1], x[0]))
    reasons = [r for (r, _n) in reason_counts]

    diag: dict[str, Any] = {"reasons": reasons, "signals": signals}
    for k2 in ("input_results", "output_results"):
        v2 = ep.get(k2)
        try:
            diag[k2] = int(v2 or 0) if v2 is not None else None
        except Exception:
            continue
    diag = {k: v for k, v in diag.items() if v is not None}
    return diag or None


def _extract_parse_quality_score(meta: Any) -> float | None:
    if not isinstance(meta, dict):
        return None

    candidates = [
        meta.get("doc_parse_quality_score"),
        meta.get("parse_quality_score"),
    ]
    pq = meta.get("parse_quality")
    if isinstance(pq, dict):
        candidates.append(pq.get("score"))
    elif pq is not None:
        candidates.append(pq)

    for raw in candidates:
        try:
            if raw is None:
                continue
            score = float(raw)
            if score < 0.0:
                score = 0.0
            if score > 1.0:
                score = 1.0
            return float(score)
        except Exception:
            continue
    return None


def _parse_quality_recommendation(*, low_ratio: float, considered: int) -> str | None:
    if considered <= 0:
        return "no_parse_quality_metadata"
    if low_ratio >= 0.8:
        return "high_parse_risk_reparse_documents"
    if low_ratio >= 0.5:
        return "medium_parse_risk_prioritize_low_quality_docs"
    if low_ratio >= 0.2:
        return "monitor_parse_quality_tail"
    return "parse_quality_healthy"


def _summarize_parse_quality_risk(
    docs: list[Document] | None,
    *,
    low_threshold: float,
    alert_ratio: float,
) -> dict[str, Any]:
    considered = 0
    low_count = 0
    scores: list[float] = []
    low_samples: list[dict[str, Any]] = []

    for i, d in enumerate(list(docs or [])[:50]):
        meta = d.metadata if isinstance(getattr(d, "metadata", None), dict) else {}
        score = _extract_parse_quality_score(meta)
        if score is None:
            continue
        considered += 1
        scores.append(float(score))
        if float(score) < float(low_threshold):
            low_count += 1
            if len(low_samples) < 5:
                low_samples.append(
                    {
                        "rank": int(i + 1),
                        "chunk_id": str(getattr(d, "id", None) or meta.get("chunk_id") or ""),
                        "document_id": str(meta.get("document_id") or ""),
                        "score": round(float(score), 3),
                    }
                )

    low_ratio = (float(low_count) / float(considered)) if considered > 0 else 0.0
    avg_score = (float(sum(scores) / float(len(scores))) if scores else None)
    alert = bool(considered > 0 and low_ratio >= float(alert_ratio))
    recommendation = _parse_quality_recommendation(low_ratio=float(low_ratio), considered=int(considered))

    return {
        "enabled": True,
        "low_threshold": round(float(low_threshold), 3),
        "alert_ratio": round(float(alert_ratio), 3),
        "considered": int(considered),
        "low_count": int(low_count),
        "low_ratio": round(float(low_ratio), 3),
        "avg_score": (round(float(avg_score), 3) if avg_score is not None else None),
        "alert": bool(alert),
        "recommendation": recommendation,
        "low_samples": low_samples,
    }


def _classify_parse_risk(
    *,
    summary: dict[str, Any] | None,
    hardcase_min_low_ratio: float,
    hardcase_min_considered: int,
) -> dict[str, Any]:
    payload = summary if isinstance(summary, dict) else {}
    considered = int(payload.get("considered") or 0)
    low_ratio = float(payload.get("low_ratio") or 0.0)
    recommendation = str(payload.get("recommendation") or "").strip()

    level = "healthy"
    if considered <= 0:
        level = "unknown"
    elif recommendation == "high_parse_risk_reparse_documents" or low_ratio >= 0.8:
        level = "high"
    elif recommendation == "medium_parse_risk_prioritize_low_quality_docs" or low_ratio >= 0.5:
        level = "medium"
    elif recommendation == "monitor_parse_quality_tail" or low_ratio >= 0.2:
        level = "low"

    hardcase_eligible = bool(
        level in {"high", "medium"}
        and considered >= int(max(1, hardcase_min_considered))
        and low_ratio >= float(max(0.0, hardcase_min_low_ratio))
    )
    return {
        "level": level,
        "score": round(float(low_ratio), 3),
        "reason": recommendation or ("no_parse_quality_metadata" if considered <= 0 else "parse_quality_healthy"),
        "considered": int(considered),
        "low_ratio": round(float(low_ratio), 3),
        "hardcase_eligible": bool(hardcase_eligible),
    }


def _doc_key(doc: Document) -> str:
    meta = doc.metadata or {}
    doc_id = meta.get("document_id")
    chunk_index = meta.get("chunk_index")
    if doc_id is not None and chunk_index is not None:
        return f"{doc_id}:{chunk_index}"
    cid = getattr(doc, "id", None) or meta.get("chunk_id")
    if cid:
        return str(cid)
    content = (doc.page_content or "").strip()
    return f"content:{stable_hash(content)}"


def _safe_post_rerank_pipeline_summary(raw: Any) -> list[dict[str, Any]]:
    """
    Parse/normalize the Evidence post-rerank pipeline config into a low-cardinality summary.

    Notes:
    - We intentionally keep only {provider, top_n} so this can be embedded into retrieval_config_hash
      without leaking secrets or environment-specific paths.
    - Expected input is JSON from settings.EVIDENCE_POST_RERANK_PIPELINE.
    """
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        obj = json.loads(text)
    except Exception:
        return []
    if not isinstance(obj, list):
        return []

    out: list[dict[str, Any]] = []
    for item in obj:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip().lower()
        if not provider or provider in {"none", "off", "false", "0"}:
            continue
        top_n_raw = item.get("top_n")
        try:
            top_n = int(top_n_raw) if top_n_raw is not None else 0
        except Exception:
            top_n = 0
        top_n = max(0, top_n)
        out.append({"provider": provider, "top_n": top_n or None})
        if len(out) >= 4:
            break
    return out


def _fetch_document_chunks_for_kg_injection(
    *,
    db: Any,
    tenant_id: Any,
    account_id: Any,
    dataset_id: Any,
    document_ids: list[Any],
    chunk_ids: list[UUID],
) -> list[Any]:
    """
    Best-effort load DocumentChunk rows for KG chunk injection.

    This is intentionally a small helper so tests can monkeypatch it without setting up a real DB.
    """
    if not chunk_ids:
        return []

    if db is None or tenant_id is None:
        return []

    from app.models.document import DocumentChunk as DBDocumentChunk  # noqa: WPS433

    # Prefer explicit document_ids scope (already ACL-filtered by the API layer when present).
    if document_ids:
        return (
            db.query(DBDocumentChunk)
            .filter(
                DBDocumentChunk.tenant_id == tenant_id,
                DBDocumentChunk.document_id.in_(list(document_ids)),
                DBDocumentChunk.id.in_(list(chunk_ids)),
            )
            .all()
        )

    # Dataset-scoped retrieval: enforce dataset permission + doc-level ACL via shared helper.
    if dataset_id is None or not str(account_id or "").strip():
        return []

    try:
        from sqlalchemy import select  # noqa: WPS433

        from app.models.document import Document as DBDocument  # noqa: WPS433
        from app.services.dataset_profile_service import build_dataset_documents_query  # noqa: WPS433

        _ds, q = build_dataset_documents_query(
            db,
            tenant_id=tenant_id,
            account_id=str(account_id),
            dataset_id=dataset_id,
        )
        doc_ids_subq = q.with_entities(DBDocument.id).subquery()

        return (
            db.query(DBDocumentChunk)
            .filter(
                DBDocumentChunk.tenant_id == tenant_id,
                DBDocumentChunk.document_id.in_(select(doc_ids_subq.c.id)),
                DBDocumentChunk.id.in_(list(chunk_ids)),
            )
            .all()
        )
    except Exception:
        return []


def _resolve_post_rerank_corpus_cache_token(state: Dict[str, Any]) -> str | None:
    db = state.get("db")
    tenant_id = state.get("tenant_id")
    if db is None or tenant_id is None:
        return None
    try:
        tenant_uuid = UUID(str(tenant_id))
    except Exception:
        return None

    dataset_id_raw = state.get("dataset_id")
    dataset_uuid: UUID | None = None
    if dataset_id_raw is not None:
        try:
            dataset_uuid = UUID(str(dataset_id_raw))
        except Exception:
            dataset_uuid = None

    document_ids_raw = state.get("document_ids") or []
    document_ids: list[UUID] = []
    for raw in list(document_ids_raw):
        try:
            document_ids.append(UUID(str(raw)))
        except Exception:
            continue

    try:
        return resolve_corpus_cache_token(
            db,
            tenant_id=tenant_uuid,
            dataset_id=dataset_uuid,
            document_ids=document_ids,
        )
    except Exception:
        return None


def run_retrieval(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute retrieval only and return an updated RAG-like state dict.

    Expected input keys (best-effort; missing keys fall back to settings defaults):
    - question: str (required)
    - history: optional list[{role, content}]
    - tenant_id/account_id/dataset_id/document_ids: scope
    - rag params: top_k/score_threshold/retrieval_mode/retrieval_profile/...

    Returns keys (best-effort):
    - query_for_retrieval, docs, citations, metrics, abstain_triggered, abstain_reason, query_debug
    """
    question = str(state.get("question") or "")
    history_text = _build_history_text(state.get("history"))
    engine = get_rag_engine()

    query_for_retrieval = question
    rewrite_elapsed = 0.0
    rewrite_used = False
    rewrite_model_used = None
    rewrite_strategy_id: str | None = None
    rewrite_strategy_hash: str | None = None
    rewrite_temperature: float | None = None
    rewrite_max_chars: int | None = None
    sparse_enabled_override = state.get("sparse_retrieval_enabled")
    sparse_enabled = (
        bool(sparse_enabled_override)
        if sparse_enabled_override is not None
        else bool(getattr(settings, "SPARSE_RETRIEVAL_ENABLED", False))
    )
    sparse_provider_raw = state.get("sparse_retrieval_provider")
    sparse_provider = str(
        sparse_provider_raw
        if sparse_provider_raw is not None
        else (getattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "deterministic") or "deterministic")
    ).strip().lower() or "deterministic"

    # KG search output can be reused by multiple retrieval steps (query expansion / chunk injection).
    kg_result_cached: dict[str, Any] | None = None
    intent_router_meta: Dict[str, Any] = {"enabled": False, "used": False}

    rewrite_enabled_req = state.get("enable_query_rewrite")
    rewrite_enabled = bool(rewrite_enabled_req) if rewrite_enabled_req is not None else bool(settings.ENABLE_QUERY_REWRITE)
    if rewrite_enabled:
        spec = build_query_rewrite_strategy_spec(state.get("query_rewrite_strategy") or getattr(settings, "QUERY_REWRITE_STRATEGY", None))
        rewrite_strategy_id = str(spec.get("strategy_id") or "").strip() or None
        rewrite_strategy_hash = str(spec.get("strategy_hash") or "").strip() or None
        try:
            rewrite_temperature = float(
                (settings.QUERY_REWRITE_TEMPERATURE if state.get("query_rewrite_temperature") is None else state.get("query_rewrite_temperature")) or 0.0
            )
        except Exception:
            rewrite_temperature = 0.0
        try:
            rewrite_max_chars = int(
                (settings.QUERY_REWRITE_MAX_CHARS if state.get("query_rewrite_max_chars") is None else state.get("query_rewrite_max_chars")) or 0
            )
        except Exception:
            rewrite_max_chars = 0

    if (
        bool(rewrite_enabled)
        and history_text != "(No conversation history)"
        and len(question) <= int(rewrite_max_chars or 0)
        and should_rewrite_query(question)
    ):
        rewrite_llm = engine.models.get("fast") or engine.models.get("default")  # type: ignore[attr-defined]
        rewrite_model_used = getattr(rewrite_llm, "model_name", None) or getattr(rewrite_llm, "model", None)
        try:
            prompt_template = get_query_rewrite_prompt_template(rewrite_strategy_id)
            rewrite_prompt = ChatPromptTemplate.from_template(prompt_template)
            rewrite_chain = (
                rewrite_prompt
                | rewrite_llm.bind(temperature=rewrite_temperature)
                | StrOutputParser()
            )
            rw_start = time.time()
            rewritten = rewrite_chain.invoke({"history": history_text, "question": question})
            rewrite_elapsed = time.time() - rw_start
            rewritten = (rewritten or "").strip().strip('"')
            if rewritten:
                query_for_retrieval = rewritten
        except Exception:
            query_for_retrieval = question
            rewrite_elapsed = 0.0

        rewrite_used = query_for_retrieval != question

    # Capture caller intent before any routing/presets apply (kept for trace/metrics).
    requested_retrieval_mode = state.get("retrieval_mode", "hybrid") or "hybrid"
    requested_retrieval_profile = state.get("retrieval_profile")
    retrieval_contract_policy = resolve_retrieval_contract_policy(
        mode=(
            state.get("retrieval_contract_mode")
            if state.get("retrieval_contract_mode") is not None
            else getattr(settings, "RETRIEVAL_CONTRACT_MODE", "")
        ),
        requested_top_k=int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 5),
        hard_fallback_enabled_setting=bool(getattr(settings, "RETRIEVAL_HARD_FALLBACK_ENABLED", False)),
        hard_fallback_mode_setting=str(getattr(settings, "RETRIEVAL_HARD_FALLBACK_MODE", "keyword") or "keyword"),
        hard_fallback_top_k_setting=int(getattr(settings, "RETRIEVAL_HARD_FALLBACK_TOP_K", 30) or 30),
        visible_evidence_only_setting=bool(getattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False)),
        evidence_span_strict_setting=bool(getattr(settings, "RAG_EVIDENCE_REQUIRE_SPANS_ENABLED", False)),
    )
    retrieval_contract_mode = str(retrieval_contract_policy.get("mode") or "").strip().lower()
    contract_deterministic_recall = bool(retrieval_contract_policy.get("deterministic_recall"))

    # Step 0.25: Deterministic intent router (optional).
    #
    # Goal: map query "shape" (log/api/howto/faq) to retrieval presets and safe toggles.
    # Must be deterministic + PII-safe (no raw query in meta payloads).
    intent_router_req = state.get("intent_router")
    intent_router_enabled = (
        bool(intent_router_req)
        if intent_router_req is not None
        else bool(getattr(settings, "RAG_INTENT_ROUTER_ENABLED", False))
    )
    intent_router_meta = {"enabled": bool(intent_router_enabled), "used": False}
    if bool(intent_router_enabled):
        try:
            overrides, intent_router_meta = route_retrieval_preset(
                query=query_for_retrieval,
                retrieval_mode=str(requested_retrieval_mode or ""),
                retrieval_profile=(
                    str(requested_retrieval_profile).strip()
                    if requested_retrieval_profile is not None
                    else None
                ),
                top_k=int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 5),
                score_threshold=float(
                    state.get("score_threshold", settings.SIMILARITY_THRESHOLD)
                    if state.get("score_threshold", settings.SIMILARITY_THRESHOLD) is not None
                    else (settings.SIMILARITY_THRESHOLD or 0.0)
                ),
                enable_reranker=bool(state.get("enable_reranker", settings.ENABLE_RERANKER)),
                enable_weight_rerank=bool(state.get("enable_weight_rerank", True)),
                enable_multi_query=(state.get("enable_multi_query") if "enable_multi_query" in state else None),
                enable_query_alias_expansion=(
                    state.get("enable_query_alias_expansion") if "enable_query_alias_expansion" in state else None
                ),
                intent_router_policy=(state.get("intent_router_policy") if "intent_router_policy" in state else None),
            )
            for k, v in (overrides or {}).items():
                state[k] = v
        except Exception as exc:  # noqa: BLE001
            intent_router_meta = {
                "enabled": True,
                "used": False,
                "error": f"intent_router_exception:{str(exc)[:160]}",
            }

    effective_retrieval_mode = state.get("retrieval_mode", "hybrid") or "hybrid"
    request_retrieval_mode = normalize_retrieval_mode(effective_retrieval_mode)
    retrieval_mode_routed = False
    mode_norm = str(request_retrieval_mode or "hybrid").lower().strip()
    if mode_norm == "auto":
        request_retrieval_mode = guess_retrieval_mode(query_for_retrieval)
        retrieval_mode_routed = True
        mode_norm = str(request_retrieval_mode or "hybrid").lower().strip()
    if mode_norm not in ("hybrid", "vector", "keyword", "mmr"):
        request_retrieval_mode = "hybrid"
        mode_norm = "hybrid"

    profile_applied = apply_retrieval_profile_overrides(
        profile=state.get("retrieval_profile"),
        top_k=int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 5),
        score_threshold=float(
            state.get("score_threshold", settings.SIMILARITY_THRESHOLD)
            if state.get("score_threshold", settings.SIMILARITY_THRESHOLD) is not None
            else (settings.SIMILARITY_THRESHOLD or 0.0)
        ),
        retrieval_mode=request_retrieval_mode,
        enable_reranker=bool(state.get("enable_reranker", settings.ENABLE_RERANKER)),
        reranker_provider=str(state.get("reranker_provider", settings.RERANKER_PROVIDER) or ""),
        reranker_top_n=int(state.get("reranker_top_n", settings.RERANKER_TOP_N) or settings.RERANKER_TOP_N or 20),
        enable_weight_rerank=bool(state.get("enable_weight_rerank", True)),
        retrieval_contract_mode=(
            state.get("retrieval_contract_mode")
            if state.get("retrieval_contract_mode") is not None
            else getattr(settings, "RETRIEVAL_CONTRACT_MODE", "")
        ),
        visible_evidence_only=(
            bool(state.get("visible_evidence_only"))
            if state.get("visible_evidence_only") is not None
            else None
        ),
    )
    profile_norm = str(profile_applied.get("retrieval_profile") or "").strip().lower()
    retriever_update: Dict[str, Any] = {
        "k": int(profile_applied.get("top_k") or settings.RETRIEVAL_TOP_K),
        "score_threshold": float(profile_applied.get("score_threshold") or 0.0),
        "alpha": state.get("alpha", 0.6),
        # Optional: channel fusion override (used by Evidence API ablations / retrieval-only tuning).
        "fusion_strategy": state.get("fusion_strategy") or settings.RETRIEVAL_FUSION_STRATEGY,
        "fusion_budgets": state.get("fusion_budgets"),
        "fusion_min_scores": state.get("fusion_min_scores"),
        "fusion_weights": state.get("fusion_weights"),
        "retrieval_mode": str(profile_applied.get("retrieval_mode") or request_retrieval_mode),
        "enable_weight_rerank": (
            profile_applied.get("enable_weight_rerank")
            if profile_applied.get("enable_weight_rerank") is not None
            else state.get("enable_weight_rerank", True)
        ),
        "vector_weight": state.get("vector_weight", 0.6),
        "keyword_weight": state.get("keyword_weight", 0.4),
        "mmr_lambda": state.get("mmr_lambda", settings.RETRIEVAL_MMR_LAMBDA),
        "enable_reranker": (
            profile_applied.get("enable_reranker")
            if profile_applied.get("enable_reranker") is not None
            else state.get("enable_reranker", settings.ENABLE_RERANKER)
        ),
        "reranker_provider": str(
            profile_applied.get("reranker_provider")
            or state.get("reranker_provider", settings.RERANKER_PROVIDER)
            or settings.RERANKER_PROVIDER
        ),
        "reranker_top_n": int(
            profile_applied.get("reranker_top_n")
            if profile_applied.get("reranker_top_n") is not None
            else state.get("reranker_top_n", settings.RERANKER_TOP_N)
        ),
        "sparse_enabled": sparse_enabled,
        "sparse_provider": sparse_provider,
        "tenant_id": state.get("tenant_id"),
        "account_id": state.get("account_id"),
        "dataset_id": state.get("dataset_id"),
        "document_ids": state.get("document_ids"),
        "metadata_filter": state.get("metadata_filter"),
    }

    if profile_applied.get("retrieval_contract_mode") is not None:
        state["retrieval_contract_mode"] = profile_applied.get("retrieval_contract_mode")
    if profile_applied.get("visible_evidence_only") is not None:
        state["visible_evidence_only"] = bool(profile_applied.get("visible_evidence_only"))

    retrieval_contract_policy = resolve_retrieval_contract_policy(
        mode=(
            state.get("retrieval_contract_mode")
            if state.get("retrieval_contract_mode") is not None
            else getattr(settings, "RETRIEVAL_CONTRACT_MODE", "")
        ),
        requested_top_k=int(retriever_update.get("k") or settings.RETRIEVAL_TOP_K or 5),
        hard_fallback_enabled_setting=bool(getattr(settings, "RETRIEVAL_HARD_FALLBACK_ENABLED", False)),
        hard_fallback_mode_setting=str(getattr(settings, "RETRIEVAL_HARD_FALLBACK_MODE", "keyword") or "keyword"),
        hard_fallback_top_k_setting=int(getattr(settings, "RETRIEVAL_HARD_FALLBACK_TOP_K", 30) or 30),
        visible_evidence_only_setting=bool(getattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False)),
        evidence_span_strict_setting=bool(getattr(settings, "RAG_EVIDENCE_REQUIRE_SPANS_ENABLED", False)),
    )
    retrieval_contract_mode = str(retrieval_contract_policy.get("mode") or "").strip().lower()
    contract_deterministic_recall = bool(retrieval_contract_policy.get("deterministic_recall"))

    # Recall-first profiles: do not drop candidates due to dedup/diversity heuristics.
    if _is_recall_profile(profile_norm):
        retriever_update.update(
            {
                "dedup_enabled": False,
                "max_chunks_per_doc": 0,
                "max_chunks_per_page": 0,
                "min_distinct_docs": 0,
            }
        )

    retriever = hybrid_retriever.model_copy(update=retriever_update)

    # Controlled query expansion (deterministic).
    alias_elapsed = 0.0
    alias_used = False
    alias_meta: Dict[str, Any] = {"enabled": False, "used": False}
    alias_queries: List[str] = []

    alias_enabled = state.get("enable_query_alias_expansion")
    aliases = state.get("query_aliases")
    if alias_enabled is None:
        alias_enabled = bool(aliases)
    if bool(alias_enabled):
        t0 = time.time()
        alias_queries, alias_meta = generate_alias_queries(
            query=query_for_retrieval,
            aliases=aliases,
            max_queries=(5 if state.get("query_alias_max_queries") is None else int(state.get("query_alias_max_queries") or 0)),
        )
        alias_elapsed = time.time() - t0
        alias_used = bool(alias_queries)

    # Deterministic dictionary expansion (bounded, auditable).
    dict_elapsed = 0.0
    dict_used = False
    dict_meta: Dict[str, Any] = {"enabled": False, "used": False}
    dict_expansions: List[Dict[str, Any]] = []
    try:
        from app.query.expand import generate_dictionary_expansions, load_base_dictionary_rules

        t0 = time.time()
        dict_expansions, dict_meta = generate_dictionary_expansions(
            query=query_for_retrieval,
            rules=load_base_dictionary_rules(),
            max_expansions_total=5,
            max_expansions_per_rule=1,
        )
        dict_elapsed = time.time() - t0
        dict_used = bool(dict_expansions)
    except Exception as exc:  # noqa: BLE001
        dict_elapsed = 0.0
        dict_used = False
        dict_expansions = []
        dict_meta = {"enabled": False, "used": False, "error": str(exc)[:200]}

    # KG query expansion (entity names, optional).
    kg_query_expansion_enabled = bool(getattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False))
    kg_query_expansion_used = False
    kg_query_expansion_elapsed = 0.0
    kg_query_expansion_error: str | None = None
    kg_query_expansion_entities_total = 0
    kg_query_expansion_entities_selected = 0
    kg_query_expansion_queries: list[str] = []
    kg_query_expansion_entity_names: list[str] = []
    try:
        tenant_id = state.get("tenant_id")
        account_id = state.get("account_id")
        document_ids = state.get("document_ids") or []
        dataset_id = state.get("dataset_id")

        if (
            kg_query_expansion_enabled
            and bool(getattr(settings, "KG_ENABLED", False))
            and bool(getattr(settings, "KG_CHAT_ENABLED", False))
            and tenant_id is not None
            and (document_ids or dataset_id is not None)
            and (account_id is not None or dataset_id is None)
        ):
            import asyncio

            coro = kg_search(
                query=query_for_retrieval,
                tenant_id=tenant_id,
                document_ids=(list(document_ids) or None),
                dataset_id=(dataset_id if not document_ids else None),
                account_id=account_id,
            )

            t0 = time.time()
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    kg_result = pool.submit(asyncio.run, coro).result()
            elif loop is not None:
                kg_result = loop.run_until_complete(coro)
            else:
                kg_result = asyncio.run(coro)

            kg_result_cached = kg_result if isinstance(kg_result, dict) else None
            kg_query_expansion_elapsed = time.time() - t0

            entities = (kg_result or {}).get("entities") or []
            entities = entities if isinstance(entities, list) else []
            kg_query_expansion_entities_total = len(entities)

            max_entities = max(0, int(getattr(settings, "RAG_KG_QUERY_EXPANSION_MAX_ENTITIES", 5) or 5))
            max_queries = max(0, int(getattr(settings, "RAG_KG_QUERY_EXPANSION_MAX_QUERIES", 5) or 5))
            min_weight = float(getattr(settings, "RAG_KG_QUERY_EXPANSION_MIN_ENTITY_WEIGHT", 0.15) or 0.15)
            exclude_types = parse_csv(
                str(getattr(settings, "RAG_KG_QUERY_EXPANSION_EXCLUDE_ENTITY_TYPES", "") or "")
            )
            exclude_all = "*" in exclude_types
            exclude_fold = {t.casefold() for t in exclude_types if str(t or "").strip() and t != "*"}

            scored: list[tuple[float, str]] = []
            for ent in entities:
                if not isinstance(ent, dict):
                    continue
                if exclude_all:
                    continue
                etype = str(ent.get("type") or "").strip()
                if etype and etype.casefold() in exclude_fold:
                    continue
                name = (ent.get("name") or "").strip()
                if not name:
                    continue
                try:
                    w = float(ent.get("weight", 0.0) or 0.0)
                except Exception:
                    w = 0.0
                if w < min_weight:
                    continue
                scored.append((w, name))

            scored.sort(key=lambda x: (-x[0], x[1]))
            seen_names: set[str] = set()
            base_folded = query_for_retrieval.casefold()
            selected_names: list[str] = []
            for _w, name in scored:
                key = name.casefold() if name.isascii() else name
                if key in seen_names:
                    continue
                seen_names.add(key)
                if key and (key in base_folded):
                    continue
                selected_names.append(name)
                if max_entities > 0 and len(selected_names) >= max_entities:
                    break

            kg_query_expansion_entities_selected = len(selected_names)
            kg_query_expansion_entity_names = selected_names[: max_queries if max_queries > 0 else len(selected_names)]

            for name in kg_query_expansion_entity_names:
                q = f"{query_for_retrieval} {name}".strip()
                if len(q) > 500:
                    q = q[:500] + "..."
                kg_query_expansion_queries.append(q)
                if max_queries > 0 and len(kg_query_expansion_queries) >= max_queries:
                    break

            kg_query_expansion_used = bool(kg_query_expansion_queries)
    except Exception as exc:  # noqa: BLE001
        kg_query_expansion_used = False
        kg_query_expansion_queries = []
        kg_query_expansion_entity_names = []
        kg_query_expansion_error = str(exc)[:200]

    # LLM-powered expansions (optional, bounded).
    multi_query_elapsed = 0.0
    multi_query_used = False
    multi_query_model_used = None
    multi_query_parse_meta: Dict[str, Any] = {"ok": False, "method": None, "error": None}
    multi_queries: List[str] = []

    mq_enabled = bool(settings.ENABLE_MULTI_QUERY) if state.get("enable_multi_query") is None else bool(state.get("enable_multi_query"))
    mq_n = settings.MULTI_QUERY_COUNT if state.get("multi_query_count") is None else int(state.get("multi_query_count") or 0)
    mq_temp = settings.MULTI_QUERY_TEMPERATURE if state.get("multi_query_temperature") is None else float(state.get("multi_query_temperature") or 0.0)
    mq_max_chars = settings.MULTI_QUERY_MAX_CHARS if state.get("multi_query_max_chars") is None else int(state.get("multi_query_max_chars") or 0)

    mq_n = max(0, min(int(mq_n or 0), 8))
    mq_temp = min(2.0, max(0.0, float(mq_temp or 0.0)))
    mq_max_chars = max(0, int(mq_max_chars or 0))

    if mq_enabled and mq_n > 0 and mq_max_chars > 0 and len(query_for_retrieval) <= mq_max_chars:
        mq_llm = engine.models.get("fast") or engine.models.get("default")  # type: ignore[attr-defined]
        multi_query_model_used = getattr(mq_llm, "model_name", None) or getattr(mq_llm, "model", None)
        try:
            mq_chain = (
                engine.multi_query_prompt  # type: ignore[attr-defined]
                | mq_llm.bind(temperature=mq_temp)
                | StrOutputParser()
            )
            mq_start = time.time()
            mq_raw = mq_chain.invoke({"query": query_for_retrieval, "n": mq_n})
            multi_query_elapsed = time.time() - mq_start
            mq_data, multi_query_parse_meta = parse_json_from_text(mq_raw, expected="array")

            if isinstance(mq_data, list):
                seen: set[str] = set()
                for item in mq_data:
                    if not isinstance(item, str):
                        continue
                    q = (item or "").strip().strip('"').strip()
                    if not q:
                        continue
                    if q == query_for_retrieval:
                        continue
                    if q in seen:
                        continue
                    if len(q) > 400:
                        q = q[:400] + "..."
                    seen.add(q)
                    multi_queries.append(q)
                    if len(multi_queries) >= mq_n:
                        break
        except Exception as exc:  # noqa: BLE001
            multi_query_elapsed = 0.0
            multi_query_parse_meta = {"ok": False, "method": None, "error": str(exc)[:200]}
            multi_queries = []

    multi_query_used = bool(multi_queries)

    hyde_used = False
    hyde_elapsed = 0.0
    hyde_model_used = None
    hyde_text = ""
    hyde_max_chars = max(0, int(settings.HYDE_MAX_CHARS or 0))
    retrieval_mode_norm = str(request_retrieval_mode or "hybrid").lower()
    if bool(settings.ENABLE_HYDE) and retrieval_mode_norm not in ("keyword",) and hyde_max_chars > 0 and len(query_for_retrieval) <= hyde_max_chars:
        hyde_llm = engine.models.get("fast") or engine.models.get("default")  # type: ignore[attr-defined]
        hyde_model_used = getattr(hyde_llm, "model_name", None) or getattr(hyde_llm, "model", None)
        try:
            hyde_chain = (
                engine.hyde_prompt  # type: ignore[attr-defined]
                | hyde_llm.bind(temperature=settings.HYDE_TEMPERATURE)
                | StrOutputParser()
            )
            hyde_start = time.time()
            hyde_text = hyde_chain.invoke({"query": query_for_retrieval})
            hyde_elapsed = time.time() - hyde_start
            hyde_text = (hyde_text or "").strip()
            out_max = max(0, int(settings.HYDE_OUTPUT_MAX_CHARS or 0))
            if out_max and len(hyde_text) > out_max:
                hyde_text = hyde_text[:out_max] + "..."
            hyde_used = bool(hyde_text)
        except Exception:
            hyde_text = ""
            hyde_elapsed = 0.0
            hyde_used = False

    decompose_elapsed = 0.0
    decompose_used = False
    decompose_model_used = None
    decompose_parse_meta: Dict[str, Any] = {"ok": False, "method": None, "error": None}
    sub_questions: List[str] = []

    dq_n = max(0, min(int(settings.QUERY_DECOMPOSITION_MAX_SUBQUESTIONS or 0), 8))
    dq_min_chars = max(0, int(settings.QUERY_DECOMPOSITION_MIN_CHARS or 0))
    dq_max_chars = max(0, int(settings.QUERY_DECOMPOSITION_MAX_CHARS or 0))
    if (
        bool(settings.ENABLE_QUERY_DECOMPOSITION)
        and dq_n > 0
        and len(query_for_retrieval) >= dq_min_chars
        and (dq_max_chars <= 0 or len(query_for_retrieval) <= dq_max_chars)
    ):
        from app.rag.core.text import heuristic_decompose_query

        heuristic_fallback_enabled = bool(getattr(settings, "QUERY_DECOMPOSITION_HEURISTIC_FALLBACK_ENABLED", True))
        llm_api_key = str(getattr(settings, "LLM_API_KEY", "") or "").strip()

        if heuristic_fallback_enabled and not llm_api_key:
            sub_questions = heuristic_decompose_query(query_for_retrieval, max_subquestions=dq_n)
            if sub_questions:
                decompose_elapsed = 0.0
                decompose_parse_meta = {"ok": True, "method": "heuristic", "error": None}
        else:
            dq_llm = engine.models.get("fast") or engine.models.get("default")  # type: ignore[attr-defined]
            decompose_model_used = getattr(dq_llm, "model_name", None) or getattr(dq_llm, "model", None)
            try:
                dq_chain = (
                    engine.decompose_prompt  # type: ignore[attr-defined]
                    | dq_llm.bind(temperature=settings.QUERY_DECOMPOSITION_TEMPERATURE)
                    | StrOutputParser()
                )
                dq_start = time.time()
                dq_raw = dq_chain.invoke({"query": query_for_retrieval, "n": dq_n})
                decompose_elapsed = time.time() - dq_start
                dq_data, decompose_parse_meta = parse_json_from_text(dq_raw, expected="array")

                if isinstance(dq_data, list):
                    seen: set[str] = set()
                    for item in dq_data:
                        if not isinstance(item, str):
                            continue
                        q = (item or "").strip().strip('"').strip()
                        if not q:
                            continue
                        if q == query_for_retrieval:
                            continue
                        if q in seen:
                            continue
                        if len(q) > 500:
                            q = q[:500] + "..."
                        seen.add(q)
                        sub_questions.append(q)
                        if len(sub_questions) >= dq_n:
                            break
            except Exception as exc:  # noqa: BLE001
                decompose_elapsed = 0.0
                decompose_parse_meta = {"ok": False, "method": None, "error": str(exc)[:200]}
                sub_questions = []

            if heuristic_fallback_enabled and not sub_questions and not bool(decompose_parse_meta.get("ok")):
                sub_questions = heuristic_decompose_query(query_for_retrieval, max_subquestions=dq_n)
                if sub_questions:
                    decompose_model_used = None
                    decompose_elapsed = 0.0
                    decompose_parse_meta = {"ok": True, "method": "heuristic", "error": None}

    decompose_used = bool(sub_questions)

    retrieval_queries: List[tuple[str, str]] = [("main", query_for_retrieval)]
    for q in alias_queries:
        retrieval_queries.append(("alias", q))
    for e in dict_expansions:
        q = e.get("expanded_text") if isinstance(e, dict) else None
        if q:
            retrieval_queries.append(("dict", str(q)))
    for q in kg_query_expansion_queries:
        retrieval_queries.append(("kgq", q))
    clause_fastlane_queries = build_clause_fastlane_queries(query_for_retrieval)
    for q in clause_fastlane_queries:
        retrieval_queries.append(("clause", q))
    for q in multi_queries:
        retrieval_queries.append(("mq", q))
    for q in sub_questions:
        retrieval_queries.append(("subq", q))
    if hyde_used and hyde_text:
        retrieval_queries.append(("hyde", hyde_text))

    # Deduplicate query variants (avoid redundant retrieval calls).
    seen_queries: set[str] = set()
    deduped_queries: List[tuple[str, str]] = []
    for kind, q in retrieval_queries:
        norm = " ".join((q or "").strip().split())
        if not norm:
            continue
        key = norm.casefold() if norm.isascii() else norm
        if key in seen_queries:
            continue
        seen_queries.add(key)
        deduped_queries.append((kind, norm))
    retrieval_queries = deduped_queries

    docs_by_query: List[List[Document]] = []
    docs_by_query_kinds: List[str] = []
    retrieval_errors: List[str] = []
    retrieval_per_query: List[Dict[str, Any]] = []
    start = time.time()
    retrieval_parallelism = max(1, int(getattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1) or 1))
    retrieval_plan: List[tuple[str, str, Any]] = []
    for kind, q in retrieval_queries:
        r = retriever
        if kind != "main":
            if kind == "hyde":
                r = retriever.model_copy(update={"enable_reranker": False, "retrieval_mode": "vector", "enable_weight_rerank": False})
            else:
                r = retriever.model_copy(update={"enable_reranker": False})
        retrieval_plan.append((kind, q, r))

    def _invoke_with_timing(kind: str, q: str, r: Any) -> tuple[str, List[Document], str | None, float, Dict[str, Any] | None]:
        t0 = time.time()
        try:
            docs_i = r.invoke(q)
            docs_i = engine._annotate_docs_with_role(docs_i or [], kind)  # type: ignore[attr-defined]
            dbg = getattr(r, "_last_debug_metrics", None)
            dbg = _sanitize_retriever_debug(dbg if isinstance(dbg, dict) else None)
            return kind, (docs_i or []), None, time.time() - t0, dbg
        except Exception as exc:  # noqa: BLE001
            return kind, [], str(exc)[:200], time.time() - t0, None

    if retrieval_parallelism <= 1 or len(retrieval_plan) <= 1:
        for kind, q, r in retrieval_plan:
            kind, docs_i, err, elapsed_i, dbg = _invoke_with_timing(kind, q, r)
            retrieval_per_query.append({"kind": kind, "query_chars": len(q or ""), "elapsed_sec": round(elapsed_i, 3), "ok": err is None, "retriever_debug": dbg})
            if err:
                retrieval_errors.append(f"{kind}:{err[:160]}")
            docs_by_query_kinds.append(kind)
            docs_by_query.append(docs_i or [])
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=retrieval_parallelism) as pool:
            futures = [pool.submit(_invoke_with_timing, kind, q, r) for kind, q, r in retrieval_plan]
            for fut in futures:
                kind, docs_i, err, elapsed_i, dbg = fut.result()
                retrieval_per_query.append({"kind": kind, "query_chars": len(q or ""), "elapsed_sec": round(elapsed_i, 3), "ok": err is None, "retriever_debug": dbg})
                if err:
                    retrieval_errors.append(f"{kind}:{err[:160]}")
                docs_by_query_kinds.append(kind)
                docs_by_query.append(docs_i or [])
    retrieval_elapsed = time.time() - start

    top_k = int(retriever_update.get("k") or state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 5)
    mq_diversify_enabled = bool(getattr(settings, "MULTI_QUERY_DIVERSIFY_ENABLED", False)) and bool(mq_enabled)
    try:
        mq_budget_raw = int(getattr(settings, "MULTI_QUERY_DIVERSIFY_BUDGET", 0) or 0)
    except Exception:
        mq_budget_raw = 0
    mq_diversify_budget = max(0, min(int(mq_budget_raw or 0), int(top_k or 0)))
    mq_diversify_used = False
    mq_diversify_selected_mq = 0
    mq_diversify_selected_non_mq = 0
    mq_diversify_fill_from_fused = 0

    if len(docs_by_query) <= 1:
        docs = docs_by_query[0] if docs_by_query else []
    else:
        docs_fused_all = engine.fuse_docs_rrf(docs_by_query, rrf_k=settings.RETRIEVAL_RRF_K, meta_prefix="query_expansion")  # type: ignore[attr-defined]
        if mq_diversify_enabled and mq_diversify_budget > 0:
            mq_lists: list[list[Document]] = []
            non_mq_lists: list[list[Document]] = []
            for kind, docs_i in zip(docs_by_query_kinds, docs_by_query, strict=False):
                if kind == "mq":
                    mq_lists.append(docs_i or [])
                else:
                    non_mq_lists.append(docs_i or [])

            if mq_lists and non_mq_lists:
                mq_diversify_used = True
                docs_non_mq = (
                    engine.fuse_docs_rrf(non_mq_lists, rrf_k=settings.RETRIEVAL_RRF_K, meta_prefix="query_expansion")  # type: ignore[attr-defined]
                    if len(non_mq_lists) > 1
                    else (non_mq_lists[0] or [])
                )
                docs_mq = (
                    engine.fuse_docs_rrf(mq_lists, rrf_k=settings.RETRIEVAL_RRF_K, meta_prefix="query_expansion")  # type: ignore[attr-defined]
                    if len(mq_lists) > 1
                    else (mq_lists[0] or [])
                )

                want_non_mq = max(0, int(top_k) - int(mq_diversify_budget))
                want_mq = int(mq_diversify_budget)

                selected: list[Document] = []
                selected_keys: set[str] = set()

                for d in docs_non_mq:
                    k = engine._doc_key(d)  # type: ignore[attr-defined]
                    if k in selected_keys:
                        continue
                    selected_keys.add(k)
                    selected.append(d)
                    if len(selected) >= want_non_mq:
                        break

                mq_added = 0
                mq_diversify_selected_non_mq = int(len(selected))
                for d in docs_mq:
                    if mq_added >= want_mq:
                        break
                    k = engine._doc_key(d)  # type: ignore[attr-defined]
                    if k in selected_keys:
                        continue
                    selected_keys.add(k)
                    selected.append(d)
                    mq_added += 1
                mq_diversify_selected_mq = int(mq_added)

                # Fill any remaining slots from the full fused list (best-effort).
                for d in docs_fused_all:
                    if len(selected) >= int(top_k):
                        break
                    k = engine._doc_key(d)  # type: ignore[attr-defined]
                    if k in selected_keys:
                        continue
                    selected_keys.add(k)
                    selected.append(d)
                    mq_diversify_fill_from_fused += 1

                docs = selected
            else:
                docs = docs_fused_all
        else:
            docs = docs_fused_all

    docs = (docs or [])[: max(0, top_k)]

    # Optional: KG-assisted retrieval (inject KG-linked chunks as extra candidates).
    kg_chunks_injected = 0
    kg_chunk_injection_error: str | None = None
    try:
        if (
            bool(getattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False))
            and bool(getattr(settings, "KG_ENABLED", False))
            and bool(getattr(settings, "KG_CHAT_ENABLED", False))
            and state.get("tenant_id") is not None
            and ((state.get("document_ids") or []) or state.get("dataset_id") is not None)
        ):
            tenant_id = state.get("tenant_id")
            account_id = state.get("account_id")
            dataset_id = state.get("dataset_id")
            document_ids = list(state.get("document_ids") or [])

            kg_result = kg_result_cached
            if kg_result is None:
                import asyncio

                coro = kg_search(
                    query=query_for_retrieval,
                    tenant_id=tenant_id,
                    document_ids=(document_ids or None),
                    dataset_id=(dataset_id if not document_ids else None),
                    account_id=(account_id if (not document_ids) else None),
                )

                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = None

                if loop is not None and loop.is_running():
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        kg_result = pool.submit(asyncio.run, coro).result()
                elif loop is not None:
                    kg_result = loop.run_until_complete(coro)
                else:
                    kg_result = asyncio.run(coro)

            kg_events = (kg_result or {}).get("events") or []
            max_chunks = max(0, int(getattr(settings, "RAG_KG_CHUNK_INJECTION_MAX_CHUNKS", 0) or 0)) or 5

            score_by_chunk: dict[str, float] = {}
            kg_features_by_chunk: dict[str, dict[str, Any]] = {}
            chunk_ids: list[UUID] = []
            seen_chunk_ids: set[UUID] = set()
            for ev in kg_events if isinstance(kg_events, list) else []:
                if not isinstance(ev, dict):
                    continue
                cid_raw = ev.get("chunk_id")
                if cid_raw is None:
                    continue
                try:
                    cid = UUID(str(cid_raw))
                except Exception:
                    continue
                if cid in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(cid)
                chunk_ids.append(cid)
                cid_str = str(cid)
                try:
                    score_by_chunk[cid_str] = float(ev.get("score", 0.0) or 0.0)
                except Exception:
                    score_by_chunk[cid_str] = 0.0

                # Stable KG ranking features (optional). These are low-cardinality and do not
                # include scope identifiers, so they are safe to propagate into citation metadata.
                feats: dict[str, Any] = {}
                if ev.get("kg_path_length") is not None:
                    feats["kg_path_length"] = ev.get("kg_path_length")
                if ev.get("kg_shared_events") is not None:
                    feats["kg_shared_events"] = ev.get("kg_shared_events")
                if ev.get("kg_evidence_anchored") is not None:
                    feats["kg_evidence_anchored"] = ev.get("kg_evidence_anchored")
                kg_path_raw = ev.get("kg_path")
                if isinstance(kg_path_raw, list) and kg_path_raw:
                    kg_path: list[dict[str, Any]] = []
                    for step in kg_path_raw:
                        if not isinstance(step, dict):
                            continue
                        ent_id = str(step.get("entity_id") or "").strip()
                        if not ent_id:
                            continue
                        typ = str(step.get("type") or "").strip()
                        entry: dict[str, Any] = {"entity_id": ent_id}
                        if typ:
                            entry["type"] = typ[:100]
                        kg_path.append(entry)
                        if len(kg_path) >= 6:
                            break
                    if kg_path:
                        feats["kg_path"] = kg_path

                def _safe_kg_path_provenance(raw: Any) -> dict[str, Any] | None:
                    if not isinstance(raw, dict) or not raw:
                        return None
                    out: dict[str, Any] = {}
                    schema = str(raw.get("schema") or "").strip()
                    if schema:
                        out["schema"] = schema[:80]
                    kind = str(raw.get("kind") or "").strip()
                    if kind:
                        out["kind"] = kind[:50]
                    try:
                        if raw.get("hops") is not None:
                            out["hops"] = int(raw.get("hops") or 0)
                    except Exception:
                        pass

                    nodes_raw = raw.get("nodes")
                    if isinstance(nodes_raw, list) and nodes_raw:
                        nodes: list[dict[str, Any]] = []
                        for n in nodes_raw:
                            if not isinstance(n, dict):
                                continue
                            node: dict[str, Any] = {}
                            k = str(n.get("kind") or "").strip()
                            if k:
                                node["kind"] = k[:30]
                            for key in ("entity_id", "type", "event_id", "document_id", "chunk_id"):
                                v = n.get(key)
                                if v is None:
                                    continue
                                s = str(v).strip()
                                if not s:
                                    continue
                                node[key] = s[:200]
                            if node:
                                nodes.append(node)
                            if len(nodes) >= 10:
                                break
                        if nodes:
                            out["nodes"] = nodes

                    edges_raw = raw.get("edges")
                    if isinstance(edges_raw, list) and edges_raw:
                        edges: list[dict[str, Any]] = []
                        for e in edges_raw:
                            if not isinstance(e, dict):
                                continue
                            edge: dict[str, Any] = {}
                            k = str(e.get("kind") or "").strip()
                            if k:
                                edge["kind"] = k[:30]
                            for key in (
                                "entity_id",
                                "event_id",
                                "document_id",
                                "chunk_id",
                                "relation_id",
                                "predicate",
                                "confidence_bucket",
                                "evidence_source",
                            ):
                                v = e.get(key)
                                if v is None:
                                    continue
                                s = str(v).strip()
                                if not s:
                                    continue
                                edge[key] = s[:200]
                            if edge:
                                edges.append(edge)
                            if len(edges) >= 10:
                                break
                        if edges:
                            out["edges"] = edges

                    return out or None

                prov = _safe_kg_path_provenance(ev.get("kg_path_provenance"))
                if prov:
                    feats["kg_path_provenance"] = prov
                if feats:
                    kg_features_by_chunk[cid_str] = feats
                if len(chunk_ids) >= max_chunks:
                    break

            if chunk_ids:
                db = state.get("db")
                owns_db = False
                if db is None:
                    try:
                        from app.core.database import SessionLocal  # noqa: WPS433

                        db = SessionLocal()
                        owns_db = True
                    except Exception:
                        db = None
                        owns_db = False

                try:
                    rows = _fetch_document_chunks_for_kg_injection(
                        db=db,
                        tenant_id=tenant_id,
                        account_id=account_id,
                        dataset_id=dataset_id,
                        document_ids=document_ids,
                        chunk_ids=chunk_ids,
                    )
                finally:
                    if owns_db and db is not None:
                        try:
                            db.close()
                        except Exception:
                            pass

                chunk_by_id: dict[UUID, Any] = {}
                for ch in (rows or []):
                    try:
                        cid = ch.id
                        content = ch.content
                    except Exception:
                        continue
                    if cid is None or content is None:
                        continue
                    chunk_by_id[cid] = ch

                kg_docs: list[Document] = []
                for cid in chunk_ids:
                    ch = chunk_by_id.get(cid)
                    if ch is None:
                        continue
                    meta = dict(getattr(ch, "doc_metadata", None) or {})
                    meta["retrieval_role"] = "kg"
                    meta.setdefault("document_id", str(getattr(ch, "document_id", "") or ""))
                    meta.setdefault("chunk_id", str(getattr(ch, "id", "") or ""))
                    meta.setdefault("chunk_index", getattr(ch, "chunk_index", None))
                    page_number = getattr(ch, "page_number", None)
                    if page_number is not None:
                        meta.setdefault("page", int(page_number))
                        meta.setdefault("page_number", int(page_number))
                    start_char = getattr(ch, "start_char", None)
                    end_char = getattr(ch, "end_char", None)
                    if start_char is not None:
                        meta.setdefault("start_char", int(start_char))
                    if end_char is not None:
                        meta.setdefault("end_char", int(end_char))
                    if str(cid) in score_by_chunk:
                        meta.setdefault("retrieval_score", float(score_by_chunk.get(str(cid), 0.0) or 0.0))
                        meta.setdefault("score", float(score_by_chunk.get(str(cid), 0.0) or 0.0))
                    feats = kg_features_by_chunk.get(str(cid))
                    if isinstance(feats, dict) and feats:
                        for k, v in feats.items():
                            if v is None:
                                continue
                            meta[k] = v

                    kg_docs.append(
                        Document(
                            page_content=str(getattr(ch, "content", None) or ""),
                            metadata=meta,
                            id=str(cid),
                        )
                    )

                if kg_docs:
                    # Merge KG docs into existing candidates without using merge order as an implicit
                    # ranking signal:
                    # - Preserve existing ordering for the base retriever results.
                    # - If a KG chunk duplicates an existing chunk, replace it in-place (KG version wins),
                    #   so provenance/score stays consistent.
                    merged = [d for d in (docs or []) if d is not None]
                    index_by_key: dict[str, int] = {}
                    for i, d in enumerate(merged):
                        try:
                            index_by_key[_doc_key(d)] = i
                        except Exception:
                            continue

                    for d in kg_docs:
                        try:
                            key = _doc_key(d)
                        except Exception:
                            continue
                        if key in index_by_key:
                            merged[index_by_key[key]] = d
                            continue
                        index_by_key[key] = len(merged)
                        merged.append(d)

                    docs = merged
                    kg_chunks_injected = len(kg_docs)
    except Exception as exc:  # noqa: BLE001
        kg_chunks_injected = 0
        kg_chunk_injection_error = str(exc)[:200]

    # Optional: TAG injection (table_store results) passed in by the API layer.
    injected = state.get("tag_docs")
    tag_docs: List[Document] = []
    if isinstance(injected, list) and injected:
        for obj in injected[:10]:
            if isinstance(obj, Document):
                tag_docs.append(obj)
                continue
            if isinstance(obj, dict):
                content = obj.get("page_content")
                if content is None:
                    content = obj.get("content")
                meta = obj.get("metadata")
                meta = meta if isinstance(meta, dict) else {}
                did = obj.get("id") or meta.get("chunk_id")
                try:
                    tag_docs.append(Document(page_content=str(content or ""), metadata=meta, id=did))
                except Exception:
                    continue
    if tag_docs:
        docs = tag_docs + (docs or [])

    # Optional: attach stable KG ranking features to candidates so rerankers (LTR) can
    # use KG as a signal source (not just as a candidate expander).
    #
    # These features are intentionally low-cardinality and avoid leaking scope identifiers.
    try:
        for doc in docs or []:
            if doc is None:
                continue
            meta = doc.metadata or {}
            role = str(meta.get("retrieval_role") or "main").strip().lower() or "main"
            if role != "kg":
                continue

            # For injected KG chunks, meta.score is the KG recall score (best-effort).
            try:
                kg_score = float(meta.get("score") or 0.0)
            except Exception:
                kg_score = 0.0

            meta["kg_pagerank"] = float(kg_score)

            # Prefer KG-provided features when available (e.g., from KG search rerank output).
            try:
                path_len = int(meta.get("kg_path_length")) if meta.get("kg_path_length") is not None else 1
            except Exception:
                path_len = 1
            path_len = max(1, min(int(path_len), 5))
            meta["kg_path_length"] = int(path_len)

            try:
                shared = int(meta.get("kg_shared_events")) if meta.get("kg_shared_events") is not None else 1
            except Exception:
                shared = 1
            shared = max(0, min(int(shared), 5))
            meta["kg_shared_events"] = int(shared)

            if "kg_evidence_anchored" in meta:
                meta["kg_evidence_anchored"] = bool(meta.get("kg_evidence_anchored"))
            else:
                meta["kg_evidence_anchored"] = True

            # Confidence buckets (low-cardinality one-hot). Thresholds are intentionally coarse.
            low = 0.0
            mid = 0.0
            high = 0.0
            if kg_score >= 0.75:
                high = 1.0
            elif kg_score >= 0.5:
                mid = 1.0
            elif kg_score > 0.0:
                low = 1.0
            meta["kg_edge_conf_low"] = low
            meta["kg_edge_conf_mid"] = mid
            meta["kg_edge_conf_high"] = high
    except Exception:
        pass

    # Optional: post-fusion rerank (evidence-first) on the final candidate list.
    post_rerank_enabled = bool(getattr(settings, "EVIDENCE_POST_RERANK_ENABLED", False))
    post_rerank_pipeline_enabled = bool(getattr(settings, "EVIDENCE_POST_RERANK_PIPELINE_ENABLED", False))
    post_rerank_pipeline_raw = getattr(settings, "EVIDENCE_POST_RERANK_PIPELINE", "")
    post_rerank_pipeline: list[dict[str, Any]] = []
    post_rerank_pipeline_used = False
    post_rerank_pipeline_stages: list[dict[str, Any]] = []
    post_rerank_used = False
    post_rerank_provider: str | None = None
    post_rerank_model_used: str | None = None
    post_rerank_elapsed = 0.0
    post_rerank_error: str | None = None
    post_rerank_candidates_n = 0
    post_rerank_skip_reason: str | None = None
    post_rerank_cache_enabled = bool(getattr(settings, "EVIDENCE_POST_RERANK_CACHE_ENABLED", False))
    post_rerank_cache_backend = get_evidence_post_rerank_cache_backend()
    post_rerank_cache_hits = 0
    post_rerank_cache_misses = 0
    post_rerank_corpus_cache_token = _resolve_post_rerank_corpus_cache_token(state)
    post_rerank_score_calibration_enabled = bool(
        getattr(settings, "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ENABLED", False)
    )
    try:
        post_rerank_score_calibration_alpha = float(
            getattr(settings, "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA", 0.7) or 0.7
        )
    except Exception:
        post_rerank_score_calibration_alpha = 0.7
    post_rerank_score_calibration_alpha = min(1.0, max(0.0, float(post_rerank_score_calibration_alpha)))
    post_rerank_score_calibration_used = False
    post_rerank_score_calibration_stats: dict[str, Any] = {
        "enabled": bool(post_rerank_score_calibration_enabled),
        "alpha": round(float(post_rerank_score_calibration_alpha), 4),
        "used": False,
    }

    def _calibrate_post_rerank_prefix(prefix_docs: List[Document]) -> List[Document]:
        nonlocal post_rerank_score_calibration_used
        if not post_rerank_score_calibration_enabled:
            return prefix_docs
        if not prefix_docs:
            post_rerank_score_calibration_stats["skip_reason"] = "no_candidates"
            return prefix_docs

        rows: list[dict[str, Any]] = []
        for idx, doc in enumerate(prefix_docs):
            meta = dict(doc.metadata or {})
            rid = _doc_key(doc) or str(idx)

            base_raw = meta.get("retrieval_score")
            if base_raw is None:
                base_raw = meta.get("score", 0.0)
            try:
                retrieval_score = float(base_raw or 0.0)
            except Exception:
                retrieval_score = 0.0

            rerank_raw = meta.get("rerank_score")
            try:
                rerank_score = float(rerank_raw) if rerank_raw is not None else None
            except Exception:
                rerank_score = None

            rows.append(
                {
                    "idx": int(idx),
                    "rid": rid,
                    "doc": doc,
                    "meta": meta,
                    "retrieval_score": float(retrieval_score),
                    "rerank_score": rerank_score,
                }
            )

        ranked_rows = [r for r in rows if r.get("rerank_score") is not None]
        if len(ranked_rows) < 2:
            post_rerank_score_calibration_stats["skip_reason"] = "insufficient_rerank_scores"
            post_rerank_score_calibration_stats["eligible_docs"] = int(len(ranked_rows))
            return prefix_docs

        def _minmax(values: list[float]) -> list[float]:
            if not values:
                return []
            lo = min(values)
            hi = max(values)
            rng = hi - lo
            if rng <= 0.0:
                return [0.0 for _ in values]
            return [(float(v) - float(lo)) / float(rng) for v in values]

        retrieval_norm = _minmax([float(r.get("retrieval_score") or 0.0) for r in rows])
        rerank_norm_values = _minmax([float(r.get("rerank_score") or 0.0) for r in ranked_rows])
        rerank_norm_by_id: dict[str, float] = {
            str(ranked_rows[i].get("rid") or ""): float(rerank_norm_values[i])
            for i in range(min(len(ranked_rows), len(rerank_norm_values)))
        }

        for i, r in enumerate(rows):
            base_norm = float(retrieval_norm[i]) if i < len(retrieval_norm) else 0.0
            rr_norm = rerank_norm_by_id.get(str(r.get("rid") or ""))
            if rr_norm is None:
                calibrated = base_norm
            else:
                calibrated = (post_rerank_score_calibration_alpha * float(rr_norm)) + (
                    (1.0 - post_rerank_score_calibration_alpha) * float(base_norm)
                )
            r["retrieval_score_norm"] = float(base_norm)
            r["rerank_score_norm"] = (float(rr_norm) if rr_norm is not None else None)
            r["calibrated_score"] = float(calibrated)

        rows_sorted = sorted(
            rows,
            key=lambda r: (
                -float(r.get("calibrated_score") or 0.0),
                -float(r.get("rerank_score_norm") or -1.0),
                -float(r.get("retrieval_score_norm") or 0.0),
                int(r.get("idx") or 0),
            ),
        )

        moved = sum(1 for i, r in enumerate(rows_sorted) if int(r.get("idx") or 0) != i)
        top_changed = bool(rows_sorted) and int(rows_sorted[0].get("idx") or 0) != 0

        out_docs: list[Document] = []
        for r in rows_sorted:
            meta = dict(r.get("meta") or {})
            calibrated = float(r.get("calibrated_score") or 0.0)
            meta["rerank_score_calibrated"] = round(calibrated, 6)
            meta["score"] = float(calibrated)
            doc = r.get("doc")
            if isinstance(doc, Document):
                out_docs.append(
                    Document(
                        page_content=doc.page_content,
                        metadata=meta,
                        id=getattr(doc, "id", None) or meta.get("chunk_id"),
                    )
                )

        post_rerank_score_calibration_used = True
        post_rerank_score_calibration_stats.update(
            {
                "used": True,
                "applied_docs": int(len(rows)),
                "eligible_docs": int(len(ranked_rows)),
                "moved_positions": int(moved),
                "top_changed": bool(top_changed),
            }
        )
        return out_docs

    try:
        if post_rerank_enabled and not (docs or []):
            post_rerank_skip_reason = "no_candidates"
        if post_rerank_enabled and (docs or []):
            provider = str(getattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "") or "ltr").strip().lower()
            post_rerank_provider = provider
            if provider in ("none", "off", "false", "0"):
                post_rerank_skip_reason = "provider_off"
            else:
                top_n = int(getattr(settings, "EVIDENCE_POST_RERANK_TOP_N", 0) or 0)
                if top_n <= 0:
                    top_n = len(docs or [])
                top_n = min(int(top_n), len(docs or []))

                if post_rerank_pipeline_enabled:
                    post_rerank_pipeline = _safe_post_rerank_pipeline_summary(post_rerank_pipeline_raw)

                # Pipeline mode: sequential stages with per-stage top_n budgets.
                if post_rerank_pipeline:
                    post_rerank_pipeline_used = True
                    docs_work: List[Document] = list(docs or [])
                    total_elapsed = 0.0
                    prev_n: int | None = None
                    final_provider: str | None = None
                    final_model_used: str | None = None
                    final_n: int = 0

                    for i, st in enumerate(post_rerank_pipeline):
                        st_provider = str(st.get("provider") or "").strip().lower()
                        if not st_provider or st_provider in ("none", "off", "false", "0"):
                            continue

                        st_top_n = st.get("top_n")
                        try:
                            st_n = int(st_top_n) if st_top_n is not None else 0
                        except Exception:
                            st_n = 0
                        if st_n <= 0:
                            st_n = int(prev_n or top_n)
                        if prev_n is not None:
                            st_n = min(int(st_n), int(prev_n))
                        st_n = min(int(st_n), len(docs_work))
                        if st_n <= 0:
                            continue

                        candidates: List[RerankCandidate] = []
                        id_to_doc: Dict[str, Document] = {}
                        for doc in docs_work[:st_n]:
                            rid = _doc_key(doc)
                            text = (doc.page_content or "").strip()
                            if not rid or not text:
                                continue
                            meta = dict(doc.metadata or {})
                            candidates.append(RerankCandidate(id=rid, text=text, metadata=meta))
                            id_to_doc[rid] = doc

                        if not candidates:
                            continue

                        cache_hit = False
                        cache_key: str | None = None
                        rr = None
                        if post_rerank_cache_enabled:
                            try:
                                cand_fp = fingerprint_rerank_candidates(candidates)
                                cache_key = build_evidence_post_rerank_cache_key(
                                    tenant_id=state.get("tenant_id"),
                                    account_id=state.get("account_id"),
                                    provider=st_provider,
                                    top_n=st_n,
                                    query=query_for_retrieval,
                                    candidates_fingerprint=cand_fp,
                                    corpus_cache_token=post_rerank_corpus_cache_token,
                                )
                                rr = get_cached_evidence_post_rerank_result(cache_key)
                                if rr is not None:
                                    cache_hit = True
                                    post_rerank_cache_hits += 1
                                else:
                                    post_rerank_cache_misses += 1
                            except Exception:
                                cache_key = None
                                rr = None

                        if rr is None:
                            reranker = get_reranker(st_provider)
                            rr_start = time.time()
                            rr = reranker.rerank(query=query_for_retrieval, candidates=candidates, top_n=st_n)
                            if post_rerank_cache_enabled and cache_key:
                                try:
                                    set_cached_evidence_post_rerank_result(cache_key, rr)
                                except Exception:
                                    pass
                            elapsed_i = float(rr.elapsed_sec or (time.time() - rr_start))
                        else:
                            elapsed_i = 0.0
                        total_elapsed += elapsed_i

                        used_provider = (rr.provider or st_provider).strip().lower() or st_provider
                        is_final = i == (len(post_rerank_pipeline) - 1)
                        if is_final:
                            final_provider = used_provider
                            final_model_used = rr.model_used
                            final_n = int(st_n)

                        ordered_prefix: List[Document] = []
                        used: set[str] = set()
                        for rid in rr.ordered_ids:
                            doc = id_to_doc.get(rid)
                            if doc is None or rid in used:
                                continue
                            used.add(rid)
                            meta = dict(doc.metadata or {})
                            if is_final:
                                base = meta.get("retrieval_score")
                                if base is None:
                                    base = meta.get("score", 0.0)
                                try:
                                    meta["retrieval_score"] = float(base or 0.0)
                                except Exception:
                                    meta["retrieval_score"] = 0.0
                                if rid in rr.score_map:
                                    meta["rerank_score"] = float(rr.score_map[rid])
                                    meta["score"] = float(rr.score_map[rid])
                                meta["reranker_provider"] = final_provider
                                meta["rerank_elapsed_sec"] = round(float(total_elapsed), 3)
                                meta["rerank_model_used"] = final_model_used
                            ordered_prefix.append(
                                Document(
                                    page_content=doc.page_content,
                                    metadata=meta,
                                    id=getattr(doc, "id", None) or meta.get("chunk_id"),
                                )
                            )

                        # Append candidates not returned by reranker (keep original order).
                        for doc in docs_work[:st_n]:
                            rid = _doc_key(doc)
                            if rid in used:
                                continue
                            meta = dict(doc.metadata or {})
                            if is_final:
                                base = meta.get("retrieval_score")
                                if base is None:
                                    base = meta.get("score", 0.0)
                                try:
                                    meta["retrieval_score"] = float(base or 0.0)
                                except Exception:
                                    meta["retrieval_score"] = 0.0
                                meta.setdefault("reranker_provider", final_provider)
                                meta.setdefault("rerank_elapsed_sec", round(float(total_elapsed), 3))
                                meta.setdefault("rerank_model_used", final_model_used)
                            ordered_prefix.append(
                                Document(
                                    page_content=doc.page_content,
                                    metadata=meta,
                                    id=getattr(doc, "id", None) or meta.get("chunk_id"),
                                )
                            )

                        if is_final:
                            ordered_prefix = _calibrate_post_rerank_prefix(ordered_prefix)
                        docs_work = ordered_prefix + list(docs_work[st_n:])
                        prev_n = int(st_n)
                        post_rerank_pipeline_stages.append(
                            {
                                "provider": used_provider,
                                "top_n": int(st_n),
                                "candidates": int(len(candidates)),
                                "elapsed_sec": round(float(elapsed_i), 3),
                                "model_used": rr.model_used,
                                "cache_hit": bool(cache_hit),
                            }
                        )

                    if final_provider is not None and final_n > 0:
                        docs = docs_work
                        post_rerank_used = True
                        post_rerank_provider = final_provider
                        post_rerank_model_used = final_model_used
                        post_rerank_candidates_n = int(final_n)
                        post_rerank_elapsed = float(total_elapsed)
                    elif post_rerank_skip_reason is None:
                        post_rerank_skip_reason = "pipeline_noop"

                # Single-stage (legacy) behavior: one provider, one top_n.
                if not post_rerank_used:
                    # Budget governance: rerank at least the visible citation prefix (top_k) in
                    # single-stage mode. Pipeline stages can intentionally use smaller prefixes.
                    governed_n = min(int(top_n), len(docs or []))
                    governed_n = max(governed_n, int(top_k or 0))
                    governed_n = min(governed_n, len(docs or []))
                    post_rerank_candidates_n = int(governed_n)

                    candidates: List[RerankCandidate] = []
                    id_to_doc: Dict[str, Document] = {}
                    for doc in (docs or [])[:post_rerank_candidates_n]:
                        rid = _doc_key(doc)
                        text = (doc.page_content or "").strip()
                        if not rid or not text:
                            continue
                        meta = dict(doc.metadata or {})
                        candidates.append(RerankCandidate(id=rid, text=text, metadata=meta))
                        id_to_doc[rid] = doc

                    if candidates:
                        cache_hit = False
                        cache_key: str | None = None
                        rr = None
                        if post_rerank_cache_enabled:
                            try:
                                cand_fp = fingerprint_rerank_candidates(candidates)
                                cache_key = build_evidence_post_rerank_cache_key(
                                    tenant_id=state.get("tenant_id"),
                                    account_id=state.get("account_id"),
                                    provider=provider,
                                    top_n=post_rerank_candidates_n,
                                    query=query_for_retrieval,
                                    candidates_fingerprint=cand_fp,
                                    corpus_cache_token=post_rerank_corpus_cache_token,
                                )
                                rr = get_cached_evidence_post_rerank_result(cache_key)
                                if rr is not None:
                                    cache_hit = True
                                    post_rerank_cache_hits += 1
                                else:
                                    post_rerank_cache_misses += 1
                            except Exception:
                                cache_key = None
                                rr = None

                        if rr is None:
                            reranker = get_reranker(provider)
                            rr_start = time.time()
                            rr = reranker.rerank(
                                query=query_for_retrieval,
                                candidates=candidates,
                                top_n=post_rerank_candidates_n,
                            )
                            if post_rerank_cache_enabled and cache_key:
                                try:
                                    set_cached_evidence_post_rerank_result(cache_key, rr)
                                except Exception:
                                    pass
                            post_rerank_elapsed = float(rr.elapsed_sec or (time.time() - rr_start))
                        else:
                            post_rerank_elapsed = 0.0

                        post_rerank_model_used = rr.model_used
                        reranker_provider = rr.provider or provider

                        ordered: List[Document] = []
                        used: set[str] = set()
                        for rid in rr.ordered_ids:
                            doc = id_to_doc.get(rid)
                            if doc is None or rid in used:
                                continue
                            used.add(rid)
                            meta = dict(doc.metadata or {})
                            meta["retrieval_score"] = float(meta.get("score", 0.0) or 0.0)
                            if rid in rr.score_map:
                                meta["rerank_score"] = float(rr.score_map[rid])
                                meta["score"] = float(rr.score_map[rid])
                            meta["reranker_provider"] = reranker_provider
                            meta["rerank_elapsed_sec"] = round(float(post_rerank_elapsed), 3)
                            meta["rerank_model_used"] = post_rerank_model_used
                            ordered.append(Document(page_content=doc.page_content, metadata=meta, id=getattr(doc, "id", None) or meta.get("chunk_id")))

                        # Append candidates not returned by reranker (keep original order).
                        for doc in (docs or [])[:post_rerank_candidates_n]:
                            rid = _doc_key(doc)
                            if rid in used:
                                continue
                            meta = dict(doc.metadata or {})
                            meta["retrieval_score"] = float(meta.get("score", 0.0) or 0.0)
                            meta.setdefault("reranker_provider", reranker_provider)
                            meta.setdefault("rerank_elapsed_sec", round(float(post_rerank_elapsed), 3))
                            meta.setdefault("rerank_model_used", post_rerank_model_used)
                            ordered.append(Document(page_content=doc.page_content, metadata=meta, id=getattr(doc, "id", None) or meta.get("chunk_id")))

                        ordered = _calibrate_post_rerank_prefix(ordered)
                        docs = ordered + list((docs or [])[post_rerank_candidates_n:])
                        post_rerank_used = True
                    elif post_rerank_skip_reason is None:
                        post_rerank_skip_reason = "no_candidates"
    except Exception as exc:  # noqa: BLE001
        post_rerank_used = False
        post_rerank_error = str(exc)[:200]
        post_rerank_skip_reason = "error"

    hard_fallback_enabled = bool(retrieval_contract_policy.get("hard_fallback_enabled"))
    hard_fallback_mode = str(retrieval_contract_policy.get("hard_fallback_mode") or "keyword").strip().lower() or "keyword"
    hard_fallback_top_k = max(1, int(retrieval_contract_policy.get("hard_fallback_top_k") or 1))
    hard_fallback_attempted = False
    hard_fallback_used = False
    hard_fallback_error: str | None = None
    hard_fallback_elapsed = 0.0
    hard_fallback_added_docs = 0
    hard_fallback_added_citations = 0
    hard_fallback_retriever_debug: Dict[str, Any] | None = None

    citations = build_citations_from_docs(
        docs,
        retrieval_elapsed_sec=retrieval_elapsed,
        retrieval_mode=request_retrieval_mode,
        query=query_for_retrieval,
    )

    # Deterministic hard fallback (opt-in): when primary retrieval yields no citations,
    # run one bounded fallback pass (typically keyword-first) to reduce false-empty cases.
    if hard_fallback_enabled and not citations:
        hard_fallback_attempted = True
        fb_start = time.time()
        fb_docs: list[Document] = []
        fb_err: str | None = None
        try:
            fallback_update = dict(retriever_update)
            fallback_update.update(
                {
                    "retrieval_mode": hard_fallback_mode,
                    "k": int(hard_fallback_top_k),
                    "enable_reranker": False,
                }
            )
            fallback_retriever = hybrid_retriever.model_copy(update=fallback_update)
            fb_docs = fallback_retriever.invoke(query_for_retrieval) or []
            fb_docs = engine._annotate_docs_with_role(fb_docs, "hard_fallback")  # type: ignore[attr-defined]
            dbg = getattr(fallback_retriever, "_last_debug_metrics", None)
            hard_fallback_retriever_debug = _sanitize_retriever_debug(dbg if isinstance(dbg, dict) else None)
        except Exception as exc:  # noqa: BLE001
            fb_docs = []
            fb_err = str(exc)[:200]

        hard_fallback_elapsed = max(0.0, float(time.time() - fb_start))
        retrieval_elapsed += float(hard_fallback_elapsed)

        retrieval_per_query.append(
            {
                "kind": "hard_fallback",
                "query_chars": len(query_for_retrieval or ""),
                "elapsed_sec": round(float(hard_fallback_elapsed), 3),
                "ok": fb_err is None,
                "retriever_debug": hard_fallback_retriever_debug,
            }
        )
        if fb_err:
            hard_fallback_error = fb_err
            retrieval_errors.append(f"hard_fallback:{fb_err[:160]}")

        if fb_docs:
            seen_keys: set[str] = set()
            merged_docs: list[Document] = []
            for d in (docs or []):
                if d is None:
                    continue
                merged_docs.append(d)
                try:
                    seen_keys.add(_doc_key(d))
                except Exception:
                    continue

            for d in fb_docs:
                if d is None:
                    continue
                try:
                    key = _doc_key(d)
                except Exception:
                    key = None
                if key and key in seen_keys:
                    continue
                if key:
                    seen_keys.add(key)
                merged_docs.append(d)
                hard_fallback_added_docs += 1

            docs = merged_docs
            citations_after = build_citations_from_docs(
                docs,
                retrieval_elapsed_sec=retrieval_elapsed,
                retrieval_mode=request_retrieval_mode,
                query=query_for_retrieval,
            )
            hard_fallback_added_citations = max(0, int(len(citations_after) - len(citations)))
            citations = citations_after
            hard_fallback_used = bool(hard_fallback_added_docs > 0 and citations)

    evidence_span_strict_enabled = bool(retrieval_contract_policy.get("require_evidence_spans"))
    evidence_span_missing_citations = 0
    if evidence_span_strict_enabled and citations:
        filtered_citations: list[dict[str, Any]] = []
        for item in citations:
            if not isinstance(item, dict):
                continue
            start = item.get("evidence_start_char")
            end = item.get("evidence_end_char")
            try:
                start_i = int(start) if start is not None else None
                end_i = int(end) if end is not None else None
            except Exception:
                start_i = None
                end_i = None
            if start_i is None or end_i is None or end_i <= start_i:
                evidence_span_missing_citations += 1
                continue
            filtered_citations.append(item)
        citations = filtered_citations

    coverage = _coverage_proxy_from_citations(citations)

    try:
        parse_quality_low_threshold = float(getattr(settings, "RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD", 0.35) or 0.35)
    except Exception:
        parse_quality_low_threshold = 0.35
    parse_quality_low_threshold = min(1.0, max(0.0, float(parse_quality_low_threshold)))

    try:
        parse_quality_alert_ratio = float(getattr(settings, "RETRIEVAL_PARSE_QUALITY_ALERT_RATIO", 0.5) or 0.5)
    except Exception:
        parse_quality_alert_ratio = 0.5
    parse_quality_alert_ratio = min(1.0, max(0.0, float(parse_quality_alert_ratio)))

    parse_quality_summary = _summarize_parse_quality_risk(
        docs,
        low_threshold=parse_quality_low_threshold,
        alert_ratio=parse_quality_alert_ratio,
    )
    try:
        parse_risk_hardcase_min_low_ratio = float(
            getattr(settings, "RETRIEVAL_PARSE_RISK_HARDCASE_MIN_LOW_RATIO", 0.5) or 0.5
        )
    except Exception:
        parse_risk_hardcase_min_low_ratio = 0.5
    parse_risk_hardcase_min_low_ratio = min(1.0, max(0.0, float(parse_risk_hardcase_min_low_ratio)))

    try:
        parse_risk_hardcase_min_considered = int(
            getattr(settings, "RETRIEVAL_PARSE_RISK_HARDCASE_MIN_CONSIDERED", 3) or 3
        )
    except Exception:
        parse_risk_hardcase_min_considered = 3
    parse_risk_hardcase_min_considered = max(1, int(parse_risk_hardcase_min_considered))

    parse_risk = _classify_parse_risk(
        summary=parse_quality_summary,
        hardcase_min_low_ratio=parse_risk_hardcase_min_low_ratio,
        hardcase_min_considered=parse_risk_hardcase_min_considered,
    )

    metrics = dict(state.get("metrics") or {})
    metrics["retrieval_elapsed_sec"] = round(retrieval_elapsed, 3)
    metrics["retrieval_mode"] = request_retrieval_mode
    metrics["retrieval_mode_requested"] = requested_retrieval_mode
    metrics["retrieval_mode_auto_routed"] = bool(retrieval_mode_routed)
    metrics["retrieval_profile"] = profile_norm or None
    metrics["retrieval_profile_requested"] = (
        str(requested_retrieval_profile).strip().lower() if requested_retrieval_profile is not None else None
    )
    metrics["retrieval_contract_mode"] = retrieval_contract_mode or None
    metrics["retrieval_contract_policy"] = dict(retrieval_contract_policy or {})
    metrics["retrieval_contract_deterministic_recall"] = bool(contract_deterministic_recall)
    metrics["intent_router_enabled"] = bool(intent_router_meta.get("enabled"))
    metrics["intent_router_used"] = bool(intent_router_meta.get("used"))
    metrics["intent_router"] = intent_router_meta
    metrics["retrieval_query_parallelism"] = retrieval_parallelism
    metrics["retrieval_query_count"] = len(retrieval_plan)
    metrics["retrieval_per_query"] = retrieval_per_query[:8]
    metrics["vector_backend"] = settings.VECTOR_BACKEND
    metrics["hard_fallback_enabled"] = bool(hard_fallback_enabled)
    metrics["hard_fallback_attempted"] = bool(hard_fallback_attempted)
    metrics["hard_fallback_used"] = bool(hard_fallback_used)
    metrics["hard_fallback_mode"] = hard_fallback_mode
    metrics["hard_fallback_top_k"] = int(hard_fallback_top_k)
    metrics["hard_fallback_elapsed_sec"] = round(float(hard_fallback_elapsed or 0.0), 3)
    metrics["hard_fallback_added_docs"] = int(hard_fallback_added_docs or 0)
    metrics["hard_fallback_added_citations"] = int(hard_fallback_added_citations or 0)
    metrics["hard_fallback_error"] = hard_fallback_error
    metrics["evidence_span_strict_enabled"] = bool(evidence_span_strict_enabled)
    metrics["evidence_span_missing_citations"] = int(evidence_span_missing_citations or 0)
    if coverage:
        metrics["citation_coverage"] = coverage
    if retrieval_errors:
        metrics["retrieval_errors"] = retrieval_errors[:5]
    empty_diag = _diagnose_empty_retrieval(metrics.get("retrieval_per_query")) if not citations else None
    if not citations and hard_fallback_attempted:
        empty_diag = dict(empty_diag or {})
        reasons = list(empty_diag.get("reasons") or [])
        if "hard_fallback_no_hit" not in reasons:
            reasons.append("hard_fallback_no_hit")
        empty_diag["reasons"] = reasons

        signals = dict(empty_diag.get("signals") or {})
        signals["hard_fallback_attempted"] = 1
        if hard_fallback_error:
            signals["hard_fallback_error"] = 1
        empty_diag["signals"] = signals

        empty_diag["hard_fallback"] = {
            "mode": hard_fallback_mode,
            "top_k": int(hard_fallback_top_k),
            "error": hard_fallback_error,
        }
    if empty_diag:
        metrics["empty_retrieval"] = empty_diag

    metrics["evidence_post_rerank_enabled"] = bool(post_rerank_enabled)
    metrics["evidence_post_rerank_used"] = bool(post_rerank_used)
    metrics["evidence_post_rerank_provider"] = post_rerank_provider
    metrics["evidence_post_rerank_candidates_n"] = int(post_rerank_candidates_n or 0)
    metrics["evidence_post_rerank_elapsed_sec"] = round(float(post_rerank_elapsed or 0.0), 3)
    metrics["evidence_post_rerank_model_used"] = post_rerank_model_used
    metrics["evidence_post_rerank_error"] = post_rerank_error
    metrics["evidence_post_rerank_skip_reason"] = post_rerank_skip_reason
    metrics["evidence_post_rerank_cache_enabled"] = bool(post_rerank_cache_enabled)
    metrics["evidence_post_rerank_cache_backend"] = post_rerank_cache_backend
    metrics["evidence_post_rerank_cache_hits"] = int(post_rerank_cache_hits or 0)
    metrics["evidence_post_rerank_cache_misses"] = int(post_rerank_cache_misses or 0)
    metrics["evidence_post_rerank_pipeline_enabled"] = bool(post_rerank_pipeline_enabled)
    metrics["evidence_post_rerank_pipeline_used"] = bool(post_rerank_pipeline_used)
    metrics["evidence_post_rerank_pipeline_stages"] = post_rerank_pipeline_stages[:4]
    metrics["evidence_post_rerank_score_calibration_enabled"] = bool(post_rerank_score_calibration_enabled)
    metrics["evidence_post_rerank_score_calibration_alpha"] = round(float(post_rerank_score_calibration_alpha), 4)
    metrics["evidence_post_rerank_score_calibration_used"] = bool(post_rerank_score_calibration_used)
    metrics["evidence_post_rerank_score_calibration"] = dict(post_rerank_score_calibration_stats or {})

    metrics["query_rewrite_enabled"] = bool(rewrite_enabled)
    metrics["query_rewrite_strategy_id"] = rewrite_strategy_id
    metrics["query_rewrite_strategy_hash"] = rewrite_strategy_hash
    metrics["rewrite_used"] = bool(rewrite_used)
    metrics["rewrite_elapsed_sec"] = round(rewrite_elapsed, 3)
    metrics["rewrite_model_used"] = rewrite_model_used

    metrics["alias_enabled"] = bool(alias_enabled)
    metrics["alias_used"] = bool(alias_used)
    metrics["alias_count"] = len(alias_queries)
    metrics["alias_elapsed_sec"] = round(alias_elapsed, 3)
    metrics["alias_meta"] = alias_meta

    metrics["dict_enabled"] = bool(dict_meta.get("enabled"))
    metrics["dict_used"] = bool(dict_used)
    metrics["dict_count"] = len(dict_expansions)
    metrics["dict_elapsed_sec"] = round(dict_elapsed, 3)
    metrics["dict_meta"] = dict_meta

    metrics["kg_query_expansion_enabled"] = bool(kg_query_expansion_enabled)
    metrics["kg_query_expansion_used"] = bool(kg_query_expansion_used)
    metrics["kg_query_expansion_entities_total"] = int(kg_query_expansion_entities_total)
    metrics["kg_query_expansion_entities_selected"] = int(kg_query_expansion_entities_selected)
    metrics["kg_query_expansion_query_count"] = int(len(kg_query_expansion_queries))
    metrics["kg_query_expansion_elapsed_sec"] = round(float(kg_query_expansion_elapsed), 3)
    metrics["kg_query_expansion_error"] = kg_query_expansion_error
    metrics["kg_chunk_injection_enabled"] = bool(getattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False))
    metrics["kg_chunks_injected"] = int(kg_chunks_injected or 0)
    metrics["kg_chunk_injection_error"] = kg_chunk_injection_error

    metrics["multi_query_enabled"] = bool(mq_enabled)
    metrics["multi_query_used"] = bool(multi_query_used)
    metrics["multi_query_count"] = len(multi_queries)
    metrics["multi_query_elapsed_sec"] = round(multi_query_elapsed, 3)
    metrics["multi_query_model_used"] = multi_query_model_used
    metrics["multi_query_parse_ok"] = bool(multi_query_parse_meta.get("ok"))
    metrics["multi_query_parse_method"] = multi_query_parse_meta.get("method")
    metrics["multi_query_parse_error"] = multi_query_parse_meta.get("error")
    metrics["multi_query_diversify_enabled"] = bool(mq_diversify_enabled)
    metrics["multi_query_diversify_budget"] = int(mq_diversify_budget or 0) if mq_diversify_enabled else 0
    metrics["multi_query_diversify_used"] = bool(mq_diversify_used)
    metrics["multi_query_diversify_selected_mq"] = int(mq_diversify_selected_mq or 0)
    metrics["multi_query_diversify_selected_non_mq"] = int(mq_diversify_selected_non_mq or 0)
    metrics["multi_query_diversify_fill_from_fused"] = int(mq_diversify_fill_from_fused or 0)

    metrics["hyde_enabled"] = bool(settings.ENABLE_HYDE)
    metrics["hyde_used"] = bool(hyde_used)
    metrics["hyde_elapsed_sec"] = round(hyde_elapsed, 3)
    metrics["hyde_model_used"] = hyde_model_used

    metrics["decompose_enabled"] = bool(settings.ENABLE_QUERY_DECOMPOSITION)
    metrics["decompose_used"] = bool(decompose_used)
    metrics["decompose_count"] = len(sub_questions)
    metrics["decompose_elapsed_sec"] = round(decompose_elapsed, 3)
    metrics["decompose_model_used"] = decompose_model_used
    metrics["decompose_parse_ok"] = bool(decompose_parse_meta.get("ok"))
    metrics["decompose_parse_method"] = decompose_parse_meta.get("method")
    metrics["decompose_parse_error"] = decompose_parse_meta.get("error")
    metrics["parse_quality"] = dict(parse_quality_summary or {})
    metrics["parse_quality_low_threshold"] = float(parse_quality_low_threshold)
    metrics["parse_quality_alert_ratio"] = float(parse_quality_alert_ratio)
    metrics["parse_quality_alert"] = bool((parse_quality_summary or {}).get("alert"))
    metrics["parse_quality_low_ratio"] = float((parse_quality_summary or {}).get("low_ratio") or 0.0)
    metrics["parse_quality_considered"] = int((parse_quality_summary or {}).get("considered") or 0)
    metrics["parse_quality_recommendation"] = (parse_quality_summary or {}).get("recommendation")
    metrics["parse_risk"] = dict(parse_risk or {})
    metrics["parse_risk_level"] = str(parse_risk.get("level") or "unknown")
    metrics["parse_risk_score"] = float(parse_risk.get("score") or 0.0)
    metrics["parse_risk_reason"] = str(parse_risk.get("reason") or "")
    metrics["parse_risk_hardcase_eligible"] = bool(parse_risk.get("hardcase_eligible"))

    # Grounding guard: abstain when evidence is weak/empty.
    strict_visible = bool(
        bool(state.get("visible_evidence_only"))
        or bool(retrieval_contract_policy.get("force_visible_evidence_only"))
    )
    abstain_enabled = bool(settings.RAG_ABSTAIN_ENABLED) or strict_visible or bool(evidence_span_strict_enabled)
    abstain_triggered = False
    abstain_reason: str | None = None
    top_rel = 0.0
    if citations:
        try:
            top_rel = max(float((c.get("relevance_score") if c.get("relevance_score") is not None else c.get("retrieval_score")) or 0.0) for c in citations)
        except Exception:
            top_rel = 0.0

    if abstain_enabled:
        min_citations = max(0, int(settings.RAG_ABSTAIN_MIN_CITATIONS or 0))
        min_top_rel = float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE or 0.0)
        if min_citations > 0 and len(citations) < min_citations:
            abstain_triggered = True
            abstain_reason = "citations_lt_min"
        elif min_top_rel > 0 and top_rel < min_top_rel:
            abstain_triggered = True
            abstain_reason = "top_relevance_lt_min"

    metrics["abstain_enabled"] = bool(abstain_enabled)
    metrics["abstain_triggered"] = bool(abstain_triggered)
    metrics["abstain_reason"] = abstain_reason
    metrics["abstain_min_citations"] = int(settings.RAG_ABSTAIN_MIN_CITATIONS or 0)
    metrics["abstain_min_top_relevance_score"] = float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE or 0.0)
    metrics["visible_evidence_only_enabled"] = bool(strict_visible)
    metrics["visible_evidence_only_requested"] = bool(state.get("visible_evidence_only"))
    metrics["top_relevance_score"] = round(float(top_rel or 0.0), 3)
    if bool(abstain_triggered):
        metrics["abstain_followup"] = build_abstain_followup(reason=abstain_reason, citations=citations)

    hardcase_emit_enabled = bool(getattr(settings, "RETRIEVAL_HARDCASE_EMIT_ENABLED", False))
    if hardcase_emit_enabled and (abstain_triggered or not citations):
        reason = "abstain" if abstain_triggered else "no_citations"
        dedupe_payload = {
            "reason": reason,
            "query_hash": stable_hash(query_for_retrieval),
            "mode": str(request_retrieval_mode or ""),
            "profile": profile_norm or None,
            "cfg_hash": metrics.get("retrieval_config_hash"),
        }
        metrics["hardcase_candidate"] = {
            "schema": "mimirq.hardcase_candidate.v1",
            "reason": reason,
            "query_hash": stable_hash(query_for_retrieval),
            "retrieval_mode": str(request_retrieval_mode or ""),
            "retrieval_profile": profile_norm or None,
            "dedupe_key": stable_hash(json.dumps(dedupe_payload, ensure_ascii=False, sort_keys=True), length=32),
            "ts_ms": int(time.time() * 1000),
        }
    if (
        not isinstance(metrics.get("hardcase_candidate"), dict)
        and bool(getattr(settings, "RETRIEVAL_PARSE_RISK_HARDCASE_EMIT_ENABLED", False))
        and bool(parse_risk.get("hardcase_eligible"))
    ):
        parse_risk_candidate = build_parse_risk_hardcase_candidate(
            query_hash=stable_hash(query_for_retrieval),
            retrieval_mode=str(request_retrieval_mode or ""),
            retrieval_profile=(profile_norm or None),
            retrieval_config_hash=(metrics.get("retrieval_config_hash") if isinstance(metrics, dict) else None),
            parse_risk=parse_risk,
            ts_ms=int(time.time() * 1000),
        )
        if isinstance(parse_risk_candidate, dict):
            metrics["hardcase_candidate"] = parse_risk_candidate

    # Best-effort query_debug payload (bounded, structured).
    query_debug: Dict[str, Any] = {"original": question, "normalized": None, "applied_rules": [], "expansions": [], "contributions": [], "channels": None}
    try:
        norm_text: str | None = None
        applied_rules: list[str] = []
        # Prefer the actual retriever normalization captured for the main query.
        for item in retrieval_per_query:
            if item.get("kind") != "main":
                continue
            dbg = item.get("retriever_debug")
            dbg = dbg if isinstance(dbg, dict) else {}
            ch = dbg.get("channels")
            if isinstance(ch, dict):
                query_debug["channels"] = ch
            qn = dbg.get("query_normalization")
            qn = qn if isinstance(qn, dict) else {}
            norm_text = qn.get("normalized") if isinstance(qn.get("normalized"), str) else None
            ar = qn.get("applied_rules")
            if isinstance(ar, list):
                applied_rules = [str(x) for x in ar if x is not None]
            break
        if not norm_text:
            nq = normalize_query(query_for_retrieval)
            norm_text = nq.normalized_text
            applied_rules = list(nq.applied_rules or [])
        query_debug["normalized"] = norm_text
        query_debug["applied_rules"] = applied_rules[:20]
    except Exception:
        query_debug["normalized"] = query_for_retrieval
        query_debug["applied_rules"] = []

    expansions_dbg: List[Dict[str, Any]] = []
    for q in alias_queries:
        expansions_dbg.append({"kind": "alias", "expanded_text": q, "source_rule_id": "alias", "weight": 1.0})
    for e in dict_expansions:
        if not isinstance(e, dict):
            continue
        item = dict(e)
        item.setdefault("kind", "dict")
        expansions_dbg.append(item)
    for q in kg_query_expansion_queries:
        expansions_dbg.append({"kind": "kgq", "expanded_text": q, "source_rule_id": "kg:entity_name", "weight": 1.0})
    for q in clause_fastlane_queries:
        expansions_dbg.append({"kind": "clause", "expanded_text": q, "source_rule_id": "policy:clause_ref", "weight": 1.0})
    for q in multi_queries:
        expansions_dbg.append({"kind": "mq", "expanded_text": q, "source_rule_id": "llm:multi_query", "weight": 1.0})
    for q in sub_questions:
        expansions_dbg.append({"kind": "subq", "expanded_text": q, "source_rule_id": "llm:decompose", "weight": 1.0})
    if hyde_used and hyde_text:
        expansions_dbg.append({"kind": "hyde", "expanded_text": hyde_text, "source_rule_id": "llm:hyde", "weight": 1.0})
    query_debug["expansions"] = expansions_dbg[:20]
    if kg_query_expansion_entity_names:
        query_debug["kg_entities"] = kg_query_expansion_entity_names[:10]

    try:
        by_role: Dict[str, int] = {}
        for c in citations:
            if not isinstance(c, dict):
                continue
            role = str(c.get("retrieval_role") or "main").strip() or "main"
            by_role[role] = by_role.get(role, 0) + 1
        query_debug["contributions"] = [{"retrieval_role": k, "citations": v} for k, v in sorted(by_role.items(), key=lambda kv: (-kv[1], kv[0]))]
    except Exception:
        query_debug["contributions"] = []

    query_debug["query_for_retrieval"] = query_for_retrieval
    query_debug["rewrite_used"] = bool(rewrite_used)
    query_debug["retrieval_profile"] = profile_norm or None
    query_debug["retrieval_profile_requested"] = (
        str(requested_retrieval_profile).strip().lower() if requested_retrieval_profile is not None else None
    )
    query_debug["intent_router"] = intent_router_meta
    query_debug["parse_quality"] = {
        "considered": int((parse_quality_summary or {}).get("considered") or 0),
        "low_ratio": float((parse_quality_summary or {}).get("low_ratio") or 0.0),
        "alert": bool((parse_quality_summary or {}).get("alert")),
        "recommendation": (parse_quality_summary or {}).get("recommendation"),
    }
    if empty_diag:
        query_debug["empty_retrieval"] = empty_diag

    # Stable retrieval trace contract (versioned, parseable by downstream systems).
    #
    # Keep this separate from `metrics` (free-form counters) and `query_debug` (best-effort text payloads).
    try:
        variants: Dict[str, int] = {}
        for kind, _q, _r in retrieval_plan:
            k = str(kind or "").strip() or "main"
            variants[k] = int(variants.get(k, 0) or 0) + 1
    except Exception:
        variants = {}

    def _trace_per_query_item(item: Dict[str, Any]) -> Dict[str, Any]:
        kind = str(item.get("kind") or "").strip() or "main"
        q_chars = int(item.get("query_chars") or 0)
        ok = bool(item.get("ok"))
        elapsed = float(item.get("elapsed_sec") or 0.0)
        payload: Dict[str, Any] = {
            "kind": kind,
            "query_chars": q_chars,
            "ok": ok,
            "elapsed_sec": round(elapsed, 3),
        }
        dbg = item.get("retriever_debug")
        if isinstance(dbg, dict):
            # Strip text-y fields (normalized query) to keep this safe as a stable trace object.
            dbg2 = dict(dbg)
            qn = dbg2.get("query_normalization")
            if isinstance(qn, dict):
                qn2 = dict(qn)
                qn2.pop("normalized", None)
                if qn2:
                    dbg2["query_normalization"] = qn2
                else:
                    dbg2.pop("query_normalization", None)
            payload["retriever_debug"] = dbg2
        return payload

    try:
        per_query_trace = [_trace_per_query_item(it) for it in (retrieval_per_query or []) if isinstance(it, dict)]
    except Exception:
        per_query_trace = []

    citations_by_role: Dict[str, int] = {}
    try:
        for c in citations:
            if not isinstance(c, dict):
                continue
            role = str(c.get("retrieval_role") or "main").strip().lower() or "main"
            citations_by_role[role] = int(citations_by_role.get(role, 0) or 0) + 1
    except Exception:
        citations_by_role = {}

    chunk_quality_summary = None
    try:
        chunk_quality_summary = summarize_retrieved_chunk_quality(
            docs,
            max_candidates=min(max(1, int(top_k or 0)), 20),
            max_items=8,
        )
    except Exception:
        chunk_quality_summary = None

    retrieval_trace: Dict[str, Any] = {
        "schema": "mimirq.retrieval_trace_pass.v1",
        "query_for_retrieval_hash": stable_hash(query_for_retrieval),
        "requested_retrieval_mode": str(requested_retrieval_mode or ""),
        "retrieval_mode": str(request_retrieval_mode or ""),
        "retrieval_mode_auto_routed": bool(retrieval_mode_routed),
        "retrieval_profile": profile_norm or None,
        "retrieval_profile_requested": (
            str(requested_retrieval_profile).strip().lower() if requested_retrieval_profile is not None else None
        ),
        "retrieval_contract_mode": retrieval_contract_mode or None,
        "retrieval_contract_policy": dict(retrieval_contract_policy or {}),
        "retrieval_contract_deterministic_recall": bool(contract_deterministic_recall),
        "intent_router": intent_router_meta,
        "hard_fallback": {
            "enabled": bool(hard_fallback_enabled),
            "attempted": bool(hard_fallback_attempted),
            "used": bool(hard_fallback_used),
            "mode": hard_fallback_mode,
            "top_k": int(hard_fallback_top_k),
            "elapsed_sec": round(float(hard_fallback_elapsed or 0.0), 3),
            "added_docs": int(hard_fallback_added_docs or 0),
            "added_citations": int(hard_fallback_added_citations or 0),
            "error": hard_fallback_error,
        },
        "rewrite": {
            "enabled": bool(rewrite_enabled),
            "strategy_id": rewrite_strategy_id,
            "strategy_hash": rewrite_strategy_hash,
            "temperature": rewrite_temperature if rewrite_enabled else None,
            "max_chars": int(rewrite_max_chars or 0) if rewrite_enabled else None,
            "used": bool(rewrite_used),
            "elapsed_sec": round(float(rewrite_elapsed or 0.0), 3),
            "model_used": rewrite_model_used,
        },
        "expansions": {
            "alias": {
                "enabled": bool(alias_enabled),
                "used": bool(alias_used),
                "count": int(len(alias_queries)),
                "elapsed_sec": round(float(alias_elapsed or 0.0), 3),
            },
            "dict": {
                "enabled": bool(dict_meta.get("enabled")),
                "used": bool(dict_used),
                "count": int(len(dict_expansions)),
                "elapsed_sec": round(float(dict_elapsed or 0.0), 3),
            },
            "kg_query": {
                "enabled": bool(kg_query_expansion_enabled),
                "used": bool(kg_query_expansion_used),
                "entities_total": int(kg_query_expansion_entities_total),
                "entities_selected": int(kg_query_expansion_entities_selected),
                "query_count": int(len(kg_query_expansion_queries)),
                "elapsed_sec": round(float(kg_query_expansion_elapsed or 0.0), 3),
                "error": kg_query_expansion_error,
            },
            "clause_fastlane": {
                "used": bool(clause_fastlane_queries),
                "count": int(len(clause_fastlane_queries)),
            },
            "multi_query": {
                "enabled": bool(mq_enabled),
                "used": bool(multi_query_used),
                "count": int(len(multi_queries)),
                "elapsed_sec": round(float(multi_query_elapsed or 0.0), 3),
                "model_used": multi_query_model_used,
                "parse_ok": bool(multi_query_parse_meta.get("ok")),
                "parse_method": multi_query_parse_meta.get("method"),
                "parse_error": multi_query_parse_meta.get("error"),
            },
            "hyde": {
                "enabled": bool(settings.ENABLE_HYDE),
                "used": bool(hyde_used),
                "elapsed_sec": round(float(hyde_elapsed or 0.0), 3),
                "model_used": hyde_model_used,
            },
            "decompose": {
                "enabled": bool(settings.ENABLE_QUERY_DECOMPOSITION),
                "used": bool(decompose_used),
                "count": int(len(sub_questions)),
                "elapsed_sec": round(float(decompose_elapsed or 0.0), 3),
                "model_used": decompose_model_used,
                "parse_ok": bool(decompose_parse_meta.get("ok")),
                "parse_method": decompose_parse_meta.get("method"),
                "parse_error": decompose_parse_meta.get("error"),
            },
        },
        "retrieval": {
            "top_k": int(top_k),
            "score_threshold": float(retriever_update.get("score_threshold") or 0.0),
            "alpha": float(retriever_update.get("alpha") or 0.0),
            "enable_weight_rerank": bool(retriever_update.get("enable_weight_rerank", True)),
            "vector_weight": float(retriever_update.get("vector_weight") or 0.0),
            "keyword_weight": float(retriever_update.get("keyword_weight") or 0.0),
            "channel_fusion_strategy": str(retriever_update.get("fusion_strategy") or "linear"),
            "channel_fusion_budgets": (retriever_update.get("fusion_budgets") if isinstance(retriever_update.get("fusion_budgets"), dict) else None),
            "channel_fusion_min_scores": (retriever_update.get("fusion_min_scores") if isinstance(retriever_update.get("fusion_min_scores"), dict) else None),
            "rrf_k": int(getattr(settings, "RETRIEVAL_RRF_K", 60) or 60),
            "query_parallelism": int(retrieval_parallelism),
            "query_count": int(len(retrieval_plan)),
            "query_variants": variants,
            "per_query": per_query_trace[:8],
            "errors": retrieval_errors[:5],
            "elapsed_sec": round(float(retrieval_elapsed or 0.0), 3),
            "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "") or ""),
        },
        "query_variant_fusion": {
            "strategy": ("rrf" if len(docs_by_query) > 1 else "single"),
            "rrf_k": int(settings.RETRIEVAL_RRF_K or 0) if len(docs_by_query) > 1 else None,
            "multi_query_diversify": {
                "enabled": bool(mq_diversify_enabled),
                "budget": int(mq_diversify_budget or 0) if mq_diversify_enabled else None,
                "used": bool(mq_diversify_used),
                "selected_mq": int(mq_diversify_selected_mq or 0),
                "selected_non_mq": int(mq_diversify_selected_non_mq or 0),
                "fill_from_fused": int(mq_diversify_fill_from_fused or 0),
            },
        },
        "kg_chunk_injection": {
            "enabled": bool(getattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False)),
            "chunks_injected": int(kg_chunks_injected or 0),
            "error": kg_chunk_injection_error,
        },
        "post_rerank": {
            "enabled": bool(post_rerank_enabled),
            "used": bool(post_rerank_used),
            "provider": post_rerank_provider,
            "skip_reason": post_rerank_skip_reason,
            "cache": {
                "enabled": bool(post_rerank_cache_enabled),
                "backend": post_rerank_cache_backend,
                "hits": int(post_rerank_cache_hits or 0),
                "misses": int(post_rerank_cache_misses or 0),
            },
            "pipeline_enabled": bool(post_rerank_pipeline_enabled),
            "pipeline_used": bool(post_rerank_pipeline_used),
            "pipeline": post_rerank_pipeline[:4],
            "pipeline_stages": post_rerank_pipeline_stages[:4],
            "candidates_n": int(post_rerank_candidates_n or 0),
            "elapsed_sec": round(float(post_rerank_elapsed or 0.0), 3),
            "model_used": post_rerank_model_used,
            "score_calibration": dict(post_rerank_score_calibration_stats or {}),
            "error": post_rerank_error,
        },
        "abstain": {
            "enabled": bool(abstain_enabled),
            "triggered": bool(abstain_triggered),
            "reason": abstain_reason,
            "evidence_span_strict_enabled": bool(evidence_span_strict_enabled),
            "evidence_span_missing_citations": int(evidence_span_missing_citations or 0),
            "min_citations": int(settings.RAG_ABSTAIN_MIN_CITATIONS or 0),
            "min_top_relevance_score": float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE or 0.0),
            "top_relevance_score": round(float(top_rel or 0.0), 3),
        },
        "citations": {
            "count": int(len(citations)),
            "by_role": citations_by_role,
            "chunk_quality": chunk_quality_summary,
        },
        "parse_quality": dict(parse_quality_summary or {}),
        "parse_risk": dict(parse_risk or {}),
        "hardcase_candidate": (metrics.get("hardcase_candidate") if isinstance(metrics.get("hardcase_candidate"), dict) else None),
    }

    # Stable retrieval config fingerprint (PII-safe).
    #
    # Goal:
    # - Provide downstream systems a compact way to compare runs across environments
    #   without relying on brittle field-by-field comparisons.
    # - Must not include raw query text, doc ids, dataset ids, or metadata filter contents.
    try:
        retrieval_cfg: Dict[str, Any] = {
            "requested_retrieval_mode": str(requested_retrieval_mode or ""),
            "retrieval_mode": str(request_retrieval_mode or ""),
            "retrieval_mode_auto_routed": bool(retrieval_mode_routed),
            "retrieval_profile": profile_norm or None,
            "top_k": int(top_k),
            "score_threshold": float(retriever_update.get("score_threshold") or 0.0),
            "alpha": float(retriever_update.get("alpha") or 0.0),
            "fusion_strategy": str(retriever_update.get("fusion_strategy") or "linear"),
            "fusion_budgets": (retriever_update.get("fusion_budgets") if isinstance(retriever_update.get("fusion_budgets"), dict) else None),
            "fusion_min_scores": (retriever_update.get("fusion_min_scores") if isinstance(retriever_update.get("fusion_min_scores"), dict) else None),
            "fusion_weights": (retriever_update.get("fusion_weights") if isinstance(retriever_update.get("fusion_weights"), dict) else None),
            "enable_weight_rerank": bool(retriever_update.get("enable_weight_rerank", True)),
            "vector_weight": float(retriever_update.get("vector_weight") or 0.0),
            "keyword_weight": float(retriever_update.get("keyword_weight") or 0.0),
            "mmr_lambda": float(retriever_update.get("mmr_lambda") or 0.0),
            "enable_reranker": bool(retriever_update.get("enable_reranker", False)),
            "reranker_provider": str(retriever_update.get("reranker_provider") or ""),
            "reranker_tier": describe_reranker_provider(
                str(retriever_update.get("reranker_provider") or ""),
                provider_name=str(getattr(settings, "COLBERT_RERANK_PROVIDER", "deterministic") or "deterministic"),
            ).get("tier"),
            "reranker_top_n": int(retriever_update.get("reranker_top_n") or 0),
            "visible_evidence_only": bool(strict_visible),
            # Global retrieval channel toggles (low-cardinality).
            "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "") or ""),
            "bm25_enabled": bool(getattr(settings, "BM25_INDEX_ENABLED", False)),
            "lexical_enabled": bool(getattr(settings, "LEXICAL_DB_TRGM_ENABLED", False)),
            "sparse_enabled": bool(sparse_enabled),
            "sparse_provider": sparse_provider,
            "sparse_index_persist_enabled": bool(getattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", False)),
            "colbert_enabled": bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)),
            "colbert_provider": str(getattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "") or ""),
            "colbert_index_persist_enabled": bool(getattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", False)),
            "colbert_max_docs": int(getattr(settings, "COLBERT_RETRIEVAL_MAX_DOCS", 0) or 0),
            "parent_child_auto_merge_enabled": bool(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_ENABLED", False)),
            "parent_child_auto_merge_mode": str(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_MODE", "") or ""),
            "kg_query_expansion_enabled": bool(getattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False)),
            "kg_chunk_injection_enabled": bool(getattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False)),
            "retrieval_contract_mode": retrieval_contract_mode or None,
            "retrieval_contract_policy": dict(retrieval_contract_policy or {}),
            "retrieval_contract_deterministic_recall": bool(contract_deterministic_recall),
            "retrieval_hard_fallback_enabled": bool(hard_fallback_enabled),
            "retrieval_hard_fallback_mode": hard_fallback_mode,
            "retrieval_hard_fallback_top_k": int(hard_fallback_top_k),
            "retrieval_hardcase_emit_enabled": bool(getattr(settings, "RETRIEVAL_HARDCASE_EMIT_ENABLED", False)),
            "rag_evidence_require_spans_enabled": bool(evidence_span_strict_enabled),
            "retrieval_parse_quality_low_threshold": float(getattr(settings, "RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD", 0.35) or 0.35),
            "retrieval_parse_quality_alert_ratio": float(getattr(settings, "RETRIEVAL_PARSE_QUALITY_ALERT_RATIO", 0.5) or 0.5),
            "evidence_post_rerank_enabled": bool(getattr(settings, "EVIDENCE_POST_RERANK_ENABLED", False)),
            "evidence_post_rerank_provider": str(getattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "") or ""),
            "evidence_post_rerank_top_n": int(getattr(settings, "EVIDENCE_POST_RERANK_TOP_N", 0) or 0),
            "evidence_post_rerank_pipeline_enabled": bool(getattr(settings, "EVIDENCE_POST_RERANK_PIPELINE_ENABLED", False)),
            "evidence_post_rerank_pipeline": _safe_post_rerank_pipeline_summary(getattr(settings, "EVIDENCE_POST_RERANK_PIPELINE", "")),
            "evidence_post_rerank_score_calibration_enabled": bool(
                getattr(settings, "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ENABLED", False)
            ),
            "evidence_post_rerank_score_calibration_alpha": float(
                getattr(settings, "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA", 0.0) or 0.0
            ),
            "multi_query": {
                "enabled": bool(mq_enabled),
                "count": int(mq_n or 0),
                "temperature": float(mq_temp or 0.0),
                "max_chars": int(mq_max_chars or 0),
                "diversify": {
                    "enabled": bool(getattr(settings, "MULTI_QUERY_DIVERSIFY_ENABLED", False)) and bool(mq_enabled),
                    "budget": max(
                        0,
                        min(
                            int(getattr(settings, "MULTI_QUERY_DIVERSIFY_BUDGET", 0) or 0),
                            int(top_k or 0),
                        ),
                    ),
                },
            },
            "query_rewrite": {
                "enabled": bool(rewrite_enabled),
                "strategy_id": rewrite_strategy_id if rewrite_enabled else None,
                "strategy_hash": rewrite_strategy_hash if rewrite_enabled else None,
                "temperature": rewrite_temperature if rewrite_enabled else None,
                "max_chars": int(rewrite_max_chars or 0) if rewrite_enabled else None,
            },
        }

        # Optional: experiment lineage for retrieval config templates.
        #
        # Keep stable keys only (no UUIDs) so retrieval_config_hash is comparable across environments.
        tmpl_raw = state.get("rag_config_template")
        if isinstance(tmpl_raw, dict) and tmpl_raw:
            tmpl_fp: Dict[str, Any] = {}

            key = str(tmpl_raw.get("template_key") or "").strip()
            if key:
                tmpl_fp["template_key"] = key

            try:
                version = int(tmpl_raw.get("version") or 0)
            except Exception:
                version = 0
            if version > 0:
                tmpl_fp["version"] = version

            exp = str(tmpl_raw.get("ab_experiment_key") or "").strip()
            if exp:
                tmpl_fp["ab_experiment_key"] = exp

            var = str(tmpl_raw.get("ab_variant") or "").strip()
            if var:
                tmpl_fp["ab_variant"] = var

            ph = str(tmpl_raw.get("patch_hash") or "").strip()
            if ph:
                tmpl_fp["patch_hash"] = ph

            if tmpl_fp:
                retrieval_cfg["rag_config_template"] = tmpl_fp

        fp = build_retrieval_config_fingerprint(config=retrieval_cfg)
        retrieval_trace["retrieval_config"] = fp
        metrics["retrieval_config_hash"] = fp.get("hash")
        hc = metrics.get("hardcase_candidate")
        if isinstance(hc, dict):
            hc["retrieval_config_hash"] = fp.get("hash")
            if not hc.get("dedupe_key"):
                dedupe_payload = {
                    "reason": hc.get("reason"),
                    "query_hash": hc.get("query_hash"),
                    "mode": hc.get("retrieval_mode"),
                    "profile": hc.get("retrieval_profile"),
                    "cfg_hash": fp.get("hash"),
                }
                hc["dedupe_key"] = stable_hash(
                    json.dumps(dedupe_payload, ensure_ascii=False, sort_keys=True),
                    length=32,
                )
            metrics["hardcase_candidate"] = hc
    except Exception:
        pass

    return {
        **state,
        "query_for_retrieval": query_for_retrieval,
        "docs": docs,
        "citations": citations,
        "metrics": metrics,
        "abstain_triggered": bool(abstain_triggered),
        "abstain_reason": abstain_reason,
        "query_debug": query_debug,
        "retrieval_trace": retrieval_trace,
    }


__all__ = ["run_retrieval"]
