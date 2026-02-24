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
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser

from app.core.config import settings
from app.core.utils import parse_csv
from app.query.normalize import normalize_query
from app.rag.core.citations import build_citations_from_docs
from app.rag.core.conversation import format_history_text
from app.rag.core.hashing import stable_hash
from app.rag.core.text import (
    build_abstain_followup,
    guess_retrieval_mode,
    normalize_retrieval_mode,
    parse_json_from_text,
    should_rewrite_query,
)
from app.rag.engine import get_rag_engine
from app.rag.kg.pipeline import kg_search
from app.rag.policy.query_expansion import build_clause_fastlane_queries
from app.rag.query_expansion import generate_alias_queries
from app.rag.reranker.factory import get_reranker
from app.rag.reranker.types import RerankCandidate
from app.rag.retriever import hybrid_retriever


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
    for k in ("requested_k", "search_k", "overfetch_enabled"):
        v = dbg.get(k)
        if v is not None:
            out[k] = v

    qn = dbg.get("query_normalization")
    qn = qn if isinstance(qn, dict) else {}
    normalized = qn.get("normalized") if isinstance(qn.get("normalized"), str) else None
    applied_rules = qn.get("applied_rules") if isinstance(qn.get("applied_rules"), list) else []
    if normalized is not None or applied_rules:
        out["query_normalization"] = {
            "normalized": normalized,
            "applied_rules": [str(x) for x in applied_rules if x is not None][:20],
            "original_chars": len(str(qn.get("original") or "")),
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

    channels = dbg.get("channels")
    if isinstance(channels, dict):
        out["channels"] = channels

    return out or None


def _is_recall_profile(profile: str | None) -> bool:
    p = str(profile or "").strip().lower()
    return p in {"recall20", "recall50", "coverage80"}


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

    # KG search output can be reused by multiple retrieval steps (query expansion / chunk injection).
    kg_result_cached: dict[str, Any] | None = None

    if (
        bool(settings.ENABLE_QUERY_REWRITE)
        and history_text != "(No conversation history)"
        and len(question) <= int(settings.QUERY_REWRITE_MAX_CHARS or 0)
        and should_rewrite_query(question)
    ):
        rewrite_llm = engine.models.get("fast") or engine.models.get("default")  # type: ignore[attr-defined]
        rewrite_model_used = getattr(rewrite_llm, "model_name", None) or getattr(rewrite_llm, "model", None)
        try:
            rewrite_chain = (
                engine.rewrite_prompt  # type: ignore[attr-defined]
                | rewrite_llm.bind(temperature=settings.QUERY_REWRITE_TEMPERATURE)
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

    requested_retrieval_mode = state.get("retrieval_mode", "hybrid") or "hybrid"
    request_retrieval_mode = normalize_retrieval_mode(requested_retrieval_mode)
    retrieval_mode_routed = False
    mode_norm = str(request_retrieval_mode or "hybrid").lower().strip()
    if mode_norm == "auto":
        request_retrieval_mode = guess_retrieval_mode(query_for_retrieval)
        retrieval_mode_routed = True
        mode_norm = str(request_retrieval_mode or "hybrid").lower().strip()
    if mode_norm not in ("hybrid", "vector", "keyword", "mmr"):
        request_retrieval_mode = "hybrid"
        mode_norm = "hybrid"

    profile_norm = str(state.get("retrieval_profile") or "").strip().lower()
    retriever_update: Dict[str, Any] = {
        "k": state.get("top_k", settings.RETRIEVAL_TOP_K),
        "score_threshold": state.get("score_threshold", settings.SIMILARITY_THRESHOLD),
        "alpha": state.get("alpha", 0.6),
        "retrieval_mode": request_retrieval_mode,
        "enable_weight_rerank": state.get("enable_weight_rerank", True),
        "vector_weight": state.get("vector_weight", 0.6),
        "keyword_weight": state.get("keyword_weight", 0.4),
        "mmr_lambda": state.get("mmr_lambda", settings.RETRIEVAL_MMR_LAMBDA),
        "enable_reranker": state.get("enable_reranker", settings.ENABLE_RERANKER),
        "reranker_provider": state.get("reranker_provider", settings.RERANKER_PROVIDER),
        "reranker_top_n": state.get("reranker_top_n", settings.RERANKER_TOP_N),
        "tenant_id": state.get("tenant_id"),
        "account_id": state.get("account_id"),
        "dataset_id": state.get("dataset_id"),
        "document_ids": state.get("document_ids"),
        "metadata_filter": state.get("metadata_filter"),
    }

    # Retrieval profile contract (defense-in-depth): ensure the profile behavior holds even
    # when callers bypass ChatRAGConfig validation.
    if profile_norm == "recall20":
        retriever_update["k"] = max(int(retriever_update.get("k") or 0), 20)
        retriever_update["score_threshold"] = 0.0
    elif profile_norm == "recall50":
        retriever_update["k"] = max(int(retriever_update.get("k") or 0), 50)
        retriever_update["score_threshold"] = 0.0
    elif profile_norm == "coverage80":
        retriever_update["k"] = max(int(retriever_update.get("k") or 0), 80)
        retriever_update["score_threshold"] = 0.0

    # Recall-first profiles: do not drop candidates due to dedup/diversity heuristics.
    if _is_recall_profile(profile_norm):
        retriever_update.update(
            {
                "dedup_enabled": False,
                "max_chunks_per_doc": 0,
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
            docs_by_query.append(docs_i or [])
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=retrieval_parallelism) as pool:
            futures = [pool.submit(_invoke_with_timing, kind, q, r) for kind, q, r in retrieval_plan]
            for fut in futures:
                kind, docs_i, err, elapsed_i, dbg = fut.result()
                retrieval_per_query.append({"kind": kind, "query_chars": len(q or ""), "elapsed_sec": round(elapsed_i, 3), "ok": err is None, "retriever_debug": dbg})
                if err:
                    retrieval_errors.append(f"{kind}:{err[:160]}")
                docs_by_query.append(docs_i or [])
    retrieval_elapsed = time.time() - start

    if len(docs_by_query) <= 1:
        docs = docs_by_query[0] if docs_by_query else []
    else:
        docs = engine.fuse_docs_rrf(docs_by_query, rrf_k=settings.RETRIEVAL_RRF_K, meta_prefix="query_expansion")  # type: ignore[attr-defined]

    top_k = int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 5)
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
                try:
                    score_by_chunk[str(cid)] = float(ev.get("score", 0.0) or 0.0)
                except Exception:
                    score_by_chunk[str(cid)] = 0.0
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
            meta["kg_shared_events"] = 1.0
            meta["kg_path_length"] = 1.0
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
    post_rerank_used = False
    post_rerank_provider: str | None = None
    post_rerank_model_used: str | None = None
    post_rerank_elapsed = 0.0
    post_rerank_error: str | None = None
    post_rerank_candidates_n = 0

    try:
        if post_rerank_enabled and (docs or []):
            provider = str(getattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "") or "ltr").strip().lower()
            post_rerank_provider = provider
            if provider not in ("none", "off", "false", "0"):
                top_n = int(getattr(settings, "EVIDENCE_POST_RERANK_TOP_N", 0) or 0)
                if top_n <= 0:
                    top_n = len(docs or [])
                post_rerank_candidates_n = min(top_n, len(docs or []))

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
                    reranker = get_reranker(provider)
                    rr_start = time.time()
                    rr = reranker.rerank(
                        query=query_for_retrieval,
                        candidates=candidates,
                        top_n=post_rerank_candidates_n,
                    )
                    post_rerank_elapsed = float(rr.elapsed_sec or (time.time() - rr_start))
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

                    docs = ordered + list((docs or [])[post_rerank_candidates_n:])
                    post_rerank_used = True
    except Exception as exc:  # noqa: BLE001
        post_rerank_used = False
        post_rerank_error = str(exc)[:200]

    citations = build_citations_from_docs(docs, retrieval_elapsed_sec=retrieval_elapsed, retrieval_mode=request_retrieval_mode, query=query_for_retrieval)

    metrics = dict(state.get("metrics") or {})
    metrics["retrieval_elapsed_sec"] = round(retrieval_elapsed, 3)
    metrics["retrieval_mode"] = request_retrieval_mode
    metrics["retrieval_mode_requested"] = requested_retrieval_mode
    metrics["retrieval_mode_auto_routed"] = bool(retrieval_mode_routed)
    metrics["retrieval_query_parallelism"] = retrieval_parallelism
    metrics["retrieval_query_count"] = len(retrieval_plan)
    metrics["retrieval_per_query"] = retrieval_per_query[:8]
    metrics["vector_backend"] = settings.VECTOR_BACKEND
    if retrieval_errors:
        metrics["retrieval_errors"] = retrieval_errors[:5]

    metrics["evidence_post_rerank_enabled"] = bool(post_rerank_enabled)
    metrics["evidence_post_rerank_used"] = bool(post_rerank_used)
    metrics["evidence_post_rerank_provider"] = post_rerank_provider
    metrics["evidence_post_rerank_candidates_n"] = int(post_rerank_candidates_n or 0)
    metrics["evidence_post_rerank_elapsed_sec"] = round(float(post_rerank_elapsed or 0.0), 3)
    metrics["evidence_post_rerank_model_used"] = post_rerank_model_used
    metrics["evidence_post_rerank_error"] = post_rerank_error

    metrics["query_rewrite_enabled"] = settings.ENABLE_QUERY_REWRITE
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

    # Grounding guard: abstain when evidence is weak/empty.
    strict_visible = bool(getattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False)) or bool(state.get("visible_evidence_only"))
    abstain_enabled = bool(settings.RAG_ABSTAIN_ENABLED) or strict_visible
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

    retrieval_trace: Dict[str, Any] = {
        "schema": "mimirq.retrieval_trace_pass.v1",
        "query_for_retrieval_hash": stable_hash(query_for_retrieval),
        "requested_retrieval_mode": str(requested_retrieval_mode or ""),
        "retrieval_mode": str(request_retrieval_mode or ""),
        "retrieval_mode_auto_routed": bool(retrieval_mode_routed),
        "retrieval_profile": profile_norm or None,
        "rewrite": {
            "enabled": bool(settings.ENABLE_QUERY_REWRITE),
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
            "channel_fusion_strategy": str(getattr(settings, "RETRIEVAL_FUSION_STRATEGY", "linear") or "linear"),
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
            "candidates_n": int(post_rerank_candidates_n or 0),
            "elapsed_sec": round(float(post_rerank_elapsed or 0.0), 3),
            "model_used": post_rerank_model_used,
            "error": post_rerank_error,
        },
        "abstain": {
            "enabled": bool(abstain_enabled),
            "triggered": bool(abstain_triggered),
            "reason": abstain_reason,
            "min_citations": int(settings.RAG_ABSTAIN_MIN_CITATIONS or 0),
            "min_top_relevance_score": float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE or 0.0),
            "top_relevance_score": round(float(top_rel or 0.0), 3),
        },
        "citations": {
            "count": int(len(citations)),
            "by_role": citations_by_role,
        },
    }

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
