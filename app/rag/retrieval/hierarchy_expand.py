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
    raw = meta.get("hierarchy_parent_key") if "hierarchy_parent_key" in meta else (meta.get("parent_id") or meta.get("parent_node_id"))
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

    try:
        depth = int(parent_depth or 0)
    except Exception:
        depth = 0
    try:
        window = int(sibling_window or 0)
    except Exception:
        window = 0
    depth = max(0, depth)
    window = max(0, window)

    if depth <= 0 and window <= 0:
        return docs_list, {"enabled": False, "reason": "disabled"}

    try:
        cap = int(max_added_docs or 0)
    except Exception:
        cap = 0
    cap = max(0, cap)
    if cap <= 0:
        return docs_list, {"enabled": False, "reason": "max_added_docs_le_0"}

    anchors = _iter_anchors(docs_list)
    if not anchors:
        return docs_list, {"enabled": False, "reason": "no_expandable_anchors"}

    cache: dict[tuple[str, str], Document] = {}

    def _fetch(pairs: set[tuple[str, str]]) -> None:
        if not pairs:
            return
        missing = {p for p in pairs if p not in cache}
        if not missing:
            return
        fetched = fetch_by_key(missing) or {}
        for k, v in fetched.items():
            if not isinstance(k, tuple) or len(k) != 2:
                continue
            if not isinstance(v, Document):
                continue
            cache[k] = v

    # Parent chains (batched per depth hop).
    parents_by_anchor: dict[str, list[str]] = {}
    current_parent_by_anchor: dict[str, str] = {}
    for a in anchors:
        meta = getattr(a, "metadata", None) or {}
        ak = _doc_key(a)
        current_parent_by_anchor[ak] = _parent_key(meta)

    for _hop in range(depth):
        pending: set[tuple[str, str]] = set()
        for a in anchors:
            meta = getattr(a, "metadata", None) or {}
            ak = _doc_key(a)
            doc_id = _sig(meta.get("document_id"))
            pk = current_parent_by_anchor.get(ak) or ""
            if not doc_id or not pk:
                continue
            pending.add((doc_id, pk))
            parents_by_anchor.setdefault(ak, []).append(pk)
        _fetch(pending)
        # Advance hop pointers
        for a in anchors:
            ak = _doc_key(a)
            keys = parents_by_anchor.get(ak) or []
            if not keys:
                current_parent_by_anchor[ak] = ""
                continue
            last = keys[-1]
            doc_id = _sig((getattr(a, "metadata", None) or {}).get("document_id"))
            if not doc_id:
                current_parent_by_anchor[ak] = ""
                continue
            parent_doc = cache.get((doc_id, last))
            meta2 = getattr(parent_doc, "metadata", None) if parent_doc is not None else None
            current_parent_by_anchor[ak] = _parent_key(meta2 if isinstance(meta2, dict) else {})

    # Sibling chains (batched per window step).
    prev_keys_by_anchor: dict[str, list[str]] = {}
    next_keys_by_anchor: dict[str, list[str]] = {}
    current_prev_by_anchor: dict[str, str] = {}
    current_next_by_anchor: dict[str, str] = {}
    for a in anchors:
        meta = getattr(a, "metadata", None) or {}
        ak = _doc_key(a)
        current_prev_by_anchor[ak] = _prev_key(meta)
        current_next_by_anchor[ak] = _next_key(meta)

    for _step in range(window):
        pending2: set[tuple[str, str]] = set()
        for a in anchors:
            meta = getattr(a, "metadata", None) or {}
            ak = _doc_key(a)
            doc_id = _sig(meta.get("document_id"))
            pk = current_prev_by_anchor.get(ak) or ""
            nk = current_next_by_anchor.get(ak) or ""
            if doc_id and pk:
                pending2.add((doc_id, pk))
                prev_keys_by_anchor.setdefault(ak, []).append(pk)
            if doc_id and nk:
                pending2.add((doc_id, nk))
                next_keys_by_anchor.setdefault(ak, []).append(nk)
        _fetch(pending2)
        for a in anchors:
            meta = getattr(a, "metadata", None) or {}
            ak = _doc_key(a)
            doc_id = _sig(meta.get("document_id"))
            prev_list = prev_keys_by_anchor.get(ak) or []
            next_list = next_keys_by_anchor.get(ak) or []
            if doc_id and prev_list:
                last_prev = prev_list[-1]
                doc_prev = cache.get((doc_id, last_prev))
                current_prev_by_anchor[ak] = _prev_key((doc_prev.metadata or {}) if doc_prev is not None else {})
            else:
                current_prev_by_anchor[ak] = ""
            if doc_id and next_list:
                last_next = next_list[-1]
                doc_next = cache.get((doc_id, last_next))
                current_next_by_anchor[ak] = _next_key((doc_next.metadata or {}) if doc_next is not None else {})
            else:
                current_next_by_anchor[ak] = ""

    # Build expanded output in original doc order: for each anchor, emit
    # [parents..., prev siblings..., anchor, next siblings...]. Non-anchor docs
    # are emitted as-is, preserving their relative position.
    expanded: list[Document] = []
    seen: set[str] = set()
    anchor_keys = {_doc_key(a) for a in anchors}
    original_keys = {_doc_key(d) for d in docs_list if d is not None}

    added = 0
    added_parents = 0
    added_siblings = 0
    skipped_cross_record_siblings = 0

    def _append(doc: Document) -> None:
        if doc is None:
            return
        dk = _doc_key(doc)
        if dk in seen:
            return
        expanded.append(doc)
        seen.add(dk)

    def _add(
        doc: Document,
        *,
        role: str,
        neighbor_of: str | None,
        base_score: float,
        score_scale: float,
        anchor_meta: dict[str, Any] | None = None,
    ) -> None:
        nonlocal added, added_parents, added_siblings, skipped_cross_record_siblings
        if doc is None:
            return
        if cap and added >= cap:
            return
        dk = _doc_key(doc)
        # Don't insert docs that are already present in the original candidate list; preserve
        # original ordering/grouping for those.
        if dk in original_keys:
            return
        if dk in seen:
            return
        meta = dict(getattr(doc, "metadata", None) or {})
        if str(role or "") == "hierarchy_sibling":
            anchor_identity = _record_identity_key(anchor_meta or {})
            if anchor_identity:
                sibling_identity = _record_identity_key(meta)
                if sibling_identity != anchor_identity:
                    skipped_cross_record_siblings += 1
                    return
        meta["retrieval_role"] = str(role or "").strip() or "hierarchy"
        if neighbor_of is not None and str(neighbor_of).strip():
            meta["neighbor_of"] = str(neighbor_of).strip()
        # Keep expansion docs lower-scored than their anchor; this reduces the chance that
        # downstream consumers treat them as the "main" evidence.
        s = float(base_score) * float(score_scale)
        meta.setdefault("retrieval_score", s)
        meta["score"] = s

        expanded.append(
            Document(
                page_content=doc.page_content,
                metadata=meta,
                id=getattr(doc, "id", None) or meta.get("chunk_id"),
            )
        )
        seen.add(dk)
        added += 1
        if str(role).startswith("hierarchy_parent"):
            added_parents += 1
        else:
            added_siblings += 1

    for d in docs_list:
        dk = _doc_key(d)
        if dk not in anchor_keys:
            _append(d)
            continue

        ameta = getattr(d, "metadata", None) or {}
        doc_id = _sig(ameta.get("document_id"))
        if not doc_id:
            _append(d)
            continue
        anchor_chunk_id = _sig(getattr(d, "id", None) or ameta.get("chunk_id") or "")
        anchor_score = _score(ameta)
        ak = dk

        parent_keys = list(parents_by_anchor.get(ak) or [])
        parent_keys.reverse()
        for pk in parent_keys:
            doc_parent = cache.get((doc_id, pk))
            if doc_parent is None:
                continue
            _add(
                doc_parent,
                role="hierarchy_parent",
                neighbor_of=anchor_chunk_id or None,
                base_score=anchor_score,
                score_scale=0.92,
                anchor_meta=ameta,
            )

        prev_keys = list(prev_keys_by_anchor.get(ak) or [])
        prev_keys.reverse()
        for sk in prev_keys:
            doc_sib = cache.get((doc_id, sk))
            if doc_sib is None:
                continue
            _add(
                doc_sib,
                role="hierarchy_sibling",
                neighbor_of=anchor_chunk_id or None,
                base_score=anchor_score,
                score_scale=0.85,
                anchor_meta=ameta,
            )

        _append(d)

        for sk in next_keys_by_anchor.get(ak) or []:
            doc_sib = cache.get((doc_id, sk))
            if doc_sib is None:
                continue
            _add(
                doc_sib,
                role="hierarchy_sibling",
                neighbor_of=anchor_chunk_id or None,
                base_score=anchor_score,
                score_scale=0.85,
                anchor_meta=ameta,
            )

    meta_out = {
        "enabled": True,
        "parent_depth": int(depth),
        "sibling_window": int(window),
        "anchors": int(len(anchors)),
        "added_docs": int(added),
        "added_parents": int(added_parents),
        "added_siblings": int(added_siblings),
        "skipped_cross_record_siblings": int(skipped_cross_record_siblings),
        "max_added_docs": int(cap),
        "cache_size": int(len(cache)),
    }
    return expanded, meta_out


__all__ = ["expand_hierarchy_context", "FetchByHierarchyKey"]
