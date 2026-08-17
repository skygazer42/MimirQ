from typing import Any

from langchain_core.documents import Document

from app.rag.retrieval.hierarchy_expand import FetchByHierarchyKey, expand_hierarchy_context
from app.rag.retrieval.neighbor_expand import expand_neighbors_by_score
from app.rag.retrieval.sibling_expand import expand_document_siblings


def _chunk_id_from_item(item: dict[str, Any]) -> str:
    meta = item.get("metadata") or {}
    return str(item.get("chunk_id") or meta.get("chunk_id") or "").strip()


def _header_path_from_meta(meta: dict[str, Any]) -> str | None:
    return str(meta.get("header_path") or meta.get("header_context") or "").strip() or None


def _coerce_non_negative_int(value: Any) -> int:
    return max(0, int(value or 0))


def _coerce_chunk_index(meta: dict[str, Any]) -> int | None:
    raw = meta.get("chunk_index")
    if raw is None:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _normalize_short_doc_ids(short_doc_ids: set[str] | None) -> set[str]:
    return {str(doc_id).strip() for doc_id in (short_doc_ids or set()) if str(doc_id or "").strip()}


def _build_original_result_map(
    results: list[dict[str, Any]],
    original_results_by_chunk_id: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    original_map = dict(original_results_by_chunk_id or {})
    if original_map:
        return original_map
    for item in results or []:
        if not isinstance(item, dict):
            continue
        chunk_id = _chunk_id_from_item(item)
        if chunk_id:
            original_map[chunk_id] = item
    return original_map


def _append_anchor_result(
    *,
    expanded: list[dict[str, Any]],
    seen: set[str],
    result: dict[str, Any],
    anchor_chunk_id: str,
) -> None:
    if anchor_chunk_id and anchor_chunk_id not in seen:
        seen.add(anchor_chunk_id)
    expanded.append(result)


def _neighbor_item(
    *,
    chunk: Any,
    result: dict[str, Any],
    anchor_chunk_id: str,
) -> dict[str, Any]:
    stored_meta = dict(getattr(chunk, "doc_metadata", None) or {})
    stored_meta.setdefault("tenant_id", str(getattr(chunk, "tenant_id", "") or ""))
    stored_meta.setdefault("document_id", str(getattr(chunk, "document_id", "") or ""))
    stored_meta.setdefault("chunk_index", int(getattr(chunk, "chunk_index", 0) or 0))
    stored_meta.setdefault("chunk_id", str(getattr(chunk, "id", "") or ""))
    if getattr(chunk, "page_number", None) is not None:
        stored_meta.setdefault("page", chunk.page_number)
    if not stored_meta.get("source"):
        stored_meta["source"] = "unknown"
    stored_meta["neighbor_of"] = anchor_chunk_id or None
    stored_meta["retrieval_role"] = "neighbor"
    anchor_score = float(result.get("score", 0.0) or 0.0)
    return {
        "chunk_id": str(getattr(chunk, "id", "") or ""),
        "content": str(getattr(chunk, "content", "") or ""),
        "metadata": stored_meta,
        "score": float(anchor_score * 0.85) if anchor_score else 0.0,
    }


def _resolve_local_window(
    *,
    result: dict[str, Any],
    window: int,
    score_driven: bool,
    high_threshold: float,
    mid_threshold: float,
    high_span: int,
    mid_span: int,
) -> int:
    if not score_driven:
        return window
    try:
        score = float(result.get("score") or 0.0)
    except Exception:
        score = 0.0
    if score >= float(high_threshold):
        return min(window, _coerce_non_negative_int(high_span))
    if score >= float(mid_threshold):
        return min(window, _coerce_non_negative_int(mid_span))
    return 0


def _append_short_document_expansion(
    *,
    result: dict[str, Any],
    doc_key: str,
    document_chunks_by_doc: dict[str, list[Any]],
    sibling_max_added: int,
    original_map: dict[str, dict[str, Any]],
    expanded: list[dict[str, Any]],
    seen: set[str],
    processed_short_docs: set[str],
) -> int:
    sibling_added = 0
    sibling_items = expand_document_siblings(
        results=[result],
        document_chunks_by_doc=document_chunks_by_doc,
        short_doc_ids={doc_key},
        max_added=sibling_max_added,
        original_results_by_chunk_id=original_map,
    )
    for item in sibling_items:
        chunk_id = _chunk_id_from_item(item)
        if chunk_id in seen:
            expanded.append(item)
            continue
        if str((item.get("metadata") or {}).get("retrieval_role") or "").strip() == "sibling":
            sibling_added += 1
        seen.add(chunk_id)
        expanded.append(item)
    processed_short_docs.add(doc_key)
    return sibling_added


def _append_neighbor_window(
    *,
    result: dict[str, Any],
    doc_key: str,
    chunk_index: int,
    local_window: int,
    max_added: int,
    neighbors_by_pair: dict[tuple[str, int], Any],
    anchor_chunk_id: str,
    anchor_header_path: str | None,
    score_driven: bool,
    expanded: list[dict[str, Any]],
    pending_score_neighbors: list[dict[str, Any]],
    seen: set[str],
    neighbor_added: int,
) -> int:
    if score_driven:
        _append_anchor_result(
            expanded=expanded,
            seen=seen,
            result=result,
            anchor_chunk_id=anchor_chunk_id,
        )
    for neighbor_index in range(chunk_index - local_window, chunk_index + local_window + 1):
        if _append_anchor_for_window_index(
            neighbor_index=neighbor_index,
            chunk_index=chunk_index,
            score_driven=score_driven,
            expanded=expanded,
            seen=seen,
            result=result,
            anchor_chunk_id=anchor_chunk_id,
        ):
            continue
        neighbor_chunk = _eligible_neighbor_chunk(
            neighbors_by_pair=neighbors_by_pair,
            doc_key=doc_key,
            neighbor_index=neighbor_index,
            max_added=max_added,
            neighbor_added=neighbor_added,
            seen=seen,
            anchor_header_path=anchor_header_path,
        )
        if neighbor_chunk is None:
            continue
        item = _neighbor_item(
            chunk=neighbor_chunk,
            result=result,
            anchor_chunk_id=anchor_chunk_id,
        )
        if score_driven:
            pending_score_neighbors.append(item)
        else:
            expanded.append(item)
        seen.add(str(getattr(neighbor_chunk, "id", "") or "").strip())
        neighbor_added += 1
    return neighbor_added


def _append_anchor_for_window_index(
    *,
    neighbor_index: int,
    chunk_index: int,
    score_driven: bool,
    expanded: list[dict[str, Any]],
    seen: set[str],
    result: dict[str, Any],
    anchor_chunk_id: str,
) -> bool:
    if neighbor_index < 0:
        return True
    if neighbor_index != chunk_index:
        return False
    if not score_driven:
        _append_anchor_result(
            expanded=expanded,
            seen=seen,
            result=result,
            anchor_chunk_id=anchor_chunk_id,
        )
    return True


def _eligible_neighbor_chunk(
    *,
    neighbors_by_pair: dict[tuple[str, int], Any],
    doc_key: str,
    neighbor_index: int,
    max_added: int,
    neighbor_added: int,
    seen: set[str],
    anchor_header_path: str | None,
) -> Any | None:
    neighbor_chunk = neighbors_by_pair.get((doc_key, neighbor_index))
    if neighbor_chunk is None:
        return None
    neighbor_chunk_id = str(getattr(neighbor_chunk, "id", "") or "").strip()
    if not neighbor_chunk_id or neighbor_chunk_id in seen:
        return None
    if max_added and neighbor_added >= max_added:
        return None
    neighbor_header_path = _header_path_from_meta(dict(getattr(neighbor_chunk, "doc_metadata", None) or {}))
    if anchor_header_path and neighbor_header_path and neighbor_header_path != anchor_header_path:
        return None
    return neighbor_chunk


def _process_ranked_result(
    *,
    result: dict[str, Any],
    window: int,
    max_added: int,
    sibling_max_added: int,
    document_chunks_by_doc: dict[str, list[Any]],
    short_doc_ids: set[str],
    neighbors_by_pair: dict[tuple[str, int], Any],
    original_map: dict[str, dict[str, Any]],
    score_driven: bool,
    high_threshold: float,
    mid_threshold: float,
    high_span: int,
    mid_span: int,
    expanded: list[dict[str, Any]],
    pending_score_neighbors: list[dict[str, Any]],
    seen: set[str],
    processed_short_docs: set[str],
    strategies_used: set[str],
    neighbor_added: int,
) -> tuple[int, int]:
    meta = result.get("metadata") or {}
    anchor_chunk_id = _chunk_id_from_item(result)
    doc_key = str(meta.get("document_id") or "").strip()
    if doc_key in short_doc_ids:
        return _process_short_doc_result(
            result=result,
            doc_key=doc_key,
            document_chunks_by_doc=document_chunks_by_doc,
            sibling_max_added=sibling_max_added,
            original_map=original_map,
            expanded=expanded,
            seen=seen,
            processed_short_docs=processed_short_docs,
            strategies_used=strategies_used,
            neighbor_added=neighbor_added,
        )
    local_window = _resolve_local_window(
        result=result,
        window=window,
        score_driven=score_driven,
        high_threshold=high_threshold,
        mid_threshold=mid_threshold,
        high_span=high_span,
        mid_span=mid_span,
    )
    return _process_windowed_result(
        result=result,
        doc_key=doc_key,
        chunk_index=_coerce_chunk_index(meta),
        local_window=local_window,
        max_added=max_added,
        neighbors_by_pair=neighbors_by_pair,
        anchor_chunk_id=anchor_chunk_id,
        anchor_header_path=_header_path_from_meta(meta),
        score_driven=score_driven,
        expanded=expanded,
        pending_score_neighbors=pending_score_neighbors,
        seen=seen,
        strategies_used=strategies_used,
        neighbor_added=neighbor_added,
    )


def _process_short_doc_result(
    *,
    result: dict[str, Any],
    doc_key: str,
    document_chunks_by_doc: dict[str, list[Any]],
    sibling_max_added: int,
    original_map: dict[str, dict[str, Any]],
    expanded: list[dict[str, Any]],
    seen: set[str],
    processed_short_docs: set[str],
    strategies_used: set[str],
    neighbor_added: int,
) -> tuple[int, int]:
    if doc_key in processed_short_docs:
        return neighbor_added, 0
    strategies_used.add("sibling")
    sibling_added = _append_short_document_expansion(
        result=result,
        doc_key=doc_key,
        document_chunks_by_doc=document_chunks_by_doc,
        sibling_max_added=sibling_max_added,
        original_map=original_map,
        expanded=expanded,
        seen=seen,
        processed_short_docs=processed_short_docs,
    )
    return neighbor_added, sibling_added


def _process_windowed_result(
    *,
    result: dict[str, Any],
    doc_key: str,
    chunk_index: int | None,
    local_window: int,
    max_added: int,
    neighbors_by_pair: dict[tuple[str, int], Any],
    anchor_chunk_id: str,
    anchor_header_path: str | None,
    score_driven: bool,
    expanded: list[dict[str, Any]],
    pending_score_neighbors: list[dict[str, Any]],
    seen: set[str],
    strategies_used: set[str],
    neighbor_added: int,
) -> tuple[int, int]:
    if doc_key and chunk_index is not None and local_window > 0:
        strategies_used.add("neighbor_score" if score_driven else "neighbor")
        neighbor_added = _append_neighbor_window(
            result=result,
            doc_key=doc_key,
            chunk_index=chunk_index,
            local_window=local_window,
            max_added=max_added,
            neighbors_by_pair=neighbors_by_pair,
            anchor_chunk_id=anchor_chunk_id,
            anchor_header_path=anchor_header_path,
            score_driven=score_driven,
            expanded=expanded,
            pending_score_neighbors=pending_score_neighbors,
            seen=seen,
            neighbor_added=neighbor_added,
        )
        return neighbor_added, 0
    _append_anchor_result(
        expanded=expanded,
        seen=seen,
        result=result,
        anchor_chunk_id=anchor_chunk_id,
    )
    return neighbor_added, 0


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

    window_i = _coerce_non_negative_int(window)
    max_added_i = _coerce_non_negative_int(max_added)
    sibling_max_added_i = _coerce_non_negative_int(sibling_max_added)
    document_chunks_by_doc = dict(document_chunks_by_doc or {})
    short_doc_ids = _normalize_short_doc_ids(short_doc_ids)
    neighbors_by_pair = dict(neighbors_by_pair or {})

    if window_i <= 0 and not short_doc_ids:
        return results, {"enabled": False, "reason": "disabled"}

    seen: set[str] = set()
    original_map = _build_original_result_map(results, original_results_by_chunk_id)
    expanded: list[dict[str, Any]] = []
    processed_short_docs: set[str] = set()
    neighbor_added = 0
    sibling_added = 0
    strategies_used: set[str] = set()
    pending_score_neighbors: list[dict[str, Any]] = []

    for result in results:
        if not isinstance(result, dict):
            continue
        neighbor_added, added_siblings = _process_ranked_result(
            result=result,
            window=window_i,
            max_added=max_added_i,
            sibling_max_added=sibling_max_added_i,
            document_chunks_by_doc=document_chunks_by_doc,
            short_doc_ids=short_doc_ids,
            neighbors_by_pair=neighbors_by_pair,
            original_map=original_map,
            score_driven=score_driven,
            high_threshold=high_threshold,
            mid_threshold=mid_threshold,
            high_span=high_span,
            mid_span=mid_span,
            expanded=expanded,
            pending_score_neighbors=pending_score_neighbors,
            seen=seen,
            processed_short_docs=processed_short_docs,
            strategies_used=strategies_used,
            neighbor_added=neighbor_added,
        )
        sibling_added += added_siblings

    if pending_score_neighbors:
        expanded.extend(pending_score_neighbors)

    if len(strategies_used) > 1:
        strategy = "mixed"
    elif strategies_used:
        strategy = next(iter(strategies_used))
    else:
        strategy = "none"

    meta = {
        "enabled": True,
        "framework": "context_expansion",
        "strategy": strategy,
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
