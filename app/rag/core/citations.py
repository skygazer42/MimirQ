"""
Shared citation helpers.

These utilities convert retrieved LangChain `Document` objects into the
structured citation payload returned by both streaming and non-streaming RAG
pipelines.
"""

import json
import re
import uuid
from typing import Any, Dict, List

from langchain_core.documents import Document

from app.core.config import settings

_QUERY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{1,}|[\u4e00-\u9fff]{2,}")
_SENTENCE_BOUNDARIES = {"。", "！", "？", ".", "!", "?", "\n"}


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _extract_query_terms(query: str, *, max_terms: int = 8) -> list[str]:
    raw = (query or "").strip()
    if not raw:
        return []
    terms: list[str] = []
    for m in _QUERY_TOKEN_RE.finditer(raw):
        t = (m.group(0) or "").strip()
        if not t:
            continue
        t_norm = t.casefold() if t.isascii() else t
        if t_norm in terms:
            continue
        terms.append(t_norm)
        if len(terms) >= max_terms:
            break
    # Prefer longer terms for matching.
    return sorted(terms, key=len, reverse=True)


def _find_first_match(text: str, terms: list[str]) -> tuple[int, str] | None:
    if not text or not terms:
        return None
    folded = text.casefold()
    best: tuple[int, str] | None = None
    for t in terms:
        if not t:
            continue
        idx = folded.find(t.casefold()) if str(t).isascii() else text.find(str(t))
        if idx < 0:
            continue
        if best is None or idx < best[0]:
            best = (idx, str(t))
    return best


def _find_prev_boundary(text: str, *, start: int, end: int) -> int:
    """Return the last sentence-boundary position in [start, end), or -1."""
    best = -1
    for ch in _SENTENCE_BOUNDARIES:
        pos = text.rfind(ch, start, end)
        if pos > best:
            best = pos
    return best


def _find_next_boundary(text: str, *, start: int, end: int) -> int | None:
    """Return the first sentence-boundary position in [start, end), or None."""
    best: int | None = None
    for ch in _SENTENCE_BOUNDARIES:
        pos = text.find(ch, start, end)
        if pos < 0:
            continue
        if best is None or pos < best:
            best = pos
    return best


def _build_snippet(text: str, query: str | None, *, max_chars: int = 220) -> tuple[str, list[str]]:
    max_chars = max(60, int(max_chars or 0))
    clean = _collapse_ws(text)
    if not clean:
        return "", []

    terms = _extract_query_terms(query or "", max_terms=10) if query else []
    hit = _find_first_match(clean, terms) if terms else None
    if hit is None:
        snippet = clean[:max_chars]
        if len(clean) > max_chars:
            snippet += "..."
        return snippet, []

    idx, _ = hit
    before = max_chars // 3
    after = max_chars - before
    base_start = max(0, idx - before)
    base_end = min(len(clean), idx + after)

    # Prefer sentence-level windows for readability, while keeping the same max_chars budget.
    start = base_start
    end = base_end
    prev = _find_prev_boundary(clean, start=base_start, end=idx)
    if prev >= 0:
        start = min(max(base_start, prev + 1), len(clean))
    nxt = _find_next_boundary(clean, start=idx, end=base_end)
    if nxt is not None:
        end = min(max(start, nxt + 1), len(clean))

    snippet = clean[start:end].strip() or clean[base_start:base_end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(clean):
        snippet = snippet + "..."

    matched: list[str] = []
    snippet_folded = snippet.casefold()
    for t in terms:
        if not t:
            continue
        if str(t).isascii():
            if t.casefold() in snippet_folded:
                matched.append(str(t))
        else:
            if str(t) in snippet:
                matched.append(str(t))
    return snippet, matched


def _build_snippet_and_span(
    text: str,
    query: str | None,
    *,
    max_chars: int = 220,
) -> tuple[str, list[str], int | None, int | None]:
    """
    Build a human-friendly snippet for UI and (best-effort) raw span offsets into `text`.

    Offsets are only returned when we find a query-term hit; otherwise offsets are None.
    """
    max_chars = max(60, int(max_chars or 0))
    raw = str(text or "")
    if not raw.strip():
        return "", [], None, None

    terms = _extract_query_terms(query or "", max_terms=10) if query else []
    hit = _find_first_match(raw, terms) if terms else None
    if hit is None:
        # Fallback: still return a bounded span window so the UI can deep-link/highlight
        # even when we don't find an explicit query-term match (best-effort).
        base_end = min(len(raw), max_chars)
        start = 0
        end = base_end
        nxt = _find_next_boundary(raw, start=0, end=base_end)
        if nxt is not None and nxt > 0:
            end = min(base_end, nxt + 1)

        snippet_raw = raw[start:end]
        snippet = _collapse_ws(snippet_raw).strip() or _collapse_ws(raw[:base_end])
        if end < len(raw):
            snippet += "..."
        return snippet, [], int(start), int(end)

    idx, _ = hit
    before = max_chars // 3
    after = max_chars - before
    base_start = max(0, idx - before)
    base_end = min(len(raw), idx + after)

    # Prefer sentence-level windows for readability.
    start = base_start
    end = base_end
    prev = _find_prev_boundary(raw, start=base_start, end=idx)
    if prev >= 0:
        start = min(max(base_start, prev + 1), len(raw))
    nxt = _find_next_boundary(raw, start=idx, end=base_end)
    if nxt is not None:
        end = min(max(start, nxt + 1), len(raw))

    snippet_raw = raw[start:end]
    snippet = _collapse_ws(snippet_raw).strip() or _collapse_ws(raw[base_start:base_end])
    if start > 0:
        snippet = "..." + snippet
    if end < len(raw):
        snippet = snippet + "..."

    matched: list[str] = []
    snippet_folded = snippet_raw.casefold()
    for t in terms:
        if not t:
            continue
        if str(t).isascii():
            if t.casefold() in snippet_folded:
                matched.append(str(t))
        else:
            if str(t) in snippet_raw:
                matched.append(str(t))

    return snippet, matched, int(start), int(end)


_NIL_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _is_uuid_like(v: Any) -> bool:
    if v is None:
        return False
    try:
        uuid.UUID(str(v))
        return True
    except Exception:
        return False


def _stable_tag_chunk_id(table_id: str | None) -> str:
    """
    Deterministic UUID for TAG-injected "docs" so ChatResponse citations remain schema-compatible.
    """
    tid = str(table_id or "").strip()
    return str(uuid.uuid5(_NIL_UUID, f"mimirq:tag:{tid}"))


def _parse_json_object(text: str) -> dict[str, Any] | None:
    s = str(text or "").strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _format_tag_table_store_summary(doc: Document, *, meta: dict[str, Any]) -> str | None:
    """
    Convert a TAG table_store JSON payload into a human-readable summary for citations/UI.
    """
    payload = _parse_json_object(doc.page_content or "")
    if not payload:
        return None
    if str(payload.get("kind") or "") != "tag_table_store":
        return None

    doc_name = str(payload.get("document") or meta.get("source") or "table").strip() or "table"
    table_id = str(payload.get("table_id") or meta.get("table_id") or "").strip()

    sheet_name = payload.get("sheet_name")
    sheet_name = str(sheet_name).strip() if sheet_name is not None else ""
    sheet_index = payload.get("sheet_index")
    try:
        sheet_index_i = int(sheet_index) if sheet_index is not None else None
    except Exception:
        sheet_index_i = None

    row_count = payload.get("row_count")
    col_count = payload.get("col_count")
    try:
        row_count_i = int(row_count) if row_count is not None else None
    except Exception:
        row_count_i = None
    try:
        col_count_i = int(col_count) if col_count is not None else None
    except Exception:
        col_count_i = None

    sql = str(payload.get("sql") or "").strip()
    columns = payload.get("columns") if isinstance(payload.get("columns"), list) else []
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    truncated = bool(payload.get("truncated"))

    parts: list[str] = ["[TAG] Table Query Result"]
    parts.append(f"Document: {doc_name}")
    if sheet_name:
        sheet_extra = f" (sheet_{sheet_index_i})" if sheet_index_i is not None else ""
        parts.append(f"Sheet: {sheet_name}{sheet_extra}")
    elif sheet_index_i is not None:
        parts.append(f"Sheet: sheet_{sheet_index_i}")
    if row_count_i is not None and col_count_i is not None:
        parts.append(f"Shape: {row_count_i} rows x {col_count_i} cols")
    if table_id:
        parts.append(f"Table ID: {table_id}")
    if sql:
        parts.append(f"SQL: {sql}")

    cols_s = [str(c) for c in columns if str(c).strip()]
    if cols_s and rows:
        max_cols = 6
        max_rows = 4
        cols_s = cols_s[:max_cols]
        parts.append("Rows (preview):")
        for r in rows[:max_rows]:
            if not isinstance(r, list):
                continue
            pairs: list[str] = []
            for i, col in enumerate(cols_s):
                v = r[i] if i < len(r) else None
                if v is None:
                    continue
                s = str(v).strip()
                if not s:
                    continue
                pairs.append(f"{col}={s}")
            if pairs:
                parts.append("- " + ", ".join(pairs))
    if truncated:
        parts.append("(truncated)")

    return "\n".join(parts).strip() or None


def build_citations_from_docs(
    docs: List[Document],
    *,
    retrieval_elapsed_sec: float,
    retrieval_mode: str,
    query: str | None = None,
) -> List[Dict[str, Any]]:
    citations: List[Dict[str, Any]] = []
    for doc in docs:
        meta = doc.metadata or {}

        v_score_raw = float(meta.get("vector_score", 0.0) or 0.0)
        b_score_raw = float(meta.get("bm25_score", 0.0) or 0.0)
        l_score_raw = float(meta.get("lexical_score", 0.0) or 0.0)
        s_score_raw = float(meta.get("sparse_score", 0.0) or 0.0)
        rerank_score = meta.get("rerank_score")
        retrieval_score = meta.get("retrieval_score")

        retrieval_role = meta.get("retrieval_role") or None
        neighbor_of = meta.get("neighbor_of") or None
        is_tag = str(retrieval_role or "").strip().lower() == "tag" or str(meta.get("chunk_role") or "") == "tag_sql_result"

        page_number = None
        page_raw = meta.get("page")
        try:
            page_int = int(page_raw) if page_raw is not None else None
            if page_int and page_int > 0:
                page_number = page_int
        except Exception:
            page_number = None

        if is_tag:
            hit_type = "tag"
        elif retrieval_mode == "mmr":
            hit_type = "mmr"
        elif v_score_raw > b_score_raw:
            hit_type = "vector"
        elif b_score_raw > v_score_raw:
            hit_type = "keyword"
        else:
            hit_type = "hybrid"

        img_id = meta.get("img_id")
        img_url = f"/api/v1/documents/image-url/{img_id}" if img_id else None

        raw_chunk_id = getattr(doc, "id", None) or meta.get("chunk_id")
        chunk_id = raw_chunk_id
        if is_tag and not _is_uuid_like(chunk_id):
            # TAG docs are not real chunks; generate deterministic UUIDs so ChatResponse citation schema
            # remains compatible even when callers used a non-UUID id (historical behavior/tests).
            tag_table_id = str(meta.get("table_id") or "").strip()
            if not tag_table_id:
                payload = _parse_json_object(doc.page_content or "")
                if payload:
                    tag_table_id = str(payload.get("table_id") or "").strip()
            chunk_id = _stable_tag_chunk_id(tag_table_id)

        effective_text = doc.page_content or ""
        if is_tag:
            formatted = _format_tag_table_store_summary(doc, meta=meta)
            if formatted:
                effective_text = formatted

        snippet, matched_terms, evidence_start_in_chunk, evidence_end_in_chunk = _build_snippet_and_span(
            effective_text, query, max_chars=220
        )

        start_char = meta.get("start_char")
        end_char = meta.get("end_char")
        chunk_index = meta.get("chunk_index")
        try:
            start_char = int(start_char) if start_char is not None else None
        except Exception:
            start_char = None
        try:
            end_char = int(end_char) if end_char is not None else None
        except Exception:
            end_char = None
        try:
            chunk_index = int(chunk_index) if chunk_index is not None else None
        except Exception:
            chunk_index = None

        citation: Dict[str, Any] = {
            "chunk_id": chunk_id,
            "document_id": meta.get("document_id"),
            "document_name": meta.get("source", "Unknown"),
            "chunk_content": snippet or ((effective_text or "")[:200] + "..."),
            "matched_terms": matched_terms,
            "page_number": page_number,
            "chunk_index": chunk_index,
            "start_char": start_char,
            "end_char": end_char,
            "evidence_start_char": (
                (int(start_char) + int(evidence_start_in_chunk))
                if (start_char is not None and evidence_start_in_chunk is not None)
                else None
            ),
            "evidence_end_char": (
                (int(start_char) + int(evidence_end_in_chunk))
                if (start_char is not None and evidence_end_in_chunk is not None)
                else None
            ),
            "header_path": meta.get("header_path") or meta.get("header_context"),
            "chunk_strategy": meta.get("chunk_strategy"),
            "chunk_role": meta.get("chunk_role"),
            "chunk_semantic_role": meta.get("chunk_semantic_role"),
            # Policy/manual structured chunking (best-effort; present only for relevant docs).
            "policy_clause_id": meta.get("policy_clause_id"),
            "policy_clause_number": meta.get("policy_clause_number"),
            "policy_path": meta.get("policy_path"),
            "policy_path_str": meta.get("policy_path_str"),
            "parent_id": meta.get("parent_id"),
            "retrieval_role": retrieval_role,
            "neighbor_of": neighbor_of,
            # Useful for audit/debug and for versioned retrieval UIs.
            "doc_pipeline_key": meta.get("doc_pipeline_key"),
            "pipeline_hash": meta.get("pipeline_hash"),
            "relevance_score": round(float(meta.get("score", 0.0) or 0.0), 2),
            "vector_score": round(v_score_raw, 3),
            "bm25_score": round(b_score_raw, 3),
            "lexical_score": round(l_score_raw, 3),
            "sparse_score": round(s_score_raw, 3),
            "keyword_score": round(float(meta.get("keyword_score", 0.0) or 0.0), 3),
            # KG ranking features (optional; low-cardinality).
            # These fields stay numeric/boolean and do not include scope identifiers.
            "kg_pagerank": round(float(meta.get("kg_pagerank", 0.0) or 0.0), 3),
            "kg_shared_events": int(meta.get("kg_shared_events", 0) or 0),
            "kg_path_length": int(meta.get("kg_path_length", 0) or 0),
            "kg_edge_conf_low": round(float(meta.get("kg_edge_conf_low", 0.0) or 0.0), 3),
            "kg_edge_conf_mid": round(float(meta.get("kg_edge_conf_mid", 0.0) or 0.0), 3),
            "kg_edge_conf_high": round(float(meta.get("kg_edge_conf_high", 0.0) or 0.0), 3),
            "kg_evidence_anchored": bool(meta.get("kg_evidence_anchored", False)),
            "rerank_score": round(float(rerank_score), 3) if rerank_score is not None else None,
            "retrieval_score": round(float(retrieval_score), 3) if retrieval_score is not None else None,
            "reranker_provider": meta.get("reranker_provider"),
            "rerank_elapsed_sec": meta.get("rerank_elapsed_sec"),
            "rerank_model_used": meta.get("rerank_model_used"),
            "retrieval_mode": retrieval_mode,
            "vector_backend": settings.VECTOR_BACKEND,
            "retrieval_elapsed_sec": round(float(retrieval_elapsed_sec or 0.0), 3),
            "hit_type": hit_type,
        }

        # Optional: KG path provenance for KG-injected citations (bounded, PII-safe).
        #
        # The retriever/orchestrator should attach this as a list of {entity_id,type} items
        # (no names, no chunk snippets).
        kg_path_raw = meta.get("kg_path")
        if isinstance(kg_path_raw, list) and kg_path_raw:
            kg_path: list[dict[str, Any]] = []
            for item in kg_path_raw:
                if not isinstance(item, dict):
                    continue
                ent_id = item.get("entity_id")
                ent_id_s = str(ent_id or "").strip()
                if not ent_id_s:
                    continue
                typ = item.get("type")
                typ_s = str(typ or "").strip()
                entry: dict[str, Any] = {"entity_id": ent_id_s}
                if typ_s:
                    entry["type"] = typ_s[:100]
                kg_path.append(entry)
                if len(kg_path) >= 6:
                    break
            if kg_path:
                citation["kg_path"] = kg_path

        def _safe_kg_path_provenance(raw: Any) -> dict[str, Any] | None:
            """
            Sanitize a shortest-path provenance payload for citations.

            Rules:
            - Keep identifiers + small, low-cardinality fields only.
            - Drop any text evidence (quotes, entity names, etc).
            - Bound list sizes.
            """
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

        kg_path_prov_raw = meta.get("kg_path_provenance")
        prov = _safe_kg_path_provenance(kg_path_prov_raw)
        if prov:
            citation["kg_path_provenance"] = prov

        if img_id:
            citation["img_id"] = img_id
            citation["img_url"] = img_url
            citation["has_image"] = True
        else:
            citation["has_image"] = False

        citations.append(citation)
    return citations
