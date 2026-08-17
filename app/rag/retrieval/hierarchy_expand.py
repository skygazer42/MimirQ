"""
Hierarchy-aware context expansion utilities.

This module intentionally stays lightweight:
- No DB imports at import-time (orchestrator provides fetchers).
- Deterministic and PII-safe (operates on ids/keys, never on raw user query text).

Use-cases:
- After retrieving anchor chunks, expand to include parent / sibling nodes based on
  metadata-only hierarchy overlay (hierarchy_node_key, hierarchy_parent_key, prev/next keys).
"""

import hashlib
from collections.abc import Callable, Iterable
from typing import Any

from langchain_core.documents import Document

from app.rag.core.logging import get_logger

FetchByHierarchyKey = Callable[[set[tuple[str, str]]], dict[tuple[str, str], Document]]


def _sig(value: Any) -> str:
    s = str(value or "").strip()
    return s


def _doc_key(doc: Document) -> str:
    meta = getattr(doc, "metadata", None) or {}
    doc_id = meta.get("document_id")
    chunk_index = meta.get("chunk_index")
    if doc_id is not None and chunk_index is not None:
        return f"{doc_id}:{chunk_index}"
    cid = getattr(doc, "id", None) or meta.get("chunk_id")
    if cid:
        return str(cid)
    content = (doc.page_content or "").strip()
    digest = hashlib.blake2b(content.encode("utf-8", "ignore"), digest_size=16).hexdigest() if content else "empty"
    return f"content:{digest}"


def _node_key(meta: dict[str, Any]) -> str:
    return _sig(meta.get("hierarchy_node_key") or meta.get("chunk_key") or meta.get("chunk_id"))


def _parent_key(meta: dict[str, Any]) -> str:
    # Respect explicit hierarchy_parent_key=None; fall back only when field absent.
    raw = (
        meta.get("hierarchy_parent_key")
        if "hierarchy_parent_key" in meta
        else (meta.get("parent_id") or meta.get("parent_node_id"))
    )
    return _sig(raw)


def _prev_key(meta: dict[str, Any]) -> str:
    return _sig(meta.get("hierarchy_prev_sibling_key") or meta.get("prev_chunk_key"))


def _next_key(meta: dict[str, Any]) -> str:
    return _sig(meta.get("hierarchy_next_sibling_key") or meta.get("next_chunk_key"))


def _record_identity_key(meta: dict[str, Any]) -> str:
    raw = meta.get("_record_identity") or meta.get("record_identity")
    if not isinstance(raw, dict):
        return ""
    return _sig(raw.get("key"))


def _score(meta: dict[str, Any]) -> float:
    for k in ("score", "retrieval_score", "rerank_score", "vector_score", "bm25_score"):
        v = meta.get(k)
        if v is None:
            continue
        try:
            return float(v or 0.0)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
    return 0.0


def _iter_anchors(docs: Iterable[Document]) -> list[Document]:
    out: list[Document] = []
    for d in docs or []:
        if d is None:
            continue
        meta = getattr(d, "metadata", None) or {}
        if not _sig(meta.get("document_id")):
            continue
        # Only expand when we have a stable node key. If missing, the fetcher likely can't find it.
        if not _node_key(meta):
            continue
        out.append(d)
    return out


def _coerce_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _fetch_hierarchy_docs(
    *,
    cache: dict[tuple[str, str], Document],
    pairs: set[tuple[str, str]],
    fetch_by_key: FetchByHierarchyKey,
) -> None:
    missing = {pair for pair in pairs if pair not in cache}
    if not missing:
        return
    fetched = fetch_by_key(missing) or {}
    for key, value in fetched.items():
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        if isinstance(value, Document):
            cache[key] = value


def _anchor_doc_id(doc: Document) -> str:
    return _sig((getattr(doc, "metadata", None) or {}).get("document_id"))


def _collect_parent_chains(
    *,
    anchors: list[Document],
    depth: int,
    fetch_by_key: FetchByHierarchyKey,
    cache: dict[tuple[str, str], Document],
) -> dict[str, list[str]]:
    parents_by_anchor: dict[str, list[str]] = {}
    current_parent_by_anchor = {
        _doc_key(anchor): _parent_key(getattr(anchor, "metadata", None) or {}) for anchor in anchors
    }
    for _hop in range(depth):
        pending: set[tuple[str, str]] = set()
        for anchor in anchors:
            anchor_key = _doc_key(anchor)
            doc_id = _anchor_doc_id(anchor)
            parent_key = current_parent_by_anchor.get(anchor_key) or ""
            if not doc_id or not parent_key:
                continue
            pending.add((doc_id, parent_key))
            parents_by_anchor.setdefault(anchor_key, []).append(parent_key)
        _fetch_hierarchy_docs(cache=cache, pairs=pending, fetch_by_key=fetch_by_key)
        for anchor in anchors:
            anchor_key = _doc_key(anchor)
            current_parent_by_anchor[anchor_key] = _next_parent_key(
                cache=cache,
                doc_id=_anchor_doc_id(anchor),
                parent_keys=parents_by_anchor.get(anchor_key) or [],
            )
    return parents_by_anchor


def _next_parent_key(
    *,
    cache: dict[tuple[str, str], Document],
    doc_id: str,
    parent_keys: list[str],
) -> str:
    if not doc_id or not parent_keys:
        return ""
    parent_doc = cache.get((doc_id, parent_keys[-1]))
    meta = getattr(parent_doc, "metadata", None) if parent_doc is not None else None
    return _parent_key(meta if isinstance(meta, dict) else {})


def _collect_sibling_chains(
    *,
    anchors: list[Document],
    window: int,
    fetch_by_key: FetchByHierarchyKey,
    cache: dict[tuple[str, str], Document],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    prev_keys_by_anchor: dict[str, list[str]] = {}
    next_keys_by_anchor: dict[str, list[str]] = {}
    current_prev = {_doc_key(anchor): _prev_key(getattr(anchor, "metadata", None) or {}) for anchor in anchors}
    current_next = {_doc_key(anchor): _next_key(getattr(anchor, "metadata", None) or {}) for anchor in anchors}
    for _step in range(window):
        pending = _collect_sibling_pending_pairs(
            anchors=anchors,
            current_prev=current_prev,
            current_next=current_next,
            prev_keys_by_anchor=prev_keys_by_anchor,
            next_keys_by_anchor=next_keys_by_anchor,
        )
        _fetch_hierarchy_docs(cache=cache, pairs=pending, fetch_by_key=fetch_by_key)
        current_prev, current_next = _next_sibling_keys(
            anchors=anchors,
            cache=cache,
            prev_keys_by_anchor=prev_keys_by_anchor,
            next_keys_by_anchor=next_keys_by_anchor,
        )
    return prev_keys_by_anchor, next_keys_by_anchor


def _collect_sibling_pending_pairs(
    *,
    anchors: list[Document],
    current_prev: dict[str, str],
    current_next: dict[str, str],
    prev_keys_by_anchor: dict[str, list[str]],
    next_keys_by_anchor: dict[str, list[str]],
) -> set[tuple[str, str]]:
    pending: set[tuple[str, str]] = set()
    for anchor in anchors:
        anchor_key = _doc_key(anchor)
        doc_id = _anchor_doc_id(anchor)
        prev_key = current_prev.get(anchor_key) or ""
        next_key = current_next.get(anchor_key) or ""
        if doc_id and prev_key:
            pending.add((doc_id, prev_key))
            prev_keys_by_anchor.setdefault(anchor_key, []).append(prev_key)
        if doc_id and next_key:
            pending.add((doc_id, next_key))
            next_keys_by_anchor.setdefault(anchor_key, []).append(next_key)
    return pending


def _next_sibling_keys(
    *,
    anchors: list[Document],
    cache: dict[tuple[str, str], Document],
    prev_keys_by_anchor: dict[str, list[str]],
    next_keys_by_anchor: dict[str, list[str]],
) -> tuple[dict[str, str], dict[str, str]]:
    next_prev: dict[str, str] = {}
    next_next: dict[str, str] = {}
    for anchor in anchors:
        anchor_key = _doc_key(anchor)
        doc_id = _anchor_doc_id(anchor)
        next_prev[anchor_key] = _resolve_sibling_pointer(
            cache=cache,
            doc_id=doc_id,
            sibling_keys=prev_keys_by_anchor.get(anchor_key) or [],
            pointer_getter=_prev_key,
        )
        next_next[anchor_key] = _resolve_sibling_pointer(
            cache=cache,
            doc_id=doc_id,
            sibling_keys=next_keys_by_anchor.get(anchor_key) or [],
            pointer_getter=_next_key,
        )
    return next_prev, next_next


def _resolve_sibling_pointer(
    *,
    cache: dict[tuple[str, str], Document],
    doc_id: str,
    sibling_keys: list[str],
    pointer_getter: Callable[[dict[str, Any]], str],
) -> str:
    if not doc_id or not sibling_keys:
        return ""
    sibling_doc = cache.get((doc_id, sibling_keys[-1]))
    meta = getattr(sibling_doc, "metadata", None) if sibling_doc is not None else None
    return pointer_getter((meta or {}) if isinstance(meta, dict) else {})


def _append_unique(expanded: list[Document], seen: set[str], doc: Document) -> None:
    if doc is None:
        return
    doc_key = _doc_key(doc)
    if doc_key in seen:
        return
    expanded.append(doc)
    seen.add(doc_key)


def _add_hierarchy_doc(
    *,
    expanded: list[Document],
    seen: set[str],
    original_keys: set[str],
    doc: Document,
    role: str,
    neighbor_of: str | None,
    base_score: float,
    score_scale: float,
    anchor_meta: dict[str, Any] | None,
    stats: dict[str, int],
    cap: int,
) -> None:
    if doc is None or (cap and stats["added"] >= cap):
        return
    doc_key = _doc_key(doc)
    if doc_key in original_keys or doc_key in seen:
        return
    meta = dict(getattr(doc, "metadata", None) or {})
    if role == "hierarchy_sibling" and not _sibling_matches_anchor(anchor_meta or {}, meta):
        stats["skipped_cross_record_siblings"] += 1
        return
    meta["retrieval_role"] = role
    if neighbor_of:
        meta["neighbor_of"] = str(neighbor_of).strip()
    score = float(base_score) * float(score_scale)
    meta.setdefault("retrieval_score", score)
    meta["score"] = score
    expanded.append(
        Document(page_content=doc.page_content, metadata=meta, id=getattr(doc, "id", None) or meta.get("chunk_id"))
    )
    seen.add(doc_key)
    stats["added"] += 1
    if role.startswith("hierarchy_parent"):
        stats["added_parents"] += 1
    else:
        stats["added_siblings"] += 1


def _sibling_matches_anchor(anchor_meta: dict[str, Any], sibling_meta: dict[str, Any]) -> bool:
    anchor_identity = _record_identity_key(anchor_meta)
    if not anchor_identity:
        return True
    return _record_identity_key(sibling_meta) == anchor_identity


def _append_anchor_expansion(
    *,
    expanded: list[Document],
    seen: set[str],
    original_keys: set[str],
    anchor: Document,
    cache: dict[tuple[str, str], Document],
    parent_keys: list[str],
    prev_keys: list[str],
    next_keys: list[str],
    stats: dict[str, int],
    cap: int,
) -> None:
    anchor_meta = getattr(anchor, "metadata", None) or {}
    doc_id = _sig(anchor_meta.get("document_id"))
    anchor_chunk_id = _sig(getattr(anchor, "id", None) or anchor_meta.get("chunk_id") or "")
    anchor_score = _score(anchor_meta)
    for parent_key in reversed(parent_keys):
        _add_hierarchy_doc(
            expanded=expanded,
            seen=seen,
            original_keys=original_keys,
            doc=cache.get((doc_id, parent_key)),
            role="hierarchy_parent",
            neighbor_of=anchor_chunk_id or None,
            base_score=anchor_score,
            score_scale=0.92,
            anchor_meta=anchor_meta,
            stats=stats,
            cap=cap,
        )
    for sibling_key in reversed(prev_keys):
        _add_hierarchy_doc(
            expanded=expanded,
            seen=seen,
            original_keys=original_keys,
            doc=cache.get((doc_id, sibling_key)),
            role="hierarchy_sibling",
            neighbor_of=anchor_chunk_id or None,
            base_score=anchor_score,
            score_scale=0.85,
            anchor_meta=anchor_meta,
            stats=stats,
            cap=cap,
        )
    _append_unique(expanded, seen, anchor)
    for sibling_key in next_keys:
        _add_hierarchy_doc(
            expanded=expanded,
            seen=seen,
            original_keys=original_keys,
            doc=cache.get((doc_id, sibling_key)),
            role="hierarchy_sibling",
            neighbor_of=anchor_chunk_id or None,
            base_score=anchor_score,
            score_scale=0.85,
            anchor_meta=anchor_meta,
            stats=stats,
            cap=cap,
        )


def _build_expanded_docs(
    *,
    docs_list: list[Document],
    anchors: list[Document],
    parents_by_anchor: dict[str, list[str]],
    prev_keys_by_anchor: dict[str, list[str]],
    next_keys_by_anchor: dict[str, list[str]],
    cache: dict[tuple[str, str], Document],
    cap: int,
) -> tuple[list[Document], dict[str, int]]:
    expanded: list[Document] = []
    seen: set[str] = set()
    anchor_keys = {_doc_key(anchor) for anchor in anchors}
    original_keys = {_doc_key(doc) for doc in docs_list if doc is not None}
    stats = {"added": 0, "added_parents": 0, "added_siblings": 0, "skipped_cross_record_siblings": 0}
    for doc in docs_list:
        doc_key = _doc_key(doc)
        if doc_key not in anchor_keys:
            _append_unique(expanded, seen, doc)
            continue
        _append_anchor_expansion(
            expanded=expanded,
            seen=seen,
            original_keys=original_keys,
            anchor=doc,
            cache=cache,
            parent_keys=parents_by_anchor.get(doc_key) or [],
            prev_keys=prev_keys_by_anchor.get(doc_key) or [],
            next_keys=next_keys_by_anchor.get(doc_key) or [],
            stats=stats,
            cap=cap,
        )
    return expanded, stats


def expand_hierarchy_context(
    docs: list[Document],
    *,
    parent_depth: int,
    sibling_window: int,
    fetch_by_key: FetchByHierarchyKey,
    max_added_docs: int = 120,
) -> tuple[list[Document], dict[str, Any]]:
    """
    Expand retrieved anchors by adding parent and sibling nodes.

    Args:
        docs: Anchor docs (already retrieved/reranked).
        parent_depth: Max parent hops to add per anchor (0 disables).
        sibling_window: Sibling hops on each side to add per anchor (0 disables).
        fetch_by_key: Fetch callback: {(document_id, hierarchy_node_key)} -> Document.
        max_added_docs: Global cap for expansion additions across all anchors.

    Returns:
        (expanded_docs, meta)
    """
    docs_list = [d for d in (docs or []) if d is not None]
    if not docs_list:
        return docs_list, {"enabled": False, "reason": "no_docs"}

    depth = _coerce_non_negative_int(parent_depth)
    window = _coerce_non_negative_int(sibling_window)

    if depth <= 0 and window <= 0:
        return docs_list, {"enabled": False, "reason": "disabled"}

    cap = _coerce_non_negative_int(max_added_docs)
    if cap <= 0:
        return docs_list, {"enabled": False, "reason": "max_added_docs_le_0"}

    anchors = _iter_anchors(docs_list)
    if not anchors:
        return docs_list, {"enabled": False, "reason": "no_expandable_anchors"}

    cache: dict[tuple[str, str], Document] = {}
    parents_by_anchor = _collect_parent_chains(
        anchors=anchors,
        depth=depth,
        fetch_by_key=fetch_by_key,
        cache=cache,
    )
    prev_keys_by_anchor, next_keys_by_anchor = _collect_sibling_chains(
        anchors=anchors,
        window=window,
        fetch_by_key=fetch_by_key,
        cache=cache,
    )
    expanded, stats = _build_expanded_docs(
        docs_list=docs_list,
        anchors=anchors,
        parents_by_anchor=parents_by_anchor,
        prev_keys_by_anchor=prev_keys_by_anchor,
        next_keys_by_anchor=next_keys_by_anchor,
        cache=cache,
        cap=cap,
    )

    meta_out = {
        "enabled": True,
        "parent_depth": int(depth),
        "sibling_window": int(window),
        "anchors": int(len(anchors)),
        "added_docs": int(stats["added"]),
        "added_parents": int(stats["added_parents"]),
        "added_siblings": int(stats["added_siblings"]),
        "skipped_cross_record_siblings": int(stats["skipped_cross_record_siblings"]),
        "max_added_docs": int(cap),
        "cache_size": int(len(cache)),
    }
    return expanded, meta_out


__all__ = ["expand_hierarchy_context", "FetchByHierarchyKey"]
