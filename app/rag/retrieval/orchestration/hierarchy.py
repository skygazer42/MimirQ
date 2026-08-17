"""Hierarchy family aggregation and ancestor-wins tree dedup for retrieval results.

Split out of ``app.rag.retrieval.orchestrator`` (see
``app.rag.retrieval.orchestration``).
"""

from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from app.rag.retrieval.orchestration.common import _doc_key, _safe_int


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
        except (TypeError, ValueError, AttributeError):
            continue
    return 0.0


def _update_hierarchy_family_feature(
    *,
    family_key: str,
    rank: int,
    score: float,
    doc_hits: dict[str, int],
    best_rank: dict[str, int],
    best_score: dict[str, float],
) -> None:
    doc_hits[family_key] = int(doc_hits.get(family_key, 0) or 0) + 1
    if family_key not in best_rank or rank < int(best_rank.get(family_key) or 0):
        best_rank[family_key] = int(rank)
    if family_key not in best_score or float(score) > float(best_score.get(family_key) or 0.0):
        best_score[family_key] = float(score)


def _build_hierarchy_family_feature_payload(
    family_key: str,
    *,
    variant_hits: dict[str, int],
    doc_hits: dict[str, int],
    best_rank: dict[str, int],
    best_score: dict[str, float],
) -> dict[str, Any]:
    return {
        "variant_hits": int(variant_hits.get(family_key, 0) or 0),
        "doc_hits": int(doc_hits.get(family_key, 0) or 0),
        "best_rank": int(best_rank.get(family_key, 0) or 0),
        "best_score": float(best_score.get(family_key, 0.0) or 0.0),
    }


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
            _update_hierarchy_family_feature(
                family_key=family_key,
                rank=rank,
                score=_doc_base_score(meta),
                doc_hits=doc_hits,
                best_rank=best_rank,
                best_score=best_score,
            )
        for fk in seen_in_variant:
            variant_hits[fk] = int(variant_hits.get(fk, 0) or 0) + 1

    out: dict[str, dict[str, Any]] = {}
    all_keys = set(variant_hits) | set(doc_hits) | set(best_rank) | set(best_score)
    for fk in all_keys:
        out[fk] = _build_hierarchy_family_feature_payload(
            fk,
            variant_hits=variant_hits,
            doc_hits=doc_hits,
            best_rank=best_rank,
            best_score=best_score,
        )
    return out


def _resolve_family_aggregation_strategy(
    docs: list[Document], family_features: dict[str, dict[str, Any]], strategy: str
) -> tuple[str, dict[str, Any] | None]:
    if not docs:
        return "", {"enabled": False, "reason": "no_docs"}
    if not family_features:
        return "", {"enabled": False, "reason": "no_families"}
    strat = str(strategy or "").strip().lower()
    if strat not in {"frequency", "score", "combined"}:
        return strat, {"enabled": False, "reason": "invalid_strategy"}
    return strat, None


def _family_aggregation_sort_key(
    family_key: str,
    *,
    family_features: dict[str, dict[str, Any]],
    strategy: str,
) -> tuple[float, float, float, str]:
    feats = family_features.get(family_key) if family_key else None
    feats = feats if isinstance(feats, dict) else {}
    variant_hits = int(feats.get("variant_hits") or 0)
    best_rank = int(feats.get("best_rank") or 0) or 1_000_000
    best_score = float(feats.get("best_score") or 0.0)
    if strategy == "frequency":
        return (-float(variant_hits), float(best_rank), -float(best_score), family_key)
    if strategy == "score":
        return (-float(best_score), -float(variant_hits), float(best_rank), family_key)
    return (-float(variant_hits), -float(best_score), float(best_rank), family_key)


def _doc_stable_debug_id(doc: Document) -> str:
    meta = doc.metadata or {}
    return str(getattr(doc, "id", None) or meta.get("chunk_id") or "")


def _rank_hierarchy_family_docs(
    docs: list[Document],
    *,
    family_features: dict[str, dict[str, Any]],
    strategy: str,
) -> list[Document]:
    ranked: list[tuple[tuple[float, float, float, str], float, int, str, Document]] = []
    for index, doc in enumerate(docs):
        meta = doc.metadata or {}
        family_key = _resolve_hierarchy_family_collapse_key(meta)
        family_key_tuple = _family_aggregation_sort_key(
            family_key or "",
            family_features=family_features,
            strategy=strategy,
        )
        ranked.append((family_key_tuple, -float(_doc_base_score(meta)), int(index), _doc_stable_debug_id(doc), doc))
    ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return [doc for *_rest, doc in ranked]


def _family_aggregation_meta(
    *,
    docs: list[Document],
    out_docs: list[Document],
    family_features: dict[str, dict[str, Any]],
    strategy: str,
) -> dict[str, Any]:
    before_ids = [_doc_stable_debug_id(doc) for doc in docs]
    after_ids = [_doc_stable_debug_id(doc) for doc in out_docs]
    moved = sum(1 for index, doc_id in enumerate(after_ids) if index < len(before_ids) and doc_id != before_ids[index])
    return {
        "enabled": True,
        "strategy": strategy,
        "input_docs": int(len(docs)),
        "families": int(len(family_features)),
        "moved_positions": int(moved),
        "top_changed": bool(before_ids) and bool(after_ids) and before_ids[0] != after_ids[0],
    }


def _apply_hierarchy_family_aggregation(
    docs: list[Document],
    *,
    family_features: dict[str, dict[str, Any]],
    strategy: str,
) -> tuple[list[Document], dict[str, Any]]:
    strat, disabled_meta = _resolve_family_aggregation_strategy(docs, family_features, strategy)
    if disabled_meta is not None:
        return docs, disabled_meta
    out_docs = _rank_hierarchy_family_docs(docs, family_features=family_features, strategy=strat)
    return out_docs, _family_aggregation_meta(
        docs=docs,
        out_docs=out_docs,
        family_features=family_features,
        strategy=strat,
    )


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
    raw = (
        meta.get("hierarchy_parent_key")
        if "hierarchy_parent_key" in meta
        else (meta.get("parent_id") or meta.get("parent_node_id"))
    )
    s = str(raw or "").strip()
    return s if s else ""


@dataclass
class _HierarchyDedupState:
    seen_doc_keys: set[str]
    kept_doc_keys: set[str]
    kept_node_keys: set[str]
    order: list[str]
    doc_by_key: dict[str, Document]
    node_by_doc_key: dict[str, str]
    parent_by_doc_key: dict[str, str]
    children_by_parent_node: dict[str, set[str]]
    dropped_as_descendant: int = 0
    removed_by_ancestor: int = 0
    scanned_unique: int = 0


def _new_hierarchy_dedup_state() -> _HierarchyDedupState:
    return _HierarchyDedupState(
        seen_doc_keys=set(),
        kept_doc_keys=set(),
        kept_node_keys=set(),
        order=[],
        doc_by_key={},
        node_by_doc_key={},
        parent_by_doc_key={},
        children_by_parent_node={},
    )


def _hierarchy_dedup_limits(top_k: int, overfetch_factor: int) -> tuple[int, int, int, dict[str, Any] | None]:
    top_k_i = _safe_int(top_k)
    if top_k_i <= 0:
        return top_k_i, 1, 0, {"enabled": False, "reason": "top_k_le_0"}
    factor = max(1, _safe_int(overfetch_factor, default=1))
    max_candidates = max(int(top_k_i), int(top_k_i) * int(factor))
    return top_k_i, factor, max_candidates, None


def _hierarchy_dedup_candidates(primary_list: list[Document], refill: list[Document] | None) -> list[Document]:
    candidates: list[Document] = list(primary_list)
    if refill:
        candidates.extend([doc for doc in (refill or []) if doc is not None])
    return candidates


def _hierarchy_node_parent_keys(doc: Document) -> tuple[str, str]:
    meta = doc.metadata or {}
    node_key = _resolve_hierarchy_node_key(meta)
    parent_key = _resolve_hierarchy_parent_key(meta)
    if parent_key and node_key and parent_key == node_key:
        parent_key = ""
    return node_key, parent_key


def _remove_hierarchy_dedup_doc(state: _HierarchyDedupState, doc_key: str) -> int:
    if doc_key not in state.kept_doc_keys:
        return 0
    state.kept_doc_keys.discard(doc_key)
    state.removed_by_ancestor += 1

    node_key = state.node_by_doc_key.get(doc_key) or ""
    parent_key = state.parent_by_doc_key.get(doc_key) or ""
    if parent_key:
        kids = state.children_by_parent_node.get(parent_key)
        if kids:
            kids.discard(doc_key)
            if not kids:
                state.children_by_parent_node.pop(parent_key, None)

    if node_key:
        state.kept_node_keys.discard(node_key)
        for child_doc_key in state.children_by_parent_node.get(node_key, set()).copy():
            _remove_hierarchy_dedup_doc(state, child_doc_key)
        state.children_by_parent_node.pop(node_key, None)
    return 1


def _keep_hierarchy_dedup_doc(
    state: _HierarchyDedupState,
    *,
    doc_key: str,
    doc: Document,
    node_key: str,
    parent_key: str,
) -> None:
    state.doc_by_key[doc_key] = doc
    state.node_by_doc_key[doc_key] = node_key
    state.parent_by_doc_key[doc_key] = parent_key
    state.kept_doc_keys.add(doc_key)
    state.order.append(doc_key)
    if node_key:
        state.kept_node_keys.add(node_key)
    if parent_key:
        state.children_by_parent_node.setdefault(parent_key, set()).add(doc_key)
    if node_key:
        for child_doc_key in state.children_by_parent_node.get(node_key, set()).copy():
            _remove_hierarchy_dedup_doc(state, child_doc_key)
        if not state.children_by_parent_node.get(node_key):
            state.children_by_parent_node.pop(node_key, None)


def _scan_hierarchy_dedup_candidates(
    candidates: list[Document],
    *,
    max_candidates: int,
    state: _HierarchyDedupState,
) -> None:
    for doc in candidates:
        if doc is None:
            continue
        doc_key = _doc_key(doc)
        if doc_key in state.seen_doc_keys:
            continue
        state.seen_doc_keys.add(doc_key)
        state.scanned_unique += 1
        if state.scanned_unique > max_candidates:
            break

        node_key, parent_key = _hierarchy_node_parent_keys(doc)
        if parent_key and parent_key in state.kept_node_keys:
            state.dropped_as_descendant += 1
            continue
        _keep_hierarchy_dedup_doc(state, doc_key=doc_key, doc=doc, node_key=node_key, parent_key=parent_key)


def _hierarchy_dedup_output(state: _HierarchyDedupState, *, top_k: int) -> list[Document]:
    out: list[Document] = []
    for doc_key in state.order:
        if doc_key not in state.kept_doc_keys:
            continue
        doc = state.doc_by_key.get(doc_key)
        if doc is not None:
            out.append(doc)
    return out[: int(top_k)]


def _hierarchy_dedup_meta(
    *,
    top_k: int,
    factor: int,
    max_candidates: int,
    primary_list: list[Document],
    refill: list[Document] | None,
    out_sliced: list[Document],
    state: _HierarchyDedupState,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "top_k": int(top_k),
        "overfetch_factor": int(factor),
        "max_candidates": int(max_candidates),
        "scanned_unique": int(state.scanned_unique),
        "input_primary": int(len(primary_list)),
        "input_refill": int(len(refill or [])),
        "output": int(len(out_sliced)),
        "dropped_as_descendant": int(state.dropped_as_descendant),
        "removed_by_ancestor": int(state.removed_by_ancestor),
    }


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

    top_k_i, factor, max_candidates, disabled_meta = _hierarchy_dedup_limits(top_k, overfetch_factor)
    if disabled_meta is not None:
        return primary_list, disabled_meta

    state = _new_hierarchy_dedup_state()
    candidates = _hierarchy_dedup_candidates(primary_list, refill)
    _scan_hierarchy_dedup_candidates(candidates, max_candidates=max_candidates, state=state)
    out_sliced = _hierarchy_dedup_output(state, top_k=top_k_i)
    return out_sliced, _hierarchy_dedup_meta(
        top_k=top_k_i,
        factor=factor,
        max_candidates=max_candidates,
        primary_list=primary_list,
        refill=refill,
        out_sliced=out_sliced,
        state=state,
    )
