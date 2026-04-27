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

import asyncio
import concurrent.futures
import json
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from app.core.config import settings
from app.core.utils import parse_csv
from app.query.normalize import normalize_query
from app.rag.core.citations import build_citations_from_docs
from app.rag.core.conversation import format_history_text
from app.rag.core.evidence_expectations import (
    DEFAULT_EVIDENCE_ANCHOR_FIELDS,
    evaluate_evidence_anchor_expectations,
    normalize_anchor_fields,
)
from app.rag.core.hashing import stable_hash
from app.rag.core.query_rewrite_strategy import (
    build_query_rewrite_strategy_spec,
    get_query_rewrite_prompt_template,
)
from app.rag.core.retrieval_config_fingerprint import build_retrieval_config_fingerprint
from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides, is_recall_first_profile
from app.rag.core.temporal import (
    apply_recency_boost,
    detect_temporal_intent,
    fetch_document_updated_ts,
)
from app.rag.core.text import (
    build_abstain_followup,
    guess_retrieval_mode,
    normalize_retrieval_mode,
    parse_json_from_text,
    should_rewrite_query,
)
from app.rag.policy.intent_router import route_adaptive_retrieval_overrides, route_intent, route_retrieval_preset
from app.rag.policy.must_recall import (
    MUST_RECALL_FAIL_REASON_TAXONOMY_V1,
    build_must_recall_fail_reasons,
    evaluate_required_source_keys,
    normalize_source_keys,
)
from app.rag.policy.must_recall_auto import (
    infer_expected_source_keys,
    infer_required_anchor_fields,
)
from app.rag.policy.out_of_scope_live_gate import (
    maybe_apply_out_of_scope_live_guard,
    run_default_out_of_scope_live_guard,
)
from app.rag.policy.query_expansion import build_clause_fastlane_queries
from app.rag.policy.recall_obligation import build_must_recall_proof
from app.rag.policy.router_layers import build_router_layers
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
from app.rag.retrieval.contextual_followup import build_contextual_followup_query
from app.rag.retrieval.contract import resolve_retrieval_contract_policy
from app.rag.retrieval.evidence_gap import detect_evidence_gap
from app.rag.retriever import hybrid_retriever
from app.services.chunk_quality_scoring import summarize_retrieved_chunk_quality
from app.services.corpus_cache_tokens import resolve_corpus_cache_token
from app.services.hardcase_discovery_service import (
    build_parse_risk_hardcase_candidate,
    evaluate_parse_risk_auto_enqueue_policy,
)
from app.services.router_prometheus_metrics import observe_router_layers

_CHANNEL_BUDGET_POLICY_SCHEMA_V1 = "mimirq.channel_budget_policy.v1"


def get_rag_engine():  # noqa: ANN201
    """
    Indirection for tests/monkeypatching while keeping module imports lightweight.

    (Many unit tests patch `app.rag.retrieval.orchestrator.get_rag_engine`.)
    """

    from app.rag.engine import get_rag_engine as _get_rag_engine

    return _get_rag_engine()


def _get_langchain_text_pipeline_primitives() -> tuple[Any, Any]:
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    return ChatPromptTemplate, StrOutputParser


def _get_kg_search() -> Any:
    from app.rag.kg.pipeline import kg_search

    return kg_search


async def kg_search(  # noqa: ANN201
    *,
    query: str,
    tenant_id: UUID | None = None,
    document_ids: list[UUID] | None = None,
    dataset_id: UUID | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    """
    Thin wrapper around the KG pipeline search, kept as a module attribute so tests
    can monkeypatch it without importing the KG module.
    """

    fn = _get_kg_search()
    result = await fn(
        query=query,
        tenant_id=tenant_id,
        document_ids=document_ids,
        dataset_id=dataset_id,
        account_id=account_id,
    )
    return result if isinstance(result, dict) else {}


def _build_history_text(history: list[dict[str, str]] | None) -> str:
    """Compress history to readable text, keep only within window."""
    return format_history_text(history, window=settings.CHAT_HISTORY_WINDOW)


def _decompose_query(query_for_retrieval: str, engine: Any) -> tuple[list[str], float, str | None, dict[str, Any]]:
    decompose_elapsed = 0.0
    decompose_model_used = None
    decompose_parse_meta: dict[str, Any] = {"ok": False, "method": None, "error": None}
    sub_questions: list[str] = []

    dq_n = max(0, min(int(settings.QUERY_DECOMPOSITION_MAX_SUBQUESTIONS or 0), 8))
    dq_min_chars = max(0, int(settings.QUERY_DECOMPOSITION_MIN_CHARS or 0))
    dq_max_chars = max(0, int(settings.QUERY_DECOMPOSITION_MAX_CHARS or 0))
    if not (
        bool(settings.ENABLE_QUERY_DECOMPOSITION)
        and dq_n > 0
        and len(query_for_retrieval) >= dq_min_chars
        and (dq_max_chars <= 0 or len(query_for_retrieval) <= dq_max_chars)
    ):
        return sub_questions, decompose_elapsed, decompose_model_used, decompose_parse_meta

    from app.rag.core.text import heuristic_decompose_query

    heuristic_fallback_enabled = bool(getattr(settings, "QUERY_DECOMPOSITION_HEURISTIC_FALLBACK_ENABLED", True))
    llm_api_key = str(getattr(settings, "LLM_API_KEY", "") or "").strip()

    if heuristic_fallback_enabled and not llm_api_key:
        sub_questions = heuristic_decompose_query(query_for_retrieval, max_subquestions=dq_n)
        if sub_questions:
            decompose_parse_meta = {"ok": True, "method": "heuristic", "error": None}
        return sub_questions, decompose_elapsed, decompose_model_used, decompose_parse_meta

    dq_llm = engine.models.get("fast") or engine.models.get("default")  # type: ignore[attr-defined]
    decompose_model_used = getattr(dq_llm, "model_name", None) or getattr(dq_llm, "model", None)
    try:
        _, str_output_parser_cls = _get_langchain_text_pipeline_primitives()
        dq_chain = (
            engine.decompose_prompt  # type: ignore[attr-defined]
            | dq_llm.bind(temperature=settings.QUERY_DECOMPOSITION_TEMPERATURE)
            | str_output_parser_cls()
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
                if not q or q == query_for_retrieval or q in seen:
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

    return sub_questions, decompose_elapsed, decompose_model_used, decompose_parse_meta


def _sanitize_retriever_debug(dbg: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Shrink retriever debug payloads for API responses / metrics.

    Rationale:
    - Debug payloads may include large generated queries (HyDE) and verbose internal stats.
    - Evidence API returns metrics to downstream systems; keep payloads bounded and avoid leaking scope identifiers.
    """
    if not isinstance(dbg, dict) or not dbg:
        return None

    out: dict[str, Any] = {}
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
        div_out: dict[str, int] = {}
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


def _resolve_hierarchy_family_collapse_key(meta: dict[str, Any]) -> str:
    for k in ("hierarchy_family_key", "parent_id", "parent_node_id"):
        v = meta.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _doc_base_score(meta: dict[str, Any]) -> float:
    for k in ("query_expansion_base_score", "retrieval_score", "score"):
        v = meta.get(k)
        if v is None:
            continue
        try:
            return float(v or 0.0)
        except Exception:
            continue
    return 0.0


def _build_hierarchy_family_features(docs_by_query: list[list[Document]]) -> dict[str, dict[str, Any]]:
    """
    Aggregate family-level features across query variants (PII-safe; does not return ids in outputs).
    """
    variant_hits: dict[str, int] = {}
    doc_hits: dict[str, int] = {}
    best_rank: dict[str, int] = {}
    best_score: dict[str, float] = {}

    for docs_i in docs_by_query or []:
        seen_in_variant: set[str] = set()
        for rank, d in enumerate(docs_i or [], 1):
            meta = d.metadata or {}
            family_key = _resolve_hierarchy_family_collapse_key(meta)
            if not family_key:
                continue
            seen_in_variant.add(family_key)
            doc_hits[family_key] = int(doc_hits.get(family_key, 0) or 0) + 1
            if family_key not in best_rank or rank < int(best_rank.get(family_key) or 0):
                best_rank[family_key] = int(rank)
            score = _doc_base_score(meta)
            if family_key not in best_score or float(score) > float(best_score.get(family_key) or 0.0):
                best_score[family_key] = float(score)
        for fk in seen_in_variant:
            variant_hits[fk] = int(variant_hits.get(fk, 0) or 0) + 1

    out: dict[str, dict[str, Any]] = {}
    all_keys = set(variant_hits) | set(doc_hits) | set(best_rank) | set(best_score)
    for fk in all_keys:
        out[fk] = {
            "variant_hits": int(variant_hits.get(fk, 0) or 0),
            "doc_hits": int(doc_hits.get(fk, 0) or 0),
            "best_rank": int(best_rank.get(fk, 0) or 0),
            "best_score": float(best_score.get(fk, 0.0) or 0.0),
        }
    return out


def _apply_hierarchy_family_aggregation(
    docs: list[Document],
    *,
    family_features: dict[str, dict[str, Any]],
    strategy: str,
) -> tuple[list[Document], dict[str, Any]]:
    if not docs:
        return docs, {"enabled": False, "reason": "no_docs"}
    if not family_features:
        return docs, {"enabled": False, "reason": "no_families"}

    strat = str(strategy or "").strip().lower()
    if strat not in {"frequency", "score", "combined"}:
        return docs, {"enabled": False, "reason": "invalid_strategy"}

    def _family_key(d: Document) -> str:
        meta = d.metadata or {}
        return _resolve_hierarchy_family_collapse_key(meta)

    def _family_sort_key(fk: str) -> tuple[float, float, float, str]:
        feats = family_features.get(fk) if fk else None
        feats = feats if isinstance(feats, dict) else {}
        vhits = int(feats.get("variant_hits") or 0)
        brank = int(feats.get("best_rank") or 0) or 1_000_000
        bscore = float(feats.get("best_score") or 0.0)

        if strat == "frequency":
            return (-float(vhits), float(brank), -float(bscore), fk)
        if strat == "score":
            return (-float(bscore), -float(vhits), float(brank), fk)
        return (-float(vhits), -float(bscore), float(brank), fk)

    before_ids = [str(getattr(d, "id", None) or (d.metadata or {}).get("chunk_id") or "") for d in docs]

    ranked: list[tuple[tuple[float, float, float, str], float, int, str, Document]] = []
    for i, d in enumerate(docs):
        meta = d.metadata or {}
        fk = _family_key(d)
        fam_key = _family_sort_key(fk or "")
        base = _doc_base_score(meta)
        doc_id = str(getattr(d, "id", None) or meta.get("chunk_id") or "")
        ranked.append((fam_key, -float(base), int(i), doc_id, d))

    ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    out_docs = [d for *_rest, d in ranked]

    after_ids = [str(getattr(d, "id", None) or (d.metadata or {}).get("chunk_id") or "") for d in out_docs]
    moved = sum(1 for i, did in enumerate(after_ids) if i < len(before_ids) and did != before_ids[i])
    top_changed = bool(before_ids) and bool(after_ids) and before_ids[0] != after_ids[0]

    return out_docs, {
        "enabled": True,
        "strategy": strat,
        "input_docs": int(len(docs)),
        "families": int(len(family_features)),
        "moved_positions": int(moved),
        "top_changed": bool(top_changed),
    }


def _resolve_hierarchy_node_key(meta: dict[str, Any]) -> str:
    for k in ("hierarchy_node_key", "chunk_key", "chunk_id"):
        v = meta.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _resolve_hierarchy_parent_key(meta: dict[str, Any]) -> str:
    # Respect explicit hierarchy_parent_key=None emitted by chunkers. Only fall back to
    # legacy parent_id fields when the hierarchy_parent_key field is absent entirely.
    raw = meta.get("hierarchy_parent_key") if "hierarchy_parent_key" in meta else (meta.get("parent_id") or meta.get("parent_node_id"))
    s = str(raw or "").strip()
    return s if s else ""


def _apply_hierarchy_tree_dedup(
    primary: list[Document],
    *,
    refill: list[Document] | None,
    top_k: int,
    overfetch_factor: int,
) -> tuple[list[Document], dict[str, Any]]:
    """
    Ancestor-wins tree deduplication for hierarchy-aware retrieval.

    If we see both a node and any of its descendants, prefer the ancestor and drop
    descendants to reclaim context slots (useful when hierarchical chunking returns
    both parent + child content).

    Notes:
    - Best-effort only; bounded by a scan window of `top_k * overfetch_factor`.
    - Keeps survivor order stable (does not reorder; only drops).
    - Uses (hierarchy_node_key, hierarchy_parent_key) as the tree edge.
    """
    primary_list = [d for d in (primary or []) if d is not None]
    if not primary_list:
        return primary_list, {"enabled": False, "reason": "no_primary"}

    try:
        top_k_i = int(top_k or 0)
    except Exception:
        top_k_i = 0
    if top_k_i <= 0:
        return primary_list, {"enabled": False, "reason": "top_k_le_0"}

    try:
        factor = int(overfetch_factor or 1)
    except Exception:
        factor = 1
    factor = max(1, factor)
    max_candidates = max(int(top_k_i), int(top_k_i) * int(factor))

    candidates: list[Document] = list(primary_list)
    if refill:
        candidates.extend([d for d in (refill or []) if d is not None])

    seen_doc_keys: set[str] = set()
    kept_doc_keys: set[str] = set()
    kept_node_keys: set[str] = set()
    order: list[str] = []

    doc_by_key: dict[str, Document] = {}
    node_by_doc_key: dict[str, str] = {}
    parent_by_doc_key: dict[str, str] = {}
    children_by_parent_node: dict[str, set[str]] = {}

    dropped_as_descendant = 0
    removed_by_ancestor = 0
    scanned_unique = 0

    def _remove_doc(doc_key: str) -> int:
        nonlocal removed_by_ancestor
        if doc_key not in kept_doc_keys:
            return 0
        kept_doc_keys.discard(doc_key)
        removed_by_ancestor += 1

        node_key = node_by_doc_key.get(doc_key) or ""
        parent_key = parent_by_doc_key.get(doc_key) or ""

        if parent_key:
            kids = children_by_parent_node.get(parent_key)
            if kids:
                kids.discard(doc_key)
                if not kids:
                    children_by_parent_node.pop(parent_key, None)

        if node_key:
            kept_node_keys.discard(node_key)
            # Recursively remove descendants (handles >2-level trees when present).
            for child_doc_key in children_by_parent_node.get(node_key, set()).copy():
                _remove_doc(child_doc_key)
            children_by_parent_node.pop(node_key, None)
        return 1

    for doc in candidates:
        if doc is None:
            continue
        dk = _doc_key(doc)
        if dk in seen_doc_keys:
            continue
        seen_doc_keys.add(dk)
        scanned_unique += 1
        if scanned_unique > max_candidates:
            break

        meta = doc.metadata or {}
        node_key = _resolve_hierarchy_node_key(meta)
        parent_key = _resolve_hierarchy_parent_key(meta)
        # Guard: some chunkers historically store parent_id=self on parent chunks.
        if parent_key and node_key and parent_key == node_key:
            parent_key = ""

        if parent_key and parent_key in kept_node_keys:
            dropped_as_descendant += 1
            continue

        doc_by_key[dk] = doc
        node_by_doc_key[dk] = node_key
        parent_by_doc_key[dk] = parent_key
        kept_doc_keys.add(dk)
        order.append(dk)
        if node_key:
            kept_node_keys.add(node_key)
        if parent_key:
            children_by_parent_node.setdefault(parent_key, set()).add(dk)

        # If we just kept an ancestor, evict any previously kept descendants.
        if node_key:
            for child_doc_key in children_by_parent_node.get(node_key, set()).copy():
                _remove_doc(child_doc_key)
            if not children_by_parent_node.get(node_key):
                children_by_parent_node.pop(node_key, None)

    out: list[Document] = []
    for dk in order:
        if dk not in kept_doc_keys:
            continue
        d = doc_by_key.get(dk)
        if d is not None:
            out.append(d)

    out_sliced = out[: int(top_k_i)]
    meta_out: dict[str, Any] = {
        "enabled": True,
        "top_k": int(top_k_i),
        "overfetch_factor": int(factor),
        "max_candidates": int(max_candidates),
        "scanned_unique": int(scanned_unique),
        "input_primary": int(len(primary_list)),
        "input_refill": int(len(refill or [])) if refill else 0,
        "output": int(len(out_sliced)),
        "dropped_as_descendant": int(dropped_as_descendant),
        "removed_by_ancestor": int(removed_by_ancestor),
    }
    return out_sliced, meta_out


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


def _sanitize_parse_repair_actions(raw: Any) -> dict[str, Any] | None:
    """
    Normalize parse-repair action payloads into bounded diagnostics.

    Expected input:
    - list[{"document_id", "action", "status", "priority", ...}]
    - {"actions":[...], "scheduler_run_id"/"run_id", "gate_passed", ...}
    """
    if raw is None:
        return None

    payload: dict[str, Any]
    if isinstance(raw, list):
        payload = {"actions": raw}
    elif isinstance(raw, dict):
        payload = dict(raw)
    else:
        return None

    actions = payload.get("actions")
    if not isinstance(actions, list):
        actions = []

    action_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    priority_counts: dict[str, int] = {}
    docs_seen: set[str] = set()
    for item in actions[:200]:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "reparse_document").strip().lower() or "reparse_document"
        status = str(item.get("status") or "scheduled").strip().lower() or "scheduled"
        priority = str(item.get("priority") or "medium").strip().lower() or "medium"
        action_counts[action] = int(action_counts.get(action, 0) + 1)
        status_counts[status] = int(status_counts.get(status, 0) + 1)
        priority_counts[priority] = int(priority_counts.get(priority, 0) + 1)
        doc_id = str(item.get("document_id") or "").strip()
        if doc_id:
            docs_seen.add(doc_id)

    if not action_counts and not status_counts and not priority_counts and not docs_seen:
        return None

    run_id = str(
        payload.get("scheduler_run_id")
        or payload.get("schedule_run_id")
        or payload.get("run_id")
        or ""
    ).strip()
    source = str(payload.get("source") or payload.get("schema") or "").strip()
    gate_passed = payload.get("gate_passed")
    if gate_passed is None:
        gate_passed = payload.get("passed")

    out: dict[str, Any] = {
        "enabled": True,
        "actions_total": int(sum(action_counts.values())),
        "unique_documents": int(len(docs_seen)),
        "action_counts": dict(sorted(action_counts.items(), key=lambda x: x[0])),
        "status_counts": dict(sorted(status_counts.items(), key=lambda x: x[0])),
        "priority_counts": dict(sorted(priority_counts.items(), key=lambda x: x[0])),
        "high_priority_count": int(priority_counts.get("high", 0)),
    }
    if run_id:
        out["run_id"] = run_id[:120]
    if source:
        out["source"] = source[:120]
    if gate_passed is not None:
        out["gate_passed"] = bool(gate_passed)
    return out


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


def _coerce_channel_budgets(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    allowed = {"vector", "bm25", "lexical", "sparse"}
    out: dict[str, int] = {}
    for k, v in raw.items():
        key = str(k or "").strip().lower()
        if not key or key not in allowed:
            continue
        try:
            iv = int(v) if v is not None else 0
        except Exception:
            continue
        out[key] = max(0, int(iv))
    return out


def _coerce_channel_min_scores(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    allowed = {"vector", "bm25", "lexical", "sparse"}
    out: dict[str, float] = {}
    for k, v in raw.items():
        key = str(k or "").strip().lower()
        if not key or key not in allowed:
            continue
        try:
            fv = float(v) if v is not None else 0.0
        except Exception:
            continue
        out[key] = max(0.0, min(1.0, float(fv)))
    return out


def resolve_channel_budget_policy_overrides(
    *,
    policy: dict[str, Any] | None,
    retrieval_mode: str,
    retrieval_profile: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    meta: dict[str, Any] = {"enabled": bool(isinstance(policy, dict)), "used": False}
    if not isinstance(policy, dict):
        meta["reason"] = "policy_missing"
        return {}, meta

    schema = str(policy.get("schema") or "").strip()
    if schema and schema != _CHANNEL_BUDGET_POLICY_SCHEMA_V1:
        meta["reason"] = "schema_mismatch"
        meta["schema"] = schema
        return {}, meta

    profiles = policy.get("profiles") if isinstance(policy.get("profiles"), dict) else {}
    if not profiles:
        meta["reason"] = "profiles_missing"
        return {}, meta

    mode_norm = str(retrieval_mode or "").strip().lower() or "hybrid"
    profile_norm = str(retrieval_profile or "").strip().lower()
    selected_key = ""
    for key in (profile_norm, mode_norm, "default"):
        if not key:
            continue
        entry = profiles.get(key)
        if isinstance(entry, dict):
            selected_key = key
            break
    if not selected_key:
        meta["reason"] = "profile_not_found"
        meta["retrieval_mode"] = mode_norm
        meta["retrieval_profile"] = profile_norm or None
        return {}, meta

    selected = profiles.get(selected_key) if isinstance(profiles.get(selected_key), dict) else {}
    budgets = _coerce_channel_budgets((selected or {}).get("fusion_budgets"))
    if not budgets:
        meta["reason"] = "budgets_missing"
        meta["selected_profile"] = selected_key
        return {}, meta
    min_scores = _coerce_channel_min_scores((selected or {}).get("fusion_min_scores"))
    fusion_strategy = str(
        (selected or {}).get("fusion_strategy") or policy.get("fusion_strategy") or "budgeted_rrf"
    ).strip().lower() or "budgeted_rrf"

    overrides: dict[str, Any] = {
        "fusion_strategy": fusion_strategy,
        "fusion_budgets": budgets,
    }
    if min_scores:
        overrides["fusion_min_scores"] = min_scores

    meta.update(
        {
            "used": True,
            "reason": "applied",
            "selected_profile": selected_key,
            "retrieval_mode": mode_norm,
            "retrieval_profile": profile_norm or None,
            "budget_channels": sorted(budgets.keys()),
            "policy_hash": stable_hash(json.dumps(policy, ensure_ascii=False, sort_keys=True), length=16),
        }
    )
    return overrides, meta


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


def _resolve_post_rerank_corpus_cache_token(state: dict[str, Any]) -> str | None:
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
    for raw in document_ids_raw:
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


def run_retrieval(state: dict[str, Any]) -> dict[str, Any]:
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
    no_retrieval_intent = route_intent(question)
    if bool(no_retrieval_intent.get("skip_retrieval")):
        requested_retrieval_mode = state.get("retrieval_mode", "hybrid") or "hybrid"
        requested_retrieval_profile = state.get("retrieval_profile")
        retrieval_mode = normalize_retrieval_mode(requested_retrieval_mode)
        profile_norm = str(requested_retrieval_profile or "").strip().lower() or None
        metrics = dict(state.get("metrics") or {})
        metrics["retrieval_elapsed_sec"] = 0.0
        metrics["retrieval_mode"] = retrieval_mode
        metrics["retrieval_mode_requested"] = requested_retrieval_mode
        metrics["retrieval_mode_auto_routed"] = False
        metrics["retrieval_profile"] = profile_norm
        metrics["retrieval_profile_requested"] = profile_norm
        metrics["retrieval_bypassed"] = True
        metrics["retrieval_bypass_reason"] = "no_retrieval_intent"
        metrics["retrieval_bypass_intent"] = no_retrieval_intent.get("intent")
        metrics["intent_router_enabled"] = False
        metrics["intent_router_used"] = False

        query_debug: dict[str, Any] = {
            "original": question,
            "normalized": question,
            "applied_rules": [],
            "expansions": [],
            "contributions": [],
            "channels": None,
            "query_for_retrieval": question,
            "rewrite_used": False,
            "retrieval_profile": profile_norm,
            "retrieval_profile_requested": profile_norm,
            "no_retrieval_intent": dict(no_retrieval_intent),
        }
        router_layers = build_router_layers(query=question, intent_meta=dict(no_retrieval_intent))
        query_debug["router_layers"] = router_layers
        observe_router_layers(router_layers)
        retrieval_trace: dict[str, Any] = {
            "schema": "mimirq.retrieval_trace_pass.v1",
            "query_for_retrieval_hash": stable_hash(question),
            "requested_retrieval_mode": str(requested_retrieval_mode or ""),
            "retrieval_mode": str(retrieval_mode or ""),
            "retrieval_mode_auto_routed": False,
            "retrieval_profile": profile_norm,
            "retrieval_profile_requested": profile_norm,
            "intent_router": {"enabled": False, "used": False},
            "adaptive_router": {"enabled": False, "used": False},
            "channel_budget_policy": {"enabled": False, "used": False},
            "router_layers": router_layers,
            "no_retrieval_intent": dict(no_retrieval_intent),
        }
        return {
            **state,
            "query_for_retrieval": question,
            "docs": [],
            "citations": [],
            "metrics": metrics,
            "abstain_triggered": False,
            "abstain_reason": None,
            "query_debug": query_debug,
            "retrieval_trace": retrieval_trace,
        }

    engine = get_rag_engine()

    query_for_retrieval = question
    rewrite_elapsed = 0.0
    rewrite_used = False
    rewrite_model_used = None
    rewrite_strategy_id: str | None = None
    rewrite_strategy_hash: str | None = None
    rewrite_temperature: float | None = None
    rewrite_max_chars: int | None = None
    from app.rag.retrieval.sparse import normalize_sparse_provider_name

    sparse_enabled_override = state.get("sparse_retrieval_enabled")
    sparse_enabled = (
        bool(sparse_enabled_override)
        if sparse_enabled_override is not None
        else bool(getattr(settings, "SPARSE_RETRIEVAL_ENABLED", False))
    )
    sparse_provider_raw = state.get("sparse_retrieval_provider")
    sparse_provider = normalize_sparse_provider_name(
        str(
            sparse_provider_raw
            if sparse_provider_raw is not None
            else (getattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "deterministic") or "deterministic")
        )
    )

    # KG search output can be reused by multiple retrieval steps (query expansion / chunk injection).
    kg_result_cached: dict[str, Any] | None = None
    intent_router_meta: dict[str, Any] = {"enabled": False, "used": False}
    adaptive_router_meta: dict[str, Any] = {"enabled": False, "used": False}
    channel_budget_policy_meta: dict[str, Any] = {"enabled": False, "used": False}
    temporal_intent_enabled = bool(getattr(settings, "RAG_TEMPORAL_INTENT_ENABLED", False))
    temporal_intent_meta: dict[str, Any] = {"detected": False, "reason_codes": []}
    temporal_recency_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}

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
            chat_prompt_template_cls, str_output_parser_cls = _get_langchain_text_pipeline_primitives()
            prompt_template = get_query_rewrite_prompt_template(rewrite_strategy_id)
            rewrite_prompt = chat_prompt_template_cls.from_template(prompt_template)
            rewrite_chain = (
                rewrite_prompt
                | rewrite_llm.bind(temperature=rewrite_temperature)
                | str_output_parser_cls()
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

    if temporal_intent_enabled:
        try:
            temporal_intent_meta = detect_temporal_intent(query_for_retrieval)
        except Exception as exc:  # noqa: BLE001
            temporal_intent_meta = {"detected": False, "reason_codes": [], "error": str(exc)[:200]}

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
    contract_must_recall_strict = bool(retrieval_contract_policy.get("must_recall_strict"))

    must_recall_requested = state.get("must_recall")
    if must_recall_requested is None:
        must_recall_enabled = bool(getattr(settings, "RETRIEVAL_MUST_RECALL_DEFAULT_ENABLED", False))
    else:
        must_recall_enabled = bool(must_recall_requested)
    if contract_must_recall_strict:
        must_recall_enabled = True

    explicit_expected_source_keys = state.get("must_recall_expected_source_keys") is not None
    raw_expected_source_keys = (
        state.get("must_recall_expected_source_keys")
        if explicit_expected_source_keys
        else getattr(settings, "RETRIEVAL_MUST_RECALL_REQUIRED_SOURCE_KEYS", "")
    )
    must_recall_expected_source_keys = normalize_source_keys(raw_expected_source_keys)
    must_recall_auto_expected_source_keys_enabled = bool(
        state.get("must_recall_auto_expected_source_keys_enabled")
        if state.get("must_recall_auto_expected_source_keys_enabled") is not None
        else getattr(settings, "RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_ENABLED", True)
    )
    must_recall_auto_expected_source_keys: list[str] = []
    must_recall_auto_expected_source_keys_reason_codes: list[str] = []
    must_recall_auto_expected_source_keys_confidence = "none"
    must_recall_auto_expected_source_keys_applied = False
    if (
        bool(must_recall_enabled)
        and bool(must_recall_auto_expected_source_keys_enabled)
        and not must_recall_expected_source_keys
        and not explicit_expected_source_keys
    ):
        auto_max_keys = max(1, int(getattr(settings, "RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_MAX", 12) or 12))
        allow_filter = bool(getattr(settings, "RETRIEVAL_MUST_RECALL_AUTO_INFER_FROM_METADATA_FILTER", True))
        meta_filter = state.get("metadata_filter") if allow_filter else None
        scope_payload: dict[str, Any] = {}
        dataset_scope = str(state.get("dataset_id") or "").strip()
        if dataset_scope:
            scope_payload["dataset_id"] = dataset_scope
        raw_doc_scope = state.get("document_ids")
        if isinstance(raw_doc_scope, list):
            scope_payload["document_ids"] = [str(v) for v in raw_doc_scope if str(v or "").strip()][:200]
        raw_table_scope = state.get("table_ids")
        if isinstance(raw_table_scope, list):
            scope_payload["table_ids"] = [str(v) for v in raw_table_scope if str(v or "").strip()][:200]
        inferred = infer_expected_source_keys(
            query=query_for_retrieval,
            metadata_filter=(meta_filter if isinstance(meta_filter, dict) else None),
            scope=(scope_payload if scope_payload else None),
            max_keys=auto_max_keys,
        )
        must_recall_auto_expected_source_keys = normalize_source_keys(list(inferred.get("expected_source_keys") or []))
        must_recall_auto_expected_source_keys_reason_codes = [
            str(v) for v in (inferred.get("reason_codes") or []) if str(v).strip()
        ][:8]
        must_recall_auto_expected_source_keys_confidence = str(inferred.get("confidence") or "none")
        if must_recall_auto_expected_source_keys:
            must_recall_expected_source_keys = must_recall_auto_expected_source_keys
            must_recall_auto_expected_source_keys_applied = True

    explicit_required_anchor_fields = state.get("must_recall_required_anchor_fields") is not None
    raw_required_anchor_fields = (
        state.get("must_recall_required_anchor_fields")
        if explicit_required_anchor_fields
        else getattr(settings, "RETRIEVAL_MUST_RECALL_REQUIRED_ANCHOR_FIELDS", "")
    )
    must_recall_required_anchor_fields = normalize_anchor_fields(raw_required_anchor_fields)
    must_recall_auto_required_anchor_fields_enabled = bool(
        state.get("must_recall_auto_required_anchor_fields_enabled")
        if state.get("must_recall_auto_required_anchor_fields_enabled") is not None
        else getattr(settings, "RETRIEVAL_MUST_RECALL_AUTO_REQUIRED_ANCHOR_FIELDS_ENABLED", True)
    )
    must_recall_auto_required_anchor_fields: list[str] = []
    must_recall_auto_required_anchor_fields_reason_codes: list[str] = []
    must_recall_auto_required_anchor_fields_applied = False
    if bool(must_recall_enabled) and bool(must_recall_auto_required_anchor_fields_enabled):
        inferred_anchor = infer_required_anchor_fields(
            query=query_for_retrieval,
            default_fields=(
                must_recall_required_anchor_fields
                if must_recall_required_anchor_fields
                else list(DEFAULT_EVIDENCE_ANCHOR_FIELDS)
            ),
        )
        must_recall_auto_required_anchor_fields = normalize_anchor_fields(
            list(inferred_anchor.get("required_anchor_fields") or [])
        )
        must_recall_auto_required_anchor_fields_reason_codes = [
            str(v) for v in (inferred_anchor.get("reason_codes") or []) if str(v).strip()
        ][:8]
        if must_recall_auto_required_anchor_fields and (
            bool(inferred_anchor.get("applied")) or not must_recall_required_anchor_fields or not explicit_required_anchor_fields
        ):
            must_recall_required_anchor_fields = must_recall_auto_required_anchor_fields
            must_recall_auto_required_anchor_fields_applied = True
    if not must_recall_required_anchor_fields and must_recall_enabled:
        must_recall_required_anchor_fields = list(DEFAULT_EVIDENCE_ANCHOR_FIELDS)

    must_recall_second_pass_enabled = bool(
        bool(retrieval_contract_policy.get("enable_partial_miss_second_pass"))
        and bool(getattr(settings, "RETRIEVAL_MUST_RECALL_SECOND_PASS_ENABLED", True))
    )
    must_recall_second_pass_mode = str(
        getattr(settings, "RETRIEVAL_MUST_RECALL_SECOND_PASS_MODE", "keyword") or "keyword"
    ).strip().lower() or "keyword"
    must_recall_second_pass_top_k = max(
        int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 1),
        int(getattr(settings, "RETRIEVAL_MUST_RECALL_SECOND_PASS_TOP_K", 80) or 80),
    )
    valid_retrieval_modes = {"hybrid", "vector", "keyword", "mmr"}
    contextual_followup_req = state.get("contextual_followup_enabled")
    contextual_followup_enabled = (
        bool(contextual_followup_req)
        if contextual_followup_req is not None
        else bool(getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_ENABLED", False))
    )
    contextual_followup_mode = str(
        state.get("contextual_followup_mode")
        if state.get("contextual_followup_mode") is not None
        else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE", "keyword") or "keyword")
    ).strip().lower() or "keyword"
    if contextual_followup_mode not in valid_retrieval_modes:
        contextual_followup_mode = "keyword"
    contextual_followup_top_k = max(
        int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 1),
        int(
            state.get("contextual_followup_top_k")
            if state.get("contextual_followup_top_k") is not None
            else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K", 40) or 40)
        ),
    )
    contextual_followup_max_docs = max(
        1,
        int(
            state.get("contextual_followup_max_docs")
            if state.get("contextual_followup_max_docs") is not None
            else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_DOCS", 4) or 4)
        ),
    )
    contextual_followup_max_terms = max(
        0,
        int(
            state.get("contextual_followup_max_terms")
            if state.get("contextual_followup_max_terms") is not None
            else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_TERMS", 4) or 4)
        ),
    )
    contextual_followup_min_term_chars = max(
        2,
        int(
            state.get("contextual_followup_min_term_chars")
            if state.get("contextual_followup_min_term_chars") is not None
            else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MIN_TERM_CHARS", 4) or 4)
        ),
    )
    contextual_followup_max_query_chars = max(
        32,
        int(
            state.get("contextual_followup_max_query_chars")
            if state.get("contextual_followup_max_query_chars") is not None
            else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_QUERY_CHARS", 500) or 500)
        ),
    )
    contextual_followup_max_hops = max(
        1,
        int(
            state.get("contextual_followup_max_hops")
            if state.get("contextual_followup_max_hops") is not None
            else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS", 1) or 1)
        ),
    )
    contextual_followup_latency_budget_ms = max(
        0.0,
        float(
            state.get("contextual_followup_latency_budget_ms")
            if state.get("contextual_followup_latency_budget_ms") is not None
            else (getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS", 500.0) or 500.0)
        ),
    )
    hierarchy_recall_req = state.get("enable_hierarchy_recall")
    hierarchy_recall_enabled = (
        bool(hierarchy_recall_req)
        if hierarchy_recall_req is not None
        else bool(getattr(settings, "HIERARCHY_RECALL_ENABLED", False))
    )
    hierarchy_family_collapse_req = state.get("hierarchy_family_collapse")
    hierarchy_family_collapse = (
        bool(hierarchy_family_collapse_req)
        if hierarchy_family_collapse_req is not None
        else bool(getattr(settings, "HIERARCHY_RECALL_FAMILY_COLLAPSE", False))
    )
    hierarchy_family_aggregation = str(
        state.get("hierarchy_family_aggregation")
        if state.get("hierarchy_family_aggregation") is not None
        else (getattr(settings, "HIERARCHY_RECALL_FAMILY_AGGREGATION", "combined") or "combined")
    ).strip().lower() or "combined"
    if hierarchy_family_aggregation not in {"frequency", "score", "combined"}:
        hierarchy_family_aggregation = "combined"
    hierarchy_tree_dedup_req = state.get("hierarchy_tree_dedup")
    hierarchy_tree_dedup = (
        bool(hierarchy_tree_dedup_req)
        if hierarchy_tree_dedup_req is not None
        else bool(getattr(settings, "HIERARCHY_RECALL_TREE_DEDUP", False))
    )
    hierarchy_parent_depth = max(
        0,
        int(
            state.get("hierarchy_parent_depth")
            if state.get("hierarchy_parent_depth") is not None
            else (getattr(settings, "HIERARCHY_RECALL_PARENT_DEPTH", 0) or 0)
        ),
    )
    hierarchy_sibling_window = max(
        0,
        int(
            state.get("hierarchy_sibling_window")
            if state.get("hierarchy_sibling_window") is not None
            else (getattr(settings, "HIERARCHY_RECALL_SIBLING_WINDOW", 0) or 0)
        ),
    )
    hierarchy_overfetch_factor = max(
        1,
        int(
            state.get("hierarchy_overfetch_factor")
            if state.get("hierarchy_overfetch_factor") is not None
            else (getattr(settings, "HIERARCHY_RECALL_OVERFETCH_FACTOR", 4) or 4)
        ),
    )

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
                learned_router_model=(
                    state.get("intent_router_model") if isinstance(state.get("intent_router_model"), dict) else None
                ),
                learned_router_model_path=(
                    str(state.get("intent_router_model_path") or "").strip()
                    if state.get("intent_router_model_path") is not None
                    else str(getattr(settings, "RAG_INTENT_ROUTER_MODEL_PATH", "") or "").strip()
                ),
                learned_router_confidence_min=float(
                    state.get("intent_router_model_confidence_min")
                    if state.get("intent_router_model_confidence_min") is not None
                    else (getattr(settings, "RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN", 0.7) or 0.7)
                ),
            )
            for k, v in (overrides or {}).items():
                state[k] = v
        except Exception as exc:  # noqa: BLE001
            intent_router_meta = {
                "enabled": True,
                "used": False,
                "error": f"intent_router_exception:{str(exc)[:160]}",
            }

    # Step 0.3: Adaptive retrieval router (optional, policy-driven).
    #
    # This layer lets operators rollout bounded routing overrides from offline artifacts
    # without editing backend code. It is deterministic and uses only low-cardinality signals.
    adaptive_router_req = state.get("adaptive_router")
    adaptive_router_enabled = (
        bool(adaptive_router_req)
        if adaptive_router_req is not None
        else bool(getattr(settings, "RAG_ADAPTIVE_ROUTER_ENABLED", False))
    )
    adaptive_router_meta = {"enabled": bool(adaptive_router_enabled), "used": False}
    if bool(adaptive_router_enabled):
        adaptive_policy = state.get("adaptive_router_policy")
        if not isinstance(adaptive_policy, dict):
            policy_path = str(getattr(settings, "RAG_ADAPTIVE_ROUTER_POLICY_PATH", "") or "").strip()
            if policy_path:
                try:
                    p = Path(policy_path)
                    if p.exists():
                        adaptive_policy = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    adaptive_policy = None
        try:
            adaptive_overrides, adaptive_router_meta = route_adaptive_retrieval_overrides(
                query=query_for_retrieval,
                retrieval_mode=str(state.get("retrieval_mode", "hybrid") or "hybrid"),
                intent_meta=(intent_router_meta if isinstance(intent_router_meta, dict) else None),
                adaptive_router_policy=(adaptive_policy if isinstance(adaptive_policy, dict) else None),
            )
            for k, v in (adaptive_overrides or {}).items():
                state[k] = v
        except Exception as exc:  # noqa: BLE001
            adaptive_router_meta = {
                "enabled": True,
                "used": False,
                "error": f"adaptive_router_exception:{str(exc)[:160]}",
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
    if profile_applied.get("enable_hierarchy_recall") is not None:
        hierarchy_recall_enabled = bool(profile_applied.get("enable_hierarchy_recall"))
    if profile_applied.get("hierarchy_family_collapse") is not None:
        hierarchy_family_collapse = bool(profile_applied.get("hierarchy_family_collapse"))
    if profile_applied.get("hierarchy_family_aggregation") is not None:
        hierarchy_family_aggregation = str(profile_applied.get("hierarchy_family_aggregation") or "combined").strip().lower() or "combined"
    if profile_applied.get("hierarchy_tree_dedup") is not None:
        hierarchy_tree_dedup = bool(profile_applied.get("hierarchy_tree_dedup"))
    if profile_applied.get("hierarchy_parent_depth") is not None:
        hierarchy_parent_depth = max(0, int(profile_applied.get("hierarchy_parent_depth") or 0))
    if profile_applied.get("hierarchy_sibling_window") is not None:
        hierarchy_sibling_window = max(0, int(profile_applied.get("hierarchy_sibling_window") or 0))
    if profile_applied.get("hierarchy_overfetch_factor") is not None:
        hierarchy_overfetch_factor = max(1, int(profile_applied.get("hierarchy_overfetch_factor") or 1))

    explicit_fusion_budgets = state.get("fusion_budgets") if isinstance(state.get("fusion_budgets"), dict) else None
    explicit_fusion_weights = state.get("fusion_weights") if isinstance(state.get("fusion_weights"), dict) else None
    if explicit_fusion_budgets:
        channel_budget_policy_meta = {"enabled": False, "used": False, "reason": "request_fusion_budgets_override"}
    elif explicit_fusion_weights:
        channel_budget_policy_meta = {"enabled": False, "used": False, "reason": "request_fusion_weights_override"}
    else:
        channel_budget_policy = state.get("channel_budget_policy")
        if not isinstance(channel_budget_policy, dict):
            policy_path = str(
                state.get("channel_budget_policy_path")
                or getattr(settings, "RAG_CHANNEL_BUDGET_POLICY_PATH", "")
                or ""
            ).strip()
            if policy_path:
                channel_budget_policy_meta = {"enabled": True, "used": False, "policy_path": policy_path}
                try:
                    policy_file = Path(policy_path)
                    if policy_file.exists():
                        channel_budget_policy = json.loads(policy_file.read_text(encoding="utf-8"))
                    else:
                        channel_budget_policy_meta["reason"] = "policy_file_missing"
                except Exception as exc:  # noqa: BLE001
                    channel_budget_policy = None
                    channel_budget_policy_meta["reason"] = f"policy_file_error:{exc.__class__.__name__}"
        if isinstance(channel_budget_policy, dict):
            overrides, channel_budget_policy_meta = resolve_channel_budget_policy_overrides(
                policy=channel_budget_policy,
                retrieval_mode=str(profile_applied.get("retrieval_mode") or request_retrieval_mode),
                retrieval_profile=(profile_norm or None),
            )
            if overrides:
                for k, v in overrides.items():
                    state[k] = v
    retriever_update: dict[str, Any] = {
        "k": int(profile_applied.get("top_k") or settings.RETRIEVAL_TOP_K),
        "score_threshold": float(profile_applied.get("score_threshold") or 0.0),
        "alpha": state.get("alpha", 0.6),
        "retrieval_profile": profile_norm or None,
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
        "enable_hierarchy_recall": bool(hierarchy_recall_enabled),
        "hierarchy_family_collapse": bool(hierarchy_family_collapse),
        "hierarchy_overfetch_factor": int(hierarchy_overfetch_factor),
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
    alias_meta: dict[str, Any] = {"enabled": False, "used": False}
    alias_queries: list[str] = []

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
    dict_meta: dict[str, Any] = {"enabled": False, "used": False}
    dict_expansions: list[dict[str, Any]] = []
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
    multi_query_parse_meta: dict[str, Any] = {"ok": False, "method": None, "error": None}
    multi_queries: list[str] = []

    mq_enabled = bool(settings.ENABLE_MULTI_QUERY) if state.get("enable_multi_query") is None else bool(state.get("enable_multi_query"))
    mq_n = settings.MULTI_QUERY_COUNT if state.get("multi_query_count") is None else int(state.get("multi_query_count") or 0)
    mq_temp = settings.MULTI_QUERY_TEMPERATURE if state.get("multi_query_temperature") is None else float(state.get("multi_query_temperature") or 0.0)
    mq_max_chars = settings.MULTI_QUERY_MAX_CHARS if state.get("multi_query_max_chars") is None else int(state.get("multi_query_max_chars") or 0)

    mq_cap = max(0, int(getattr(settings, "MULTI_QUERY_COUNT_CAP", 8) or 8))
    mq_n = max(0, min(int(mq_n or 0), int(mq_cap)))
    mq_temp = min(2.0, max(0.0, float(mq_temp or 0.0)))
    mq_max_chars = max(0, int(mq_max_chars or 0))

    if mq_enabled and mq_n > 0 and mq_max_chars > 0 and len(query_for_retrieval) <= mq_max_chars:
        mq_llm = engine.models.get("fast") or engine.models.get("default")  # type: ignore[attr-defined]
        multi_query_model_used = getattr(mq_llm, "model_name", None) or getattr(mq_llm, "model", None)
        try:
            _, str_output_parser_cls = _get_langchain_text_pipeline_primitives()
            mq_chain = (
                engine.multi_query_prompt  # type: ignore[attr-defined]
                | mq_llm.bind(temperature=mq_temp)
                | str_output_parser_cls()
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
            _, str_output_parser_cls = _get_langchain_text_pipeline_primitives()
            hyde_chain = (
                engine.hyde_prompt  # type: ignore[attr-defined]
                | hyde_llm.bind(temperature=settings.HYDE_TEMPERATURE)
                | str_output_parser_cls()
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

    step_back_enabled = bool(getattr(settings, "ENABLE_STEP_BACK_QUERY", False))
    step_back_elapsed = 0.0
    step_back_used = False
    step_back_model_used = None
    step_back_parse_meta: dict[str, Any] = {"ok": False, "method": None, "error": None}
    step_back_query = ""
    step_back_max_chars = max(0, int(getattr(settings, "STEP_BACK_MAX_CHARS", 0) or 0))
    step_back_temp = min(2.0, max(0.0, float(getattr(settings, "STEP_BACK_TEMPERATURE", 0.2) or 0.0)))
    step_back_output_max = max(0, int(getattr(settings, "STEP_BACK_OUTPUT_MAX_CHARS", 0) or 0))
    if step_back_enabled and step_back_max_chars > 0 and len(query_for_retrieval) <= step_back_max_chars:
        sb_llm = engine.models.get("fast") or engine.models.get("default")  # type: ignore[attr-defined]
        step_back_model_used = getattr(sb_llm, "model_name", None) or getattr(sb_llm, "model", None)
        try:
            _, str_output_parser_cls = _get_langchain_text_pipeline_primitives()
            sb_chain = (
                engine.step_back_prompt  # type: ignore[attr-defined]
                | sb_llm.bind(temperature=step_back_temp)
                | str_output_parser_cls()
            )
            sb_start = time.time()
            sb_raw = sb_chain.invoke({"query": query_for_retrieval})
            step_back_elapsed = time.time() - sb_start
            step_back_query = (sb_raw or "").strip().strip('"').strip()
            if step_back_output_max > 0 and len(step_back_query) > step_back_output_max:
                step_back_query = step_back_query[:step_back_output_max] + "..."
            if step_back_query and step_back_query != query_for_retrieval:
                step_back_parse_meta = {"ok": True, "method": "text", "error": None}
            else:
                step_back_query = ""
                step_back_parse_meta = {"ok": False, "method": "text", "error": "empty_or_duplicate"}
        except Exception as exc:  # noqa: BLE001
            step_back_query = ""
            step_back_elapsed = 0.0
            step_back_parse_meta = {"ok": False, "method": None, "error": str(exc)[:200]}
    step_back_used = bool(step_back_query)

    decompose_elapsed = 0.0
    decompose_used = False
    decompose_model_used = None
    decompose_parse_meta: dict[str, Any] = {"ok": False, "method": None, "error": None}
    sub_questions: list[str] = []

    decompose_result = _decompose_query(query_for_retrieval, engine)
    if isinstance(decompose_result, tuple) and len(decompose_result) == 4:
        sub_questions, decompose_elapsed, decompose_model_used, decompose_parse_meta = decompose_result
    elif isinstance(decompose_result, list):
        sub_questions = [str(item).strip() for item in decompose_result if str(item or "").strip()]
        if sub_questions:
            decompose_parse_meta = {"ok": True, "method": "patched", "error": None}

    decompose_used = bool(sub_questions)
    decompose_chain_enabled = bool(getattr(settings, "RAG_DECOMPOSITION_CHAIN_ENABLED", False))
    decompose_chain_requested = bool(decompose_chain_enabled and sub_questions)
    decompose_chain_used = False
    decompose_chain_steps = 0
    decompose_chain_elapsed = 0.0
    decompose_chain_queries: list[str] = []

    retrieval_queries: list[tuple[str, str]] = [("main", query_for_retrieval)]
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
    if step_back_used and step_back_query:
        retrieval_queries.append(("step_back", step_back_query))
    for q in sub_questions:
        retrieval_queries.append(("subq", q))
    if hyde_used and hyde_text:
        retrieval_queries.append(("hyde", hyde_text))

    # Deduplicate query variants (avoid redundant retrieval calls).
    seen_queries: set[str] = set()
    deduped_queries: list[tuple[str, str]] = []
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

    docs_by_query: list[list[Document]] = []
    docs_by_query_kinds: list[str] = []
    retrieval_errors: list[str] = []
    retrieval_per_query: list[dict[str, Any]] = []
    retrieval_parallelism = max(1, int(getattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1) or 1))
    retrieval_plan: list[tuple[str, str, Any]] = []
    for kind, q in retrieval_queries:
        r = retriever
        if kind != "main":
            if kind == "hyde":
                r = retriever.model_copy(update={"enable_reranker": False, "retrieval_mode": "vector", "enable_weight_rerank": False})
            else:
                r = retriever.model_copy(update={"enable_reranker": False})
        retrieval_plan.append((kind, q, r))

    def _invoke_with_timing(kind: str, q: str, r: Any) -> tuple[str, list[Document], str | None, float, dict[str, Any] | None]:
        t0 = time.time()
        try:
            docs_i = r.invoke(q)
            docs_i = engine._annotate_docs_with_role(docs_i or [], kind)  # type: ignore[attr-defined]
            dbg = getattr(r, "_last_debug_metrics", None)
            dbg = _sanitize_retriever_debug(dbg if isinstance(dbg, dict) else None)
            if bool(hierarchy_recall_enabled) and docs_i:
                family_keys: list[str] = []
                for d in docs_i:
                    meta = d.metadata or {}
                    family_key = None
                    for k in ("hierarchy_family_key", "parent_id", "parent_node_id"):
                        v = meta.get(k)
                        if v is None:
                            continue
                        s = str(v).strip()
                        if s:
                            family_key = s
                            break
                    if family_key:
                        family_keys.append(family_key)
                distinct_families = len(set(family_keys)) if family_keys else 0
                duplicate_docs = max(0, len(family_keys) - distinct_families)
                dbg2 = dict(dbg or {})
                dbg2["hierarchy_family"] = {
                    "docs": int(len(docs_i)),
                    "docs_with_key": int(len(family_keys)),
                    "distinct_families": int(distinct_families),
                    "duplicate_docs": int(duplicate_docs),
                }
                dbg = dbg2
            return kind, (docs_i or []), None, time.time() - t0, dbg
        except Exception as exc:  # noqa: BLE001
            return kind, [], str(exc)[:200], time.time() - t0, None

    start = time.time()
    if decompose_chain_requested:
        try:
            from app.rag.retrieval.decomposition_chain import build_chained_query, summarize_chain_step

            chain_start = time.time()
            prior_findings: list[str] = []
            chain_retrieval_mode = str(retriever_update.get("retrieval_mode") or state.get("retrieval_mode") or "hybrid")
            for sub_question in sub_questions:
                chained_query = build_chained_query(sub_question, prior_findings)
                if not chained_query:
                    continue
                decompose_chain_queries.append(chained_query)
                chained_retriever = retriever.model_copy(update={"enable_reranker": False})
                kind, docs_i, err, elapsed_i, dbg = _invoke_with_timing("subq", chained_query, chained_retriever)
                retrieval_per_query.append(
                    {
                        "kind": kind,
                        "query_chars": len(chained_query or ""),
                        "elapsed_sec": round(elapsed_i, 3),
                        "ok": err is None,
                        "retriever_debug": dbg,
                    }
                )
                if err:
                    retrieval_errors.append(f"{kind}:{err[:160]}")
                docs_by_query_kinds.append(kind)
                docs_by_query.append(docs_i or [])

                try:
                    chain_citations = build_citations_from_docs(
                        docs_i or [],
                        retrieval_elapsed_sec=float(elapsed_i or 0.0),
                        retrieval_mode=chain_retrieval_mode,
                        query=chained_query,
                    )
                except Exception:
                    chain_citations = []
                step_summary = summarize_chain_step(chain_citations)
                prior_findings.append(sub_question if not step_summary else f"{sub_question}: {step_summary}")

            decompose_chain_steps = len(decompose_chain_queries)
            decompose_chain_used = decompose_chain_steps > 0
            decompose_chain_elapsed = time.time() - chain_start
            if decompose_chain_used:
                retrieval_plan = [item for item in retrieval_plan if item[0] != "subq"]
        except Exception:
            decompose_chain_used = False
            decompose_chain_steps = 0
            decompose_chain_elapsed = 0.0
            decompose_chain_queries = []

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
    family_aggregation_meta: dict[str, Any] = {"enabled": False, "reason": "not_run"}
    family_features: dict[str, dict[str, Any]] = {}
    tree_dedup_meta: dict[str, Any] = {"enabled": False, "reason": "not_run"}
    family_aggregation_enabled = bool(
        hierarchy_recall_enabled and hierarchy_family_collapse and len(docs_by_query) > 1
    )
    if family_aggregation_enabled:
        try:
            family_features = _build_hierarchy_family_features(docs_by_query)
        except Exception:
            family_features = {}

    docs_refill_pool: list[Document] = docs_by_query[0] if docs_by_query else []
    if len(docs_by_query) <= 1:
        docs = docs_by_query[0] if docs_by_query else []
    else:
        docs_fused_all = engine.fuse_docs_rrf(docs_by_query, rrf_k=settings.RETRIEVAL_RRF_K, meta_prefix="query_expansion")  # type: ignore[attr-defined]
        docs_refill_pool = docs_fused_all
        if family_aggregation_enabled:
            try:
                docs_fused_all, family_aggregation_meta = _apply_hierarchy_family_aggregation(
                    docs_fused_all,
                    family_features=family_features,
                    strategy=hierarchy_family_aggregation,
                )
            except Exception:
                family_aggregation_meta = {"enabled": False, "reason": "exception"}
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
                if family_aggregation_enabled:
                    try:
                        docs_non_mq, _ = _apply_hierarchy_family_aggregation(
                            docs_non_mq,
                            family_features=family_features,
                            strategy=hierarchy_family_aggregation,
                        )
                        docs_mq, _ = _apply_hierarchy_family_aggregation(
                            docs_mq,
                            family_features=family_features,
                            strategy=hierarchy_family_aggregation,
                        )
                    except Exception:
                        pass

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

    # Optional: Temporal intent + recency-aware rerank (deterministic, feature-flagged).
    if temporal_intent_enabled and docs:
        try:
            temporal_boost_enabled = bool(
                getattr(settings, "RAG_TEMPORAL_INTENT_RECENCY_BOOST_ENABLED", True)
            )
            if bool(temporal_intent_meta.get("detected")) and bool(temporal_boost_enabled):
                max_docs = max(0, int(getattr(settings, "RAG_TEMPORAL_INTENT_MAX_DOCS", 200) or 200))
                doc_ids: list[str] = []
                seen_doc_ids: set[str] = set()
                for d in docs:
                    meta = getattr(d, "metadata", None)
                    meta = meta if isinstance(meta, dict) else {}
                    did = meta.get("document_id")
                    did_s = str(did).strip() if did is not None else ""
                    if not did_s:
                        continue
                    if did_s in seen_doc_ids:
                        continue
                    seen_doc_ids.add(did_s)
                    doc_ids.append(did_s)
                    if max_docs and len(doc_ids) >= max_docs:
                        break

                updated_ts = fetch_document_updated_ts(
                    doc_ids,
                    tenant_id=state.get("tenant_id"),
                    dataset_id=state.get("dataset_id"),
                    max_docs=max_docs,
                )
                docs, temporal_recency_meta = apply_recency_boost(
                    docs,
                    updated_ts_by_document_id=updated_ts,
                    boost_max=float(getattr(settings, "RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX", 0.0) or 0.0),
                    window_days=int(getattr(settings, "RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS", 180) or 180),
                )
            else:
                temporal_recency_meta = {
                    "enabled": bool(temporal_boost_enabled),
                    "used": False,
                    "reason": "not_detected",
                }
        except Exception as exc:  # noqa: BLE001
            temporal_recency_meta = {"enabled": True, "used": False, "reason": f"exception:{str(exc)[:160]}"}

    if bool(hierarchy_recall_enabled) and bool(hierarchy_tree_dedup) and docs:
        try:
            docs, tree_dedup_meta = _apply_hierarchy_tree_dedup(
                docs,
                refill=docs_refill_pool,
                top_k=int(top_k),
                overfetch_factor=int(hierarchy_overfetch_factor),
            )
        except Exception:
            tree_dedup_meta = {"enabled": False, "reason": "exception"}

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
    tag_docs: list[Document] = []
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

    def _calibrate_post_rerank_prefix(prefix_docs: list[Document]) -> list[Document]:
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
                    docs_work: list[Document] = list(docs or [])
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

                        candidates: list[RerankCandidate] = []
                        id_to_doc: dict[str, Document] = {}
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
                            rr = reranker.rerank(
                                query=query_for_retrieval,
                                candidates=candidates,
                                top_n=st_n,
                                tenant_id=str(state.get("tenant_id") or "").strip() or None,
                                query_type=str(state.get("query_type") or "").strip() or None,
                            )
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

                        ordered_prefix: list[Document] = []
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

                    candidates: list[RerankCandidate] = []
                    id_to_doc: dict[str, Document] = {}
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
                                tenant_id=str(state.get("tenant_id") or "").strip() or None,
                                query_type=str(state.get("query_type") or "").strip() or None,
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

                        ordered: list[Document] = []
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

    hierarchy_expand_attempted = False
    hierarchy_expand_used = False
    hierarchy_expand_error: str | None = None
    hierarchy_expand_elapsed = 0.0
    hierarchy_expand_meta: dict[str, Any] = {"enabled": False, "reason": "not_run"}
    try:
        if (
            bool(hierarchy_recall_enabled)
            and bool(docs)
            and (int(hierarchy_parent_depth) > 0 or int(hierarchy_sibling_window) > 0)
        ):
            hierarchy_expand_attempted = True
            exp_start = time.time()

            tenant_uuid: UUID | None = None
            try:
                tenant_id_raw = state.get("tenant_id")
                if tenant_id_raw is not None:
                    tenant_uuid = UUID(str(tenant_id_raw))
            except Exception:
                tenant_uuid = None

            from app.rag.retrieval.context_expansion import expand_hierarchy_documents  # noqa: WPS433

            # Version-aware expansion: only fetch hierarchy parents/siblings from the same
            # active pipeline version as the retrieved anchors.
            desired_pipeline_by_doc: dict[str, str] = {}
            for d in docs or []:
                if d is None:
                    continue
                meta = d.metadata or {}
                doc_id = str(meta.get("document_id") or "").strip()
                if not doc_id:
                    continue
                pipeline_key = str(meta.get("doc_pipeline_key") or "").strip()
                if not pipeline_key:
                    ph = str(meta.get("pipeline_hash") or "").strip()
                    if ph:
                        pipeline_key = f"{doc_id}:{ph}"
                if pipeline_key:
                    desired_pipeline_by_doc.setdefault(doc_id, pipeline_key)

            def _fetch_by_key(pairs: set[tuple[str, str]]) -> dict[tuple[str, str], Document]:
                if not pairs:
                    return {}
                from sqlalchemy import or_  # noqa: WPS433

                from app.core.database import SessionLocal  # noqa: WPS433
                from app.models.document import DocumentChunk  # noqa: WPS433

                by_doc: dict[str, set[str]] = {}
                for doc_id, node_key in pairs:
                    doc_id_s = str(doc_id or "").strip()
                    node_key_s = str(node_key or "").strip()
                    if not doc_id_s or not node_key_s:
                        continue
                    by_doc.setdefault(doc_id_s, set()).add(node_key_s)

                if not by_doc:
                    return {}

                db = SessionLocal()
                try:
                    out: dict[tuple[str, str], Document] = {}
                    for doc_id_s, keys in by_doc.items():
                        try:
                            doc_uuid = UUID(doc_id_s)
                        except Exception:
                            continue
                        keys_list = [k for k in keys if k]
                        if not keys_list:
                            continue

                        q = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_uuid)
                        if tenant_uuid is not None:
                            q = q.filter(DocumentChunk.tenant_id == tenant_uuid)
                        q = q.filter(
                            or_(
                                DocumentChunk.doc_metadata["hierarchy_node_key"].astext.in_(keys_list),  # type: ignore[attr-defined]
                                DocumentChunk.doc_metadata["chunk_key"].astext.in_(keys_list),  # type: ignore[attr-defined]
                            )
                        )

                        for ck in q.all():
                            meta = dict(getattr(ck, "doc_metadata", None) or {})
                            desired = desired_pipeline_by_doc.get(str(ck.document_id))
                            if desired:
                                ck_key = str(meta.get("doc_pipeline_key") or "").strip()
                                if not ck_key:
                                    ph = str(meta.get("pipeline_hash") or "").strip()
                                    if ph:
                                        ck_key = f"{ck.document_id}:{ph}"
                                if not ck_key or ck_key != desired:
                                    continue

                            cid = str(getattr(ck, "id", "") or "")
                            meta.setdefault("tenant_id", str(getattr(ck, "tenant_id", "") or ""))
                            meta.setdefault("document_id", str(getattr(ck, "document_id", "") or ""))
                            meta.setdefault("chunk_id", cid)
                            meta.setdefault("chunk_index", int(getattr(ck, "chunk_index", 0) or 0))
                            page_number = getattr(ck, "page_number", None)
                            if page_number is not None:
                                meta.setdefault("page", int(page_number))
                                meta.setdefault("page_number", int(page_number))
                            start_char = getattr(ck, "start_char", None)
                            end_char = getattr(ck, "end_char", None)
                            if start_char is not None:
                                meta.setdefault("start_char", int(start_char))
                            if end_char is not None:
                                meta.setdefault("end_char", int(end_char))
                            if not meta.get("source"):
                                meta["source"] = "unknown"

                            node_key_s = str(meta.get("hierarchy_node_key") or meta.get("chunk_key") or "").strip()
                            if not node_key_s:
                                continue

                            out[(str(ck.document_id), node_key_s)] = Document(
                                page_content=str(getattr(ck, "content", None) or ""),
                                metadata=meta,
                                id=cid or meta.get("chunk_id"),
                            )
                    return out
                finally:
                    try:
                        db.close()
                    except Exception:
                        pass

            max_added = max(0, int(top_k) * (int(hierarchy_parent_depth) + (2 * int(hierarchy_sibling_window))))
            max_added = min(400, max_added or 120)

            expanded_docs, hierarchy_expand_meta = expand_hierarchy_documents(
                [d for d in (docs or []) if d is not None],
                parent_depth=int(hierarchy_parent_depth),
                sibling_window=int(hierarchy_sibling_window),
                fetch_by_key=_fetch_by_key,
                max_added_docs=int(max_added),
            )
            hierarchy_expand_elapsed = max(0.0, float(time.time() - exp_start))
            retrieval_elapsed += float(hierarchy_expand_elapsed)

            if isinstance(hierarchy_expand_meta, dict):
                hierarchy_expand_meta = dict(hierarchy_expand_meta)
            else:
                hierarchy_expand_meta = {"enabled": False, "reason": "invalid_meta"}

            if expanded_docs and int(hierarchy_expand_meta.get("added_docs") or 0) > 0:
                docs = expanded_docs
                hierarchy_expand_used = True
            else:
                hierarchy_expand_used = False
    except Exception as exc:  # noqa: BLE001
        hierarchy_expand_used = False
        hierarchy_expand_error = str(exc)[:200]
        hierarchy_expand_meta = {"enabled": False, "reason": "exception"}

    hard_fallback_enabled = bool(retrieval_contract_policy.get("hard_fallback_enabled"))
    hard_fallback_mode = str(retrieval_contract_policy.get("hard_fallback_mode") or "keyword").strip().lower() or "keyword"
    hard_fallback_top_k = max(1, int(retrieval_contract_policy.get("hard_fallback_top_k") or 1))
    hard_fallback_attempted = False
    hard_fallback_used = False
    hard_fallback_error: str | None = None
    hard_fallback_elapsed = 0.0
    hard_fallback_added_docs = 0
    hard_fallback_added_citations = 0
    hard_fallback_retriever_debug: dict[str, Any] | None = None
    contextual_followup_attempted = False
    contextual_followup_used = False
    contextual_followup_error: str | None = None
    contextual_followup_elapsed = 0.0
    contextual_followup_added_docs = 0
    contextual_followup_added_citations = 0
    contextual_followup_retriever_debug: dict[str, Any] | None = None
    contextual_followup_reason_codes: list[str] = []
    contextual_followup_selected_terms: list[str] = []
    contextual_followup_followup_query: str | None = None
    contextual_followup_query_hash: str | None = None
    iterative_pass_reason_codes: list[str] = []
    iterative_pass_hops: list[dict[str, Any]] = []
    iterative_pass_gap: dict[str, Any] | None = None

    # Deterministic iterative follow-up controller:
    # - gap-aware follow-up query planning
    # - bounded by max_hops + latency budget
    # - does not replace must-recall strict second-pass semantics
    if bool(contextual_followup_enabled) and bool(docs):
        iterative_start = time.time()
        for hop in range(1, int(contextual_followup_max_hops) + 1):
            elapsed_ms = (time.time() - iterative_start) * 1000.0
            if float(contextual_followup_latency_budget_ms) > 0.0 and elapsed_ms >= float(
                contextual_followup_latency_budget_ms
            ):
                iterative_pass_reason_codes.append("latency_budget_exhausted")
                break

            citations_before_contextual = build_citations_from_docs(
                docs,
                retrieval_elapsed_sec=retrieval_elapsed,
                retrieval_mode=request_retrieval_mode,
                query=query_for_retrieval,
            )
            iterative_pass_gap = detect_evidence_gap(
                citations=[c for c in citations_before_contextual if isinstance(c, dict)],
                required_source_keys=(must_recall_expected_source_keys if must_recall_enabled else []),
                required_anchor_fields=(must_recall_required_anchor_fields if must_recall_enabled else []),
                min_citations=1,
            )
            hop_diag: dict[str, Any] = {
                "hop": int(hop),
                "attempted": False,
                "used": False,
                "query_hash": None,
                "added_docs": 0,
                "added_citations": 0,
                "reason_codes": [],
                "gap_before": dict(iterative_pass_gap or {}),
                "gap_after": None,
            }

            spec = build_contextual_followup_query(
                query=query_for_retrieval,
                docs=list(docs or []),
                evidence_gap=iterative_pass_gap,
                max_docs=int(contextual_followup_max_docs),
                max_terms=int(contextual_followup_max_terms),
                min_term_chars=int(contextual_followup_min_term_chars),
                max_query_chars=int(contextual_followup_max_query_chars),
            )
            if not isinstance(spec, dict):
                hop_diag["reason_codes"] = ["planner_spec_invalid"]
                iterative_pass_hops.append(hop_diag)
                iterative_pass_reason_codes.append("planner_spec_invalid")
                break

            hop_reason_codes = [str(v) for v in (spec.get("reason_codes") or []) if str(v).strip()][:8]
            hop_diag["reason_codes"] = hop_reason_codes
            for rc in hop_reason_codes:
                if rc not in contextual_followup_reason_codes:
                    contextual_followup_reason_codes.append(rc)
                if rc not in iterative_pass_reason_codes:
                    iterative_pass_reason_codes.append(rc)

            for term in [str(v) for v in (spec.get("selected_terms") or []) if str(v).strip()]:
                if term not in contextual_followup_selected_terms:
                    contextual_followup_selected_terms.append(term)
                    if len(contextual_followup_selected_terms) >= 10:
                        break

            q2 = str(spec.get("query") or "").strip()
            if q2:
                contextual_followup_followup_query = q2
                contextual_followup_query_hash = stable_hash(q2)
                hop_diag["query_hash"] = contextual_followup_query_hash

            if not (bool(spec.get("used")) and q2):
                hop_diag["reason_codes"] = hop_reason_codes or ["planner_not_used"]
                iterative_pass_hops.append(hop_diag)
                if "planner_not_used" not in iterative_pass_reason_codes:
                    iterative_pass_reason_codes.append("planner_not_used")
                break

            contextual_followup_attempted = True
            hop_diag["attempted"] = True

            t_cf = time.time()
            cf_docs: list[Document] = []
            cf_err: str | None = None
            try:
                contextual_update = dict(retriever_update)
                contextual_update.update(
                    {
                        "retrieval_mode": str(contextual_followup_mode),
                        "k": int(contextual_followup_top_k),
                        "enable_reranker": False,
                    }
                )
                contextual_retriever = hybrid_retriever.model_copy(update=contextual_update)
                cf_docs = contextual_retriever.invoke(q2) or []
                cf_docs = engine._annotate_docs_with_role(cf_docs, "contextual_followup")  # type: ignore[attr-defined]
                dbg = getattr(contextual_retriever, "_last_debug_metrics", None)
                contextual_followup_retriever_debug = _sanitize_retriever_debug(
                    dbg if isinstance(dbg, dict) else None
                )
            except Exception as exc:  # noqa: BLE001
                cf_docs = []
                cf_err = str(exc)[:200]

            hop_elapsed = max(0.0, float(time.time() - t_cf))
            contextual_followup_elapsed += float(hop_elapsed)
            retrieval_elapsed += float(hop_elapsed)
            retrieval_per_query.append(
                {
                    "kind": "contextual_followup",
                    "hop": int(hop),
                    "query_chars": len(q2 or ""),
                    "elapsed_sec": round(float(hop_elapsed), 3),
                    "ok": cf_err is None,
                    "retriever_debug": contextual_followup_retriever_debug,
                }
            )
            if cf_err:
                contextual_followup_error = cf_err
                retrieval_errors.append(f"contextual_followup:{cf_err[:160]}")

            hop_added_docs = 0
            hop_added_citations = 0
            if cf_docs:
                merged_docs = list(docs or [])
                seen_keys: set[str] = set()
                for d in merged_docs:
                    if d is None:
                        continue
                    try:
                        seen_keys.add(_doc_key(d))
                    except Exception:
                        continue

                for d in cf_docs:
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
                    hop_added_docs += 1

                if hop_added_docs > 0:
                    docs = merged_docs
                    citations_after_contextual = build_citations_from_docs(
                        docs,
                        retrieval_elapsed_sec=retrieval_elapsed,
                        retrieval_mode=request_retrieval_mode,
                        query=query_for_retrieval,
                    )
                    hop_added_citations = max(
                        0,
                        int(len(citations_after_contextual) - len(citations_before_contextual)),
                    )
                    contextual_followup_added_docs += int(hop_added_docs)
                    contextual_followup_added_citations += int(hop_added_citations)
                    contextual_followup_used = True

                    iterative_pass_gap = detect_evidence_gap(
                        citations=[c for c in citations_after_contextual if isinstance(c, dict)],
                        required_source_keys=(must_recall_expected_source_keys if must_recall_enabled else []),
                        required_anchor_fields=(must_recall_required_anchor_fields if must_recall_enabled else []),
                        min_citations=1,
                    )
                    hop_diag["gap_after"] = dict(iterative_pass_gap or {})
                    if not bool((iterative_pass_gap or {}).get("has_gap")):
                        if "gap_closed" not in iterative_pass_reason_codes:
                            iterative_pass_reason_codes.append("gap_closed")
                else:
                    hop_diag["reason_codes"] = hop_reason_codes + ["no_new_docs"]
                    if "no_new_docs" not in iterative_pass_reason_codes:
                        iterative_pass_reason_codes.append("no_new_docs")

            hop_diag["used"] = bool(hop_added_docs > 0)
            hop_diag["added_docs"] = int(hop_added_docs)
            hop_diag["added_citations"] = int(hop_added_citations)
            iterative_pass_hops.append(hop_diag)

            if not bool(hop_diag.get("used")):
                break
            if isinstance(hop_diag.get("gap_after"), dict) and not bool((hop_diag.get("gap_after") or {}).get("has_gap")):
                break

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

    # Must-recall contract checks:
    # 1) required source keys are represented in citations
    # 2) required evidence anchor fields exist
    must_recall_source_eval = evaluate_required_source_keys(
        citations=[c for c in citations if isinstance(c, dict)],
        required_source_keys=must_recall_expected_source_keys,
    )
    must_recall_anchor_eval = evaluate_evidence_anchor_expectations(
        citations=[c for c in citations if isinstance(c, dict)],
        required_fields=must_recall_required_anchor_fields,
        exclude_retrieval_role_prefixes=["hierarchy_"],
    )
    initial_missing_source_keys = list(must_recall_source_eval.get("missing_source_keys") or [])
    initial_anchor_missing_any = int(must_recall_anchor_eval.get("missing_any") or 0)
    partial_miss_detected = bool(
        must_recall_enabled
        and (
            bool(initial_missing_source_keys)
            or int(initial_anchor_missing_any or 0) > 0
        )
    )

    must_recall_second_pass_attempted = False
    must_recall_second_pass_used = False
    must_recall_second_pass_error: str | None = None
    must_recall_second_pass_added_docs = 0
    must_recall_second_pass_added_citations = 0
    must_recall_second_pass_diff: dict[str, Any] | None = None

    if partial_miss_detected and must_recall_second_pass_enabled:
        must_recall_second_pass_attempted = True
        before_doc_keys: set[str] = set()
        for d in docs or []:
            if d is None:
                continue
            try:
                before_doc_keys.add(_doc_key(d))
            except Exception:
                continue
        citations_before = list(citations or [])

        fb_docs: list[Document] = []
        try:
            second_pass_update = dict(retriever_update)
            second_pass_update.update(
                {
                    "retrieval_mode": must_recall_second_pass_mode,
                    "k": int(must_recall_second_pass_top_k),
                    "enable_reranker": False,
                }
            )
            second_pass_retriever = hybrid_retriever.model_copy(update=second_pass_update)
            fb_docs = second_pass_retriever.invoke(query_for_retrieval) or []
            fb_docs = engine._annotate_docs_with_role(fb_docs, "must_recall_second_pass")  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            fb_docs = []
            must_recall_second_pass_error = str(exc)[:200]

        if fb_docs:
            merged_docs = list(docs or [])
            seen_keys = set(before_doc_keys)
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
                must_recall_second_pass_added_docs += 1
            docs = merged_docs

            citations_after = build_citations_from_docs(
                docs,
                retrieval_elapsed_sec=retrieval_elapsed,
                retrieval_mode=request_retrieval_mode,
                query=query_for_retrieval,
            )
            must_recall_second_pass_added_citations = max(0, int(len(citations_after) - len(citations_before)))
            citations = citations_after

            after_source_eval = evaluate_required_source_keys(
                citations=[c for c in citations if isinstance(c, dict)],
                required_source_keys=must_recall_expected_source_keys,
            )
            after_anchor_eval = evaluate_evidence_anchor_expectations(
                citations=[c for c in citations if isinstance(c, dict)],
                required_fields=must_recall_required_anchor_fields,
                exclude_retrieval_role_prefixes=["hierarchy_"],
            )
            after_missing_source_keys = list(after_source_eval.get("missing_source_keys") or [])
            after_anchor_missing_any = int(after_anchor_eval.get("missing_any") or 0)

            must_recall_second_pass_used = bool(
                not after_missing_source_keys and int(after_anchor_missing_any) <= 0
            )
            must_recall_second_pass_diff = {
                "before_missing_source_keys": initial_missing_source_keys,
                "after_missing_source_keys": after_missing_source_keys,
                "before_anchor_missing_any": int(initial_anchor_missing_any),
                "after_anchor_missing_any": int(after_anchor_missing_any),
                "before_citations": int(len(citations_before)),
                "after_citations": int(len(citations)),
                "added_docs": int(must_recall_second_pass_added_docs),
                "added_citations": int(must_recall_second_pass_added_citations),
            }

            must_recall_source_eval = after_source_eval
            must_recall_anchor_eval = after_anchor_eval

    missing_source_keys = list(must_recall_source_eval.get("missing_source_keys") or [])
    anchor_missing_any = int(must_recall_anchor_eval.get("missing_any") or 0)
    must_recall_passed = bool(
        (not must_recall_enabled) or (not missing_source_keys and int(anchor_missing_any or 0) <= 0)
    )
    must_recall_fail_reasons = build_must_recall_fail_reasons(
        citations_count=len(citations or []),
        missing_source_keys=missing_source_keys,
        anchor_missing_any=anchor_missing_any,
        second_pass_attempted=must_recall_second_pass_attempted,
        second_pass_used=must_recall_second_pass_used,
    )
    if not must_recall_enabled:
        must_recall_status = "disabled"
    elif must_recall_passed and must_recall_second_pass_attempted:
        must_recall_status = "partial_miss_recovered"
    elif must_recall_passed:
        must_recall_status = "passed"
    else:
        must_recall_status = "failed"
    must_recall_second_pass_payload = {
        "enabled": bool(must_recall_second_pass_enabled),
        "attempted": bool(must_recall_second_pass_attempted),
        "used": bool(must_recall_second_pass_used),
        "mode": str(must_recall_second_pass_mode),
        "top_k": int(must_recall_second_pass_top_k),
        "added_docs": int(must_recall_second_pass_added_docs),
        "added_citations": int(must_recall_second_pass_added_citations),
        "error": must_recall_second_pass_error,
        "diff": (
            dict(must_recall_second_pass_diff)
            if isinstance(must_recall_second_pass_diff, dict)
            else None
        ),
    }
    must_recall_proof = build_must_recall_proof(
        enabled=bool(must_recall_enabled),
        status=str(must_recall_status),
        passed=bool(must_recall_passed),
        required_source_keys=must_recall_expected_source_keys,
        required_anchor_fields=must_recall_required_anchor_fields,
        source_eval=must_recall_source_eval,
        anchor_eval=must_recall_anchor_eval,
        fail_reasons=must_recall_fail_reasons,
        second_pass=must_recall_second_pass_payload,
        contract_fail_reason_taxonomy=str(
            retrieval_contract_policy.get("contract_fail_reason_taxonomy")
            or MUST_RECALL_FAIL_REASON_TAXONOMY_V1
        ),
    )

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
    parse_quality_gate_profile = str(
        getattr(settings, "RETRIEVAL_PARSE_QUALITY_GATE_PROFILE", "warn") or "warn"
    ).strip().lower() or "warn"
    if parse_quality_gate_profile not in {"off", "warn", "strict"}:
        parse_quality_gate_profile = "warn"
    parse_quality_gate_violation = bool((parse_quality_summary or {}).get("alert"))
    parse_quality_gate_blocked = bool(parse_quality_gate_profile == "strict" and parse_quality_gate_violation)
    parse_quality_gate_reason = "parse_quality_alert" if parse_quality_gate_violation else None
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
    parse_repair_actions_input = state.get("parse_repair_actions")
    if parse_repair_actions_input is None:
        alt = state.get("parse_repair_schedule")
        if isinstance(alt, (dict, list)):
            parse_repair_actions_input = alt
    parse_repair_actions_meta = _sanitize_parse_repair_actions(parse_repair_actions_input)

    metrics = dict(state.get("metrics") or {})
    metrics["retrieval_elapsed_sec"] = round(retrieval_elapsed, 3)
    metrics["retrieval_mode"] = request_retrieval_mode
    metrics["retrieval_mode_requested"] = requested_retrieval_mode
    metrics["retrieval_mode_auto_routed"] = bool(retrieval_mode_routed)
    metrics["retrieval_profile"] = profile_norm or None
    metrics["retrieval_profile_requested"] = (
        str(requested_retrieval_profile).strip().lower() if requested_retrieval_profile is not None else None
    )
    metrics["temporal_intent_enabled"] = bool(temporal_intent_enabled)
    metrics["temporal_intent_detected"] = bool(temporal_intent_meta.get("detected"))
    metrics["temporal_intent_reason_codes"] = list(temporal_intent_meta.get("reason_codes") or [])
    metrics["temporal_recency_rerank"] = (
        dict(temporal_recency_meta) if isinstance(temporal_recency_meta, dict) else None
    )
    metrics["retrieval_contract_mode"] = retrieval_contract_mode or None
    metrics["retrieval_contract_policy"] = dict(retrieval_contract_policy or {})
    metrics["retrieval_contract_deterministic_recall"] = bool(contract_deterministic_recall)
    metrics["retrieval_contract_must_recall_strict"] = bool(contract_must_recall_strict)
    metrics["contract_fail_reason_taxonomy"] = str(
        retrieval_contract_policy.get("contract_fail_reason_taxonomy")
        or MUST_RECALL_FAIL_REASON_TAXONOMY_V1
    )
    metrics["must_recall_enabled"] = bool(must_recall_enabled)
    metrics["must_recall_requested"] = (
        bool(must_recall_requested) if must_recall_requested is not None else None
    )
    metrics["must_recall_expected_source_keys"] = list(must_recall_expected_source_keys or [])
    metrics["must_recall_required_anchor_fields"] = list(must_recall_required_anchor_fields or [])
    metrics["must_recall_auto_expected_source_keys_enabled"] = bool(
        must_recall_auto_expected_source_keys_enabled
    )
    metrics["must_recall_auto_expected_source_keys_applied"] = bool(
        must_recall_auto_expected_source_keys_applied
    )
    metrics["must_recall_auto_expected_source_keys"] = list(
        must_recall_auto_expected_source_keys or []
    )
    metrics["must_recall_auto_expected_source_keys_reason_codes"] = list(
        must_recall_auto_expected_source_keys_reason_codes or []
    )
    metrics["must_recall_auto_expected_source_keys_confidence"] = str(
        must_recall_auto_expected_source_keys_confidence or "none"
    )
    metrics["must_recall_auto_required_anchor_fields_enabled"] = bool(
        must_recall_auto_required_anchor_fields_enabled
    )
    metrics["must_recall_auto_required_anchor_fields_applied"] = bool(
        must_recall_auto_required_anchor_fields_applied
    )
    metrics["must_recall_auto_required_anchor_fields"] = list(
        must_recall_auto_required_anchor_fields or []
    )
    metrics["must_recall_auto_required_anchor_fields_reason_codes"] = list(
        must_recall_auto_required_anchor_fields_reason_codes or []
    )
    metrics["must_recall_status"] = str(must_recall_status)
    metrics["must_recall_passed"] = bool(must_recall_passed)
    metrics["must_recall_missing_source_keys"] = missing_source_keys[:40]
    metrics["must_recall_anchor_missing_counts"] = dict(must_recall_anchor_eval.get("missing_counts") or {})
    metrics["must_recall_anchor_considered_citations"] = int(must_recall_anchor_eval.get("considered_citations") or 0)
    metrics["must_recall_anchor_skipped_citations"] = int(must_recall_anchor_eval.get("skipped_citations") or 0)
    metrics["must_recall_anchor_skipped_by_role"] = dict(must_recall_anchor_eval.get("skipped_by_role") or {})
    metrics["must_recall_fail_reasons"] = must_recall_fail_reasons[:12]
    metrics["must_recall_second_pass_enabled"] = bool(must_recall_second_pass_enabled)
    metrics["must_recall_second_pass_attempted"] = bool(must_recall_second_pass_attempted)
    metrics["must_recall_second_pass_used"] = bool(must_recall_second_pass_used)
    metrics["must_recall_second_pass_mode"] = str(must_recall_second_pass_mode)
    metrics["must_recall_second_pass_top_k"] = int(must_recall_second_pass_top_k)
    metrics["must_recall_second_pass_added_docs"] = int(must_recall_second_pass_added_docs)
    metrics["must_recall_second_pass_added_citations"] = int(must_recall_second_pass_added_citations)
    metrics["must_recall_second_pass_error"] = must_recall_second_pass_error
    if isinstance(must_recall_second_pass_diff, dict):
        metrics["must_recall_second_pass_diff"] = dict(must_recall_second_pass_diff)
    metrics["must_recall_proof"] = dict(must_recall_proof)
    metrics["contextual_followup_enabled"] = bool(contextual_followup_enabled)
    metrics["contextual_followup_attempted"] = bool(contextual_followup_attempted)
    metrics["contextual_followup_used"] = bool(contextual_followup_used)
    metrics["contextual_followup_mode"] = str(contextual_followup_mode)
    metrics["contextual_followup_top_k"] = int(contextual_followup_top_k)
    metrics["contextual_followup_max_docs"] = int(contextual_followup_max_docs)
    metrics["contextual_followup_max_terms"] = int(contextual_followup_max_terms)
    metrics["contextual_followup_min_term_chars"] = int(contextual_followup_min_term_chars)
    metrics["contextual_followup_added_docs"] = int(contextual_followup_added_docs)
    metrics["contextual_followup_added_citations"] = int(contextual_followup_added_citations)
    metrics["contextual_followup_reason_codes"] = list(contextual_followup_reason_codes or [])
    metrics["contextual_followup_selected_terms"] = list(contextual_followup_selected_terms or [])
    metrics["contextual_followup_query_hash"] = contextual_followup_query_hash
    metrics["contextual_followup_elapsed_sec"] = round(float(contextual_followup_elapsed or 0.0), 3)
    metrics["contextual_followup_error"] = contextual_followup_error
    metrics["iterative_pass_enabled"] = bool(contextual_followup_enabled)
    metrics["iterative_pass_max_hops"] = int(contextual_followup_max_hops)
    metrics["iterative_pass_latency_budget_ms"] = round(float(contextual_followup_latency_budget_ms), 3)
    metrics["iterative_pass_hops_attempted"] = int(
        len([h for h in iterative_pass_hops if isinstance(h, dict) and bool(h.get("attempted"))])
    )
    metrics["iterative_pass_hops_used"] = int(
        len([h for h in iterative_pass_hops if isinstance(h, dict) and bool(h.get("used"))])
    )
    metrics["iterative_pass_reason_codes"] = list(iterative_pass_reason_codes or [])[:16]
    metrics["iterative_pass_gap"] = (dict(iterative_pass_gap or {}) if isinstance(iterative_pass_gap, dict) else None)
    metrics["iterative_pass_hops"] = [
        h
        for h in list(iterative_pass_hops or [])[:5]
        if isinstance(h, dict)
    ]
    metrics["intent_router_enabled"] = bool(intent_router_meta.get("enabled"))
    metrics["intent_router_used"] = bool(intent_router_meta.get("used"))
    intent_router_learned_meta = (
        dict(intent_router_meta.get("learned_router") or {})
        if isinstance(intent_router_meta.get("learned_router"), dict)
        else None
    )
    metrics["intent_router_learned"] = intent_router_learned_meta
    metrics["intent_router_learned_used"] = bool((intent_router_learned_meta or {}).get("used"))
    metrics["intent_router_learned_confidence"] = float((intent_router_learned_meta or {}).get("confidence") or 0.0)
    metrics["intent_router_learned_confidence_gate"] = float(
        (intent_router_learned_meta or {}).get("confidence_gate") or 0.0
    )
    metrics["intent_router_learned_rule_id"] = (intent_router_learned_meta or {}).get("rule_id")
    metrics["intent_router"] = intent_router_meta
    metrics["adaptive_router_enabled"] = bool(adaptive_router_meta.get("enabled"))
    metrics["adaptive_router_used"] = bool(adaptive_router_meta.get("used"))
    metrics["adaptive_router"] = adaptive_router_meta
    metrics["channel_budget_policy_enabled"] = bool(channel_budget_policy_meta.get("enabled"))
    metrics["channel_budget_policy_used"] = bool(channel_budget_policy_meta.get("used"))
    metrics["channel_budget_policy"] = channel_budget_policy_meta
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
    metrics["step_back_enabled"] = bool(step_back_enabled)
    metrics["step_back_used"] = bool(step_back_used)
    metrics["step_back_elapsed_sec"] = round(step_back_elapsed, 3)
    metrics["step_back_model_used"] = step_back_model_used
    metrics["step_back_parse_ok"] = bool(step_back_parse_meta.get("ok"))
    metrics["step_back_parse_method"] = step_back_parse_meta.get("method")
    metrics["step_back_parse_error"] = step_back_parse_meta.get("error")

    metrics["hierarchy_recall_enabled"] = bool(hierarchy_recall_enabled)
    metrics["hierarchy_family_collapse"] = bool(hierarchy_family_collapse)
    metrics["hierarchy_family_aggregation"] = str(hierarchy_family_aggregation)
    metrics["hierarchy_family_aggregation_meta"] = (
        dict(family_aggregation_meta) if isinstance(family_aggregation_meta, dict) else None
    )
    metrics["hierarchy_tree_dedup"] = bool(hierarchy_tree_dedup)
    metrics["hierarchy_tree_dedup_meta"] = (dict(tree_dedup_meta) if isinstance(tree_dedup_meta, dict) else None)
    metrics["hierarchy_parent_depth"] = int(hierarchy_parent_depth)
    metrics["hierarchy_sibling_window"] = int(hierarchy_sibling_window)
    metrics["hierarchy_overfetch_factor"] = int(hierarchy_overfetch_factor)
    metrics["hierarchy_context_expansion_attempted"] = bool(hierarchy_expand_attempted)
    metrics["hierarchy_context_expansion_used"] = bool(hierarchy_expand_used)
    metrics["hierarchy_context_expansion_elapsed_sec"] = round(float(hierarchy_expand_elapsed or 0.0), 3)
    metrics["hierarchy_context_expansion_error"] = hierarchy_expand_error
    metrics["hierarchy_context_expansion_meta"] = (dict(hierarchy_expand_meta) if isinstance(hierarchy_expand_meta, dict) else None)

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
    metrics["decompose_chain_enabled"] = bool(decompose_chain_enabled)
    metrics["decompose_chain_used"] = bool(decompose_chain_used)
    metrics["decompose_chain_steps"] = int(decompose_chain_steps or 0)
    metrics["decompose_chain_elapsed_sec"] = round(float(decompose_chain_elapsed or 0.0), 3)
    metrics["parse_quality"] = dict(parse_quality_summary or {})
    metrics["parse_quality_low_threshold"] = float(parse_quality_low_threshold)
    metrics["parse_quality_alert_ratio"] = float(parse_quality_alert_ratio)
    metrics["parse_quality_alert"] = bool((parse_quality_summary or {}).get("alert"))
    metrics["parse_quality_low_ratio"] = float((parse_quality_summary or {}).get("low_ratio") or 0.0)
    metrics["parse_quality_considered"] = int((parse_quality_summary or {}).get("considered") or 0)
    metrics["parse_quality_recommendation"] = (parse_quality_summary or {}).get("recommendation")
    metrics["parse_quality_gate_profile"] = str(parse_quality_gate_profile)
    metrics["parse_quality_gate_violation"] = bool(parse_quality_gate_violation)
    metrics["parse_quality_gate_blocked"] = bool(parse_quality_gate_blocked)
    metrics["parse_quality_gate_reason"] = parse_quality_gate_reason
    metrics["parse_risk"] = dict(parse_risk or {})
    metrics["parse_risk_level"] = str(parse_risk.get("level") or "unknown")
    metrics["parse_risk_score"] = float(parse_risk.get("score") or 0.0)
    metrics["parse_risk_reason"] = str(parse_risk.get("reason") or "")
    metrics["parse_risk_hardcase_eligible"] = bool(parse_risk.get("hardcase_eligible"))
    metrics["parse_repair_actions"] = (
        dict(parse_repair_actions_meta)
        if isinstance(parse_repair_actions_meta, dict)
        else None
    )
    metrics["parse_repair_actions_enabled"] = bool(isinstance(parse_repair_actions_meta, dict))
    metrics["parse_repair_actions_run_id"] = (
        str(parse_repair_actions_meta.get("run_id") or "")
        if isinstance(parse_repair_actions_meta, dict)
        else ""
    ) or None

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
    if parse_quality_gate_blocked:
        abstain_enabled = True
        if not abstain_triggered:
            abstain_triggered = True
            abstain_reason = "parse_quality_gate_strict"
    if bool(must_recall_enabled) and not bool(must_recall_passed):
        abstain_enabled = True
        if not abstain_triggered:
            abstain_triggered = True
            abstain_reason = "must_recall_failed"

    out_of_scope_guard = maybe_apply_out_of_scope_live_guard(
        query=query_for_retrieval,
        enabled=bool(getattr(settings, "RAG_OUT_OF_SCOPE_LIVE_GUARD_ENABLED", False)),
        candidate=bool(abstain_triggered or not citations),
        current_triggered=bool(abstain_triggered),
        current_reason=abstain_reason,
        tenant_id=(str(state.get("tenant_id") or "").strip() or None),
        dataset_id=(str(state.get("dataset_id") or "").strip() or None),
        verifier=lambda: run_default_out_of_scope_live_guard(
            query=query_for_retrieval,
            tenant_id=str(state.get("tenant_id") or ""),
            dataset_id=str(state.get("dataset_id") or ""),
            ruleset_name=(str(getattr(settings, "RAG_OUT_OF_SCOPE_RULESET", "") or "").strip() or None),
            hyde_query=hyde_text if bool(hyde_used and hyde_text) else None,
            vector_similarity_threshold=float(getattr(settings, "RAG_OUT_OF_SCOPE_VECTOR_THRESHOLD", 0.35) or 0.35),
            hyde_similarity_threshold=float(getattr(settings, "RAG_OUT_OF_SCOPE_HYDE_THRESHOLD", 0.4) or 0.4),
        ),
    )
    abstain_triggered = bool(out_of_scope_guard.get("abstain_triggered"))
    abstain_reason = out_of_scope_guard.get("abstain_reason")

    metrics["abstain_enabled"] = bool(abstain_enabled)
    metrics["abstain_triggered"] = bool(abstain_triggered)
    metrics["abstain_reason"] = abstain_reason
    metrics["out_of_scope_guard_enabled"] = bool(getattr(settings, "RAG_OUT_OF_SCOPE_LIVE_GUARD_ENABLED", False))
    if isinstance(out_of_scope_guard.get("verdict"), dict):
        metrics["out_of_scope_guard"] = dict(out_of_scope_guard.get("verdict") or {})
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
    parse_risk_auto_enqueue_levels = {
        str(x).strip().lower()
        for x in parse_csv(str(getattr(settings, "RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS", "high,medium") or "high,medium"))
        if str(x).strip()
    }
    if not parse_risk_auto_enqueue_levels:
        parse_risk_auto_enqueue_levels = {"high", "medium"}
    try:
        parse_risk_auto_enqueue_min_score = float(
            getattr(settings, "RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_MIN_SCORE", 0.0) or 0.0
        )
    except Exception:
        parse_risk_auto_enqueue_min_score = 0.0
    parse_risk_auto_enqueue_min_score = min(1.0, max(0.0, float(parse_risk_auto_enqueue_min_score)))
    parse_risk_auto_enqueue_policy = evaluate_parse_risk_auto_enqueue_policy(
        parse_risk=parse_risk,
        enabled=bool(getattr(settings, "RETRIEVAL_PARSE_RISK_HARDCASE_EMIT_ENABLED", False)),
        allowed_levels=parse_risk_auto_enqueue_levels,
        min_score=parse_risk_auto_enqueue_min_score,
    )
    metrics["parse_risk_auto_enqueue_policy"] = dict(parse_risk_auto_enqueue_policy or {})

    if (
        not isinstance(metrics.get("hardcase_candidate"), dict)
        and bool(parse_risk_auto_enqueue_policy.get("enqueue"))
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
    query_debug: dict[str, Any] = {"original": question, "normalized": None, "applied_rules": [], "expansions": [], "contributions": [], "channels": None}
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

    expansions_dbg: list[dict[str, Any]] = []
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
    if step_back_used and step_back_query:
        expansions_dbg.append(
            {"kind": "step_back", "expanded_text": step_back_query, "source_rule_id": "llm:step_back", "weight": 1.0}
        )
    for q in sub_questions:
        expansions_dbg.append({"kind": "subq", "expanded_text": q, "source_rule_id": "llm:decompose", "weight": 1.0})
    if hyde_used and hyde_text:
        expansions_dbg.append({"kind": "hyde", "expanded_text": hyde_text, "source_rule_id": "llm:hyde", "weight": 1.0})
    query_debug["expansions"] = expansions_dbg[:20]
    query_debug["decompose_chain"] = {
        "enabled": bool(decompose_chain_enabled),
        "used": bool(decompose_chain_used),
        "steps": int(decompose_chain_steps or 0),
        "queries": decompose_chain_queries[:5],
        "elapsed_sec": round(float(decompose_chain_elapsed or 0.0), 3),
    }
    if kg_query_expansion_entity_names:
        query_debug["kg_entities"] = kg_query_expansion_entity_names[:10]

    try:
        by_role: dict[str, int] = {}
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
    router_layers = build_router_layers(
        query=query_for_retrieval,
        entity_key=(str(state.get("entity_key") or "").strip() or None),
        partition_keys=(list(state.get("partition_keys") or []) if isinstance(state.get("partition_keys"), list) else None),
        entity_candidates=(list(state.get("entity_candidates") or []) if isinstance(state.get("entity_candidates"), list) else None),
        intent_meta=(intent_router_meta if isinstance(intent_router_meta, dict) else None),
    )
    query_debug["router_layers"] = router_layers
    query_debug["intent_router"] = intent_router_meta
    query_debug["adaptive_router"] = adaptive_router_meta
    query_debug["channel_budget_policy"] = channel_budget_policy_meta
    query_debug["temporal_intent"] = {
        "enabled": bool(temporal_intent_enabled),
        "detected": bool(temporal_intent_meta.get("detected")),
        "reason_codes": list(temporal_intent_meta.get("reason_codes") or []),
        "recency_rerank": (
            dict(temporal_recency_meta) if isinstance(temporal_recency_meta, dict) else None
        ),
    }
    query_debug["hierarchy_recall"] = {
        "enabled": bool(hierarchy_recall_enabled),
        "family_collapse": bool(hierarchy_family_collapse),
        "family_aggregation": str(hierarchy_family_aggregation),
        "family_aggregation_meta": (
            dict(family_aggregation_meta) if isinstance(family_aggregation_meta, dict) else None
        ),
        "tree_dedup": bool(hierarchy_tree_dedup),
        "parent_depth": int(hierarchy_parent_depth),
        "sibling_window": int(hierarchy_sibling_window),
        "overfetch_factor": int(hierarchy_overfetch_factor),
        "tree_dedup_meta": (dict(tree_dedup_meta) if isinstance(tree_dedup_meta, dict) else None),
        "context_expansion_attempted": bool(hierarchy_expand_attempted),
        "context_expansion_used": bool(hierarchy_expand_used),
        "context_expansion_elapsed_sec": round(float(hierarchy_expand_elapsed or 0.0), 3),
        "context_expansion_error": hierarchy_expand_error,
        "context_expansion_meta": (dict(hierarchy_expand_meta) if isinstance(hierarchy_expand_meta, dict) else None),
    }
    query_debug["contextual_followup"] = {
        "enabled": bool(contextual_followup_enabled),
        "attempted": bool(contextual_followup_attempted),
        "used": bool(contextual_followup_used),
        "mode": str(contextual_followup_mode),
        "top_k": int(contextual_followup_top_k),
        "added_docs": int(contextual_followup_added_docs),
        "added_citations": int(contextual_followup_added_citations),
        "reason_codes": list(contextual_followup_reason_codes or []),
        "selected_terms": list(contextual_followup_selected_terms or []),
        "query": (str(contextual_followup_followup_query)[:220] if contextual_followup_followup_query else None),
        "error": contextual_followup_error,
    }
    query_debug["iterative_pass"] = {
        "enabled": bool(contextual_followup_enabled),
        "max_hops": int(contextual_followup_max_hops),
        "latency_budget_ms": round(float(contextual_followup_latency_budget_ms), 3),
        "hops_attempted": int(
            len([h for h in iterative_pass_hops if isinstance(h, dict) and bool(h.get("attempted"))])
        ),
        "hops_used": int(
            len([h for h in iterative_pass_hops if isinstance(h, dict) and bool(h.get("used"))])
        ),
        "reason_codes": list(iterative_pass_reason_codes or [])[:16],
        "gap": (dict(iterative_pass_gap or {}) if isinstance(iterative_pass_gap, dict) else None),
        "hops": [h for h in list(iterative_pass_hops or [])[:5] if isinstance(h, dict)],
    }
    query_debug["parse_quality"] = {
        "considered": int((parse_quality_summary or {}).get("considered") or 0),
        "low_ratio": float((parse_quality_summary or {}).get("low_ratio") or 0.0),
        "alert": bool((parse_quality_summary or {}).get("alert")),
        "recommendation": (parse_quality_summary or {}).get("recommendation"),
        "gate_profile": str(parse_quality_gate_profile),
        "gate_violation": bool(parse_quality_gate_violation),
        "gate_blocked": bool(parse_quality_gate_blocked),
        "gate_reason": parse_quality_gate_reason,
    }
    query_debug["parse_risk_auto_enqueue"] = (
        dict(metrics.get("parse_risk_auto_enqueue_policy"))
        if isinstance(metrics.get("parse_risk_auto_enqueue_policy"), dict)
        else None
    )
    query_debug["parse_repair_actions"] = (
        dict(metrics.get("parse_repair_actions"))
        if isinstance(metrics.get("parse_repair_actions"), dict)
        else None
    )
    query_debug["retrieval_contract"] = {
        "mode": retrieval_contract_mode or None,
        "deterministic_recall": bool(contract_deterministic_recall),
        "must_recall_strict": bool(contract_must_recall_strict),
        "must_recall_enabled": bool(must_recall_enabled),
        "must_recall_status": str(must_recall_status),
        "must_recall_passed": bool(must_recall_passed),
        "must_recall_expected_source_keys": list(must_recall_expected_source_keys or []),
        "must_recall_missing_source_keys": list(missing_source_keys or [])[:20],
        "must_recall_required_anchor_fields": list(must_recall_required_anchor_fields or []),
        "must_recall_auto_expected_source_keys": {
            "enabled": bool(must_recall_auto_expected_source_keys_enabled),
            "applied": bool(must_recall_auto_expected_source_keys_applied),
            "keys": list(must_recall_auto_expected_source_keys or []),
            "reason_codes": list(must_recall_auto_expected_source_keys_reason_codes or []),
            "confidence": str(must_recall_auto_expected_source_keys_confidence or "none"),
        },
        "must_recall_auto_required_anchor_fields": {
            "enabled": bool(must_recall_auto_required_anchor_fields_enabled),
            "applied": bool(must_recall_auto_required_anchor_fields_applied),
            "fields": list(must_recall_auto_required_anchor_fields or []),
            "reason_codes": list(must_recall_auto_required_anchor_fields_reason_codes or []),
        },
        "must_recall_anchor_missing_counts": dict(must_recall_anchor_eval.get("missing_counts") or {}),
        "must_recall_fail_reasons": list(must_recall_fail_reasons or [])[:12],
        "contract_fail_reason_taxonomy": str(
            retrieval_contract_policy.get("contract_fail_reason_taxonomy") or MUST_RECALL_FAIL_REASON_TAXONOMY_V1
        ),
        "second_pass": dict(must_recall_second_pass_payload),
        "must_recall_proof": dict(must_recall_proof),
    }
    if empty_diag:
        query_debug["empty_retrieval"] = empty_diag

    # Stable retrieval trace contract (versioned, parseable by downstream systems).
    #
    # Keep this separate from `metrics` (free-form counters) and `query_debug` (best-effort text payloads).
    try:
        variants: dict[str, int] = {}
        for kind, _q, _r in retrieval_plan:
            k = str(kind or "").strip() or "main"
            variants[k] = int(variants.get(k, 0) or 0) + 1
    except Exception:
        variants = {}

    def _trace_per_query_item(item: dict[str, Any]) -> dict[str, Any]:
        kind = str(item.get("kind") or "").strip() or "main"
        q_chars = int(item.get("query_chars") or 0)
        ok = bool(item.get("ok"))
        elapsed = float(item.get("elapsed_sec") or 0.0)
        payload: dict[str, Any] = {
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

    citations_by_role: dict[str, int] = {}
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

    retrieval_trace: dict[str, Any] = {
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
        "contract_diagnostics": {
            "contract_fail_reason_taxonomy": str(
                retrieval_contract_policy.get("contract_fail_reason_taxonomy") or MUST_RECALL_FAIL_REASON_TAXONOMY_V1
            ),
            "must_recall": {
                "enabled": bool(must_recall_enabled),
                "status": str(must_recall_status),
                "passed": bool(must_recall_passed),
                "expected_source_keys": list(must_recall_expected_source_keys or []),
                "missing_source_keys": list(missing_source_keys or [])[:40],
                "required_anchor_fields": list(must_recall_required_anchor_fields or []),
                "auto_expected_source_keys": {
                    "enabled": bool(must_recall_auto_expected_source_keys_enabled),
                    "applied": bool(must_recall_auto_expected_source_keys_applied),
                    "keys": list(must_recall_auto_expected_source_keys or []),
                    "reason_codes": list(must_recall_auto_expected_source_keys_reason_codes or []),
                    "confidence": str(must_recall_auto_expected_source_keys_confidence or "none"),
                },
                "auto_required_anchor_fields": {
                    "enabled": bool(must_recall_auto_required_anchor_fields_enabled),
                    "applied": bool(must_recall_auto_required_anchor_fields_applied),
                    "fields": list(must_recall_auto_required_anchor_fields or []),
                    "reason_codes": list(must_recall_auto_required_anchor_fields_reason_codes or []),
                },
                "anchor_missing_counts": dict(must_recall_anchor_eval.get("missing_counts") or {}),
                "fail_reasons": list(must_recall_fail_reasons or [])[:12],
                "second_pass": dict(must_recall_second_pass_payload),
                "proof": dict(must_recall_proof),
            },
        },
        "intent_router": intent_router_meta,
        "adaptive_router": adaptive_router_meta,
        "channel_budget_policy": channel_budget_policy_meta,
        "router_layers": router_layers,
        "contextual_followup": {
            "enabled": bool(contextual_followup_enabled),
            "attempted": bool(contextual_followup_attempted),
            "used": bool(contextual_followup_used),
            "mode": str(contextual_followup_mode),
            "top_k": int(contextual_followup_top_k),
            "max_docs": int(contextual_followup_max_docs),
            "max_terms": int(contextual_followup_max_terms),
            "min_term_chars": int(contextual_followup_min_term_chars),
            "query_hash": contextual_followup_query_hash,
            "added_docs": int(contextual_followup_added_docs),
            "added_citations": int(contextual_followup_added_citations),
            "reason_codes": list(contextual_followup_reason_codes or []),
            "selected_terms": list(contextual_followup_selected_terms or [])[:10],
            "elapsed_sec": round(float(contextual_followup_elapsed or 0.0), 3),
            "error": contextual_followup_error,
        },
        "iterative_pass": {
            "enabled": bool(contextual_followup_enabled),
            "max_hops": int(contextual_followup_max_hops),
            "latency_budget_ms": round(float(contextual_followup_latency_budget_ms), 3),
            "hops_attempted": int(
                len([h for h in iterative_pass_hops if isinstance(h, dict) and bool(h.get("attempted"))])
            ),
            "hops_used": int(
                len([h for h in iterative_pass_hops if isinstance(h, dict) and bool(h.get("used"))])
            ),
            "reason_codes": list(iterative_pass_reason_codes or [])[:16],
            "gap": (dict(iterative_pass_gap or {}) if isinstance(iterative_pass_gap, dict) else None),
            "hops": [h for h in list(iterative_pass_hops or [])[:5] if isinstance(h, dict)],
        },
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
            "step_back": {
                "enabled": bool(step_back_enabled),
                "used": bool(step_back_used),
                "elapsed_sec": round(float(step_back_elapsed or 0.0), 3),
                "model_used": step_back_model_used,
                "parse_ok": bool(step_back_parse_meta.get("ok")),
                "parse_method": step_back_parse_meta.get("method"),
                "parse_error": step_back_parse_meta.get("error"),
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
        "hierarchy_recall": {
            "enabled": bool(hierarchy_recall_enabled),
            "family_collapse": bool(hierarchy_family_collapse),
            "family_aggregation": str(hierarchy_family_aggregation),
            "tree_dedup": bool(hierarchy_tree_dedup),
            "parent_depth": int(hierarchy_parent_depth),
            "sibling_window": int(hierarchy_sibling_window),
            "overfetch_factor": int(hierarchy_overfetch_factor),
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
        "parse_quality_gate": {
            "profile": str(parse_quality_gate_profile),
            "violation": bool(parse_quality_gate_violation),
            "blocked": bool(parse_quality_gate_blocked),
            "reason": parse_quality_gate_reason,
        },
        "parse_risk": dict(parse_risk or {}),
        "parse_risk_auto_enqueue_policy": (
            dict(metrics.get("parse_risk_auto_enqueue_policy"))
            if isinstance(metrics.get("parse_risk_auto_enqueue_policy"), dict)
            else None
        ),
        "parse_repair_actions": (
            dict(metrics.get("parse_repair_actions"))
            if isinstance(metrics.get("parse_repair_actions"), dict)
            else None
        ),
        "hardcase_candidate": (metrics.get("hardcase_candidate") if isinstance(metrics.get("hardcase_candidate"), dict) else None),
    }
    observe_router_layers(router_layers)

    # Stable retrieval config fingerprint (PII-safe).
    #
    # Goal:
    # - Provide downstream systems a compact way to compare runs across environments
    #   without relying on brittle field-by-field comparisons.
    # - Must not include raw query text, doc ids, dataset ids, or metadata filter contents.
    try:
        retrieval_cfg: dict[str, Any] = {
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
            "adaptive_router": dict(adaptive_router_meta or {}),
            "channel_budget_policy": dict(channel_budget_policy_meta or {}),
            "must_recall_enabled": bool(must_recall_enabled),
            "must_recall_expected_source_keys": list(must_recall_expected_source_keys or []),
            "must_recall_required_anchor_fields": list(must_recall_required_anchor_fields or []),
            "must_recall_second_pass_enabled": bool(must_recall_second_pass_enabled),
            "must_recall_second_pass_mode": str(must_recall_second_pass_mode),
            "must_recall_second_pass_top_k": int(must_recall_second_pass_top_k),
            "contextual_followup_enabled": bool(contextual_followup_enabled),
            "contextual_followup_mode": str(contextual_followup_mode),
            "contextual_followup_top_k": int(contextual_followup_top_k),
            "contextual_followup_max_docs": int(contextual_followup_max_docs),
            "contextual_followup_max_terms": int(contextual_followup_max_terms),
            "contextual_followup_min_term_chars": int(contextual_followup_min_term_chars),
            "contextual_followup_max_query_chars": int(contextual_followup_max_query_chars),
            "contextual_followup_max_hops": int(contextual_followup_max_hops),
            "contextual_followup_latency_budget_ms": round(float(contextual_followup_latency_budget_ms), 3),
            "hierarchy_recall_enabled": bool(hierarchy_recall_enabled),
            "hierarchy_family_collapse": bool(hierarchy_family_collapse),
            "hierarchy_family_aggregation": str(hierarchy_family_aggregation),
            "hierarchy_tree_dedup": bool(hierarchy_tree_dedup),
            "hierarchy_parent_depth": int(hierarchy_parent_depth),
            "hierarchy_sibling_window": int(hierarchy_sibling_window),
            "hierarchy_overfetch_factor": int(hierarchy_overfetch_factor),
            "retrieval_hardcase_emit_enabled": bool(getattr(settings, "RETRIEVAL_HARDCASE_EMIT_ENABLED", False)),
            "rag_evidence_require_spans_enabled": bool(evidence_span_strict_enabled),
            "retrieval_parse_quality_low_threshold": float(getattr(settings, "RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD", 0.35) or 0.35),
            "retrieval_parse_quality_alert_ratio": float(getattr(settings, "RETRIEVAL_PARSE_QUALITY_ALERT_RATIO", 0.5) or 0.5),
            "retrieval_parse_quality_gate_profile": str(parse_quality_gate_profile),
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
            "step_back": {
                "enabled": bool(step_back_enabled),
                "temperature": float(step_back_temp or 0.0),
                "max_chars": int(step_back_max_chars or 0),
                "output_max_chars": int(step_back_output_max or 0),
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
            tmpl_fp: dict[str, Any] = {}

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
