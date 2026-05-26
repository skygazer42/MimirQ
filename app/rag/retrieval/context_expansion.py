from __future__ import annotations

from typing import Any

from langchain_core.documents import Document

from app.rag.retrieval.hierarchy_expand import FetchByHierarchyKey, expand_hierarchy_context
from app.rag.retrieval.neighbor_expand import expand_neighbors_by_score
from app.rag.retrieval.sibling_expand import expand_document_siblings


def expand_reranked_ids_by_score(
    *,
    ranked_items: list[dict[str, Any]],
    get_adjacent_ids,
    high_threshold: float = 0.7,
    mid_threshold: float = 0.4,
    high_span: int = 3,
    mid_span: int = 1,
) -> dict[str, Any]:
    return expand_neighbors_by_score(
        ranked_items=ranked_items,
        get_adjacent_ids=get_adjacent_ids,
        high_threshold=high_threshold,
        mid_threshold=mid_threshold,
        high_span=high_span,
        mid_span=mid_span,
    )


def expand_ranked_chunk_results(
    *,
    results: list[dict[str, Any]],
    window: int,
    max_added: int,
    sibling_max_added: int,
    document_chunks_by_doc: dict[str, list[Any]] | None = None,
    short_doc_ids: set[str] | None = None,
    neighbors_by_pair: dict[tuple[str, int], Any] | None = None,
    original_results_by_chunk_id: dict[str, dict[str, Any]] | None = None,
    score_driven: bool = False,
    high_threshold: float = 0.7,
    mid_threshold: float = 0.4,
    high_span: int = 3,
    mid_span: int = 1,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not results:
        return results, {"enabled": False, "reason": "no_results"}

    window_i = max(0, int(window or 0))
    max_added_i = max(0, int(max_added or 0))
    sibling_max_added_i = max(0, int(sibling_max_added or 0))
    document_chunks_by_doc = dict(document_chunks_by_doc or {})
    short_doc_ids = {str(doc_id).strip() for doc_id in (short_doc_ids or set()) if str(doc_id or "").strip()}
    neighbors_by_pair = dict(neighbors_by_pair or {})

    if window_i <= 0 and not short_doc_ids:
        return results, {"enabled": False, "reason": "disabled"}

    seen: set[str] = set()
    original_map = dict(original_results_by_chunk_id or {})
    if not original_map:
        for item in results or []:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("chunk_id") or ((item.get("metadata") or {}).get("chunk_id")) or "").strip()
            if cid:
                original_map[cid] = item

    expanded: list[dict[str, Any]] = []
    processed_short_docs: set[str] = set()
    neighbor_added = 0
    sibling_added = 0
    strategies_used: set[str] = set()
    pending_score_neighbors: list[dict[str, Any]] = []

    for result in results:
        if not isinstance(result, dict):
            continue
        meta = result.get("metadata") or {}
        anchor_cid = str(result.get("chunk_id") or meta.get("chunk_id") or "").strip()
        doc_key = str(meta.get("document_id") or "").strip()
        anchor_header_path = str(meta.get("header_path") or meta.get("header_context") or "").strip() or None

        try:
            idx = int(meta.get("chunk_index")) if meta.get("chunk_index") is not None else None
        except Exception:
            idx = None

        if doc_key and doc_key in short_doc_ids:
            if doc_key in processed_short_docs:
                continue
            strategies_used.add("sibling")
            sibling_items = expand_document_siblings(
                results=[result],
                document_chunks_by_doc=document_chunks_by_doc,
                short_doc_ids={doc_key},
                max_added=sibling_max_added_i,
                original_results_by_chunk_id=original_map,
            )
            for item in sibling_items:
                cid = str(item.get("chunk_id") or ((item.get("metadata") or {}).get("chunk_id")) or "").strip()
                if cid in seen:
                    expanded.append(item)
                    continue
                if str((item.get("metadata") or {}).get("retrieval_role") or "").strip() == "sibling":
                    sibling_added += 1
                seen.add(cid)
                expanded.append(item)
            processed_short_docs.add(doc_key)
            continue

        local_window = window_i
        if score_driven:
            try:
                score = float(result.get("score") or 0.0)
            except Exception:
                score = 0.0
            if score >= float(high_threshold):
                local_window = min(window_i, max(0, int(high_span or 0)))
            elif score >= float(mid_threshold):
                local_window = min(window_i, max(0, int(mid_span or 0)))
            else:
                local_window = 0

        if doc_key and idx is not None and local_window > 0:
            strategies_used.add("neighbor_score" if score_driven else "neighbor")
            if score_driven:
                if anchor_cid and anchor_cid not in seen:
                    seen.add(anchor_cid)
                expanded.append(result)
            for gi in range(idx - local_window, idx + local_window + 1):
                if gi < 0:
                    continue
                if gi == idx:
                    if not score_driven:
                        if anchor_cid and anchor_cid not in seen:
                            seen.add(anchor_cid)
                        expanded.append(result)
                    continue

                ck = neighbors_by_pair.get((doc_key, gi))
                if ck is None:
                    continue
                ck_id = str(getattr(ck, "id", "") or "").strip()
                if not ck_id or ck_id in seen:
                    continue
                if max_added_i and neighbor_added >= max_added_i:
                    continue

                stored_meta = dict(getattr(ck, "doc_metadata", None) or {})
                neighbor_header_path = str(
                    stored_meta.get("header_path") or stored_meta.get("header_context") or ""
                ).strip() or None
                if anchor_header_path and neighbor_header_path and neighbor_header_path != anchor_header_path:
                    continue
                stored_meta.setdefault("tenant_id", str(getattr(ck, "tenant_id", "") or ""))
                stored_meta.setdefault("document_id", str(getattr(ck, "document_id", "") or ""))
                stored_meta.setdefault("chunk_index", int(getattr(ck, "chunk_index", 0) or 0))
                stored_meta.setdefault("chunk_id", ck_id)
                if getattr(ck, "page_number", None) is not None:
                    stored_meta.setdefault("page", ck.page_number)
                if not stored_meta.get("source"):
                    stored_meta["source"] = "unknown"
                stored_meta["neighbor_of"] = anchor_cid or None
                stored_meta["retrieval_role"] = "neighbor"

                anchor_score = float(result.get("score", 0.0) or 0.0)
                neighbor_score = float(anchor_score * 0.85) if anchor_score else 0.0
                neighbor_item = {
                    "chunk_id": ck_id,
                    "content": str(getattr(ck, "content", "") or ""),
                    "metadata": stored_meta,
                    "score": neighbor_score,
                }
                if score_driven:
                    pending_score_neighbors.append(neighbor_item)
                else:
                    expanded.append(neighbor_item)
                seen.add(ck_id)
                neighbor_added += 1
            continue

        if anchor_cid and anchor_cid not in seen:
            seen.add(anchor_cid)
        expanded.append(result)

    if pending_score_neighbors:
        expanded.extend(pending_score_neighbors)

    meta = {
        "enabled": True,
        "framework": "context_expansion",
        "strategy": "mixed" if len(strategies_used) > 1 else (next(iter(strategies_used)) if strategies_used else "none"),
        "strategies_used": sorted(strategies_used),
        "window": int(window_i),
        "score_driven": bool(score_driven),
        "high_threshold": float(high_threshold),
        "mid_threshold": float(mid_threshold),
        "high_span": int(high_span),
        "mid_span": int(mid_span),
        "short_doc_count": int(len(short_doc_ids)),
        "neighbor_added": int(neighbor_added),
        "sibling_added": int(sibling_added),
        "added_docs": int(neighbor_added + sibling_added),
    }
    return expanded, meta


def expand_hierarchy_documents(
    docs: list[Document],
    *,
    parent_depth: int,
    sibling_window: int,
    fetch_by_key: FetchByHierarchyKey,
    max_added_docs: int = 120,
) -> tuple[list[Document], dict[str, Any]]:
    expanded_docs, meta = expand_hierarchy_context(
        docs,
        parent_depth=parent_depth,
        sibling_window=sibling_window,
        fetch_by_key=fetch_by_key,
        max_added_docs=max_added_docs,
    )
    meta_out = dict(meta or {})
    meta_out["framework"] = "context_expansion"
    meta_out["strategy"] = "hierarchy"
    return expanded_docs, meta_out


__all__ = [
    "expand_hierarchy_documents",
    "expand_ranked_chunk_results",
    "expand_reranked_ids_by_score",
]
