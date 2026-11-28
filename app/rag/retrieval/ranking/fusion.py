"""Role annotations and deterministic RRF document fusion."""

from typing import Any

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.rag.retrieval.results import document_key


def annotate_documents_with_role(docs: list[Document], role: str) -> list[Document]:
    if not docs:
        return []
    out: list[Document] = []
    normalized_role = role.strip()
    for d in docs:
        meta = dict(d.metadata)
        if normalized_role == "main":
            meta.setdefault("retrieval_role", "main")
        else:
            meta["retrieval_role"] = normalized_role or "main"
        out.append(
            Document(
                page_content=d.page_content,
                metadata=meta,
                id=d.id or meta.get("chunk_id"),
            )
        )
    return out


def _merge_metadata(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    for k, v in src.items():
        if k not in dst or dst.get(k) in (None, "", [], {}):
            dst[k] = v
    return dst


def _is_reranked(doc: Document) -> bool:
    meta = doc.metadata
    return meta.get("rerank_score") is not None


def prefer_document(current: Document, candidate: Document) -> Document:
    if _is_reranked(candidate) and not _is_reranked(current):
        return candidate
    if _is_reranked(current) and not _is_reranked(candidate):
        return current
    a = float(current.metadata.get("score", 0.0) or 0.0)
    b = float(candidate.metadata.get("score", 0.0) or 0.0)
    return candidate if b > a else current


def fuse_docs_rrf(
    docs_by_query: list[list[Document]],
    *,
    rrf_k: int | None = None,
    meta_prefix: str = "query_expansion",
) -> list[Document]:
    if not docs_by_query:
        return []

    k0 = int(rrf_k or 0) or int(settings.RETRIEVAL_RRF_K)
    k0 = max(1, k0)

    score_map: dict[str, float] = {}
    hit_counts: dict[str, int] = {}
    best_docs: dict[str, Document] = {}
    merged_meta: dict[str, dict[str, Any]] = {}

    for docs in docs_by_query:
        seen_in_query: set[str] = set()
        for rank, doc in enumerate(docs or [], 1):
            key = document_key(doc)
            if key in seen_in_query:
                continue
            seen_in_query.add(key)

            score_map[key] = score_map.get(key, 0.0) + (1.0 / (k0 + rank))
            hit_counts[key] = hit_counts.get(key, 0) + 1

            meta = dict(doc.metadata)
            if key not in best_docs:
                best_docs[key] = doc
                merged_meta[key] = meta
            else:
                merged_meta[key] = _merge_metadata(merged_meta[key], meta)
                best_docs[key] = prefer_document(best_docs[key], doc)

    if not score_map:
        return []

    raw_scores = list(score_map.values())
    min_s = min(raw_scores)
    max_s = max(raw_scores)
    # When every fused doc shares one RRF score (single hit, or all docs hit
    # the same number of queries at the same rank), min == max. Min-max
    # normalization would map them all to 0.0 and wipe out the signal, so
    # treat that degenerate case as "uniformly relevant" (1.0) instead.
    degenerate_range = not (max_s > min_s)
    rng = 1.0 if degenerate_range else (max_s - min_s)

    fused_items: list[tuple[str, Document]] = []
    for key, doc in best_docs.items():
        meta = dict(merged_meta[key])
        base_score = meta.get("score")
        if base_score is not None and f"{meta_prefix}_base_score" not in meta:
            meta[f"{meta_prefix}_base_score"] = base_score
        raw_rrf = score_map[key]
        meta[f"{meta_prefix}_rrf_raw"] = raw_rrf
        meta[f"{meta_prefix}_rrf_k"] = k0
        meta[f"{meta_prefix}_hits"] = hit_counts[key]
        meta[f"{meta_prefix}_fused"] = True
        meta["score"] = 1.0 if degenerate_range else (raw_rrf - min_s) / rng
        fused_items.append(
            (
                key,
                Document(
                    page_content=doc.page_content,
                    metadata=meta,
                    id=doc.id or meta.get("chunk_id"),
                ),
            ),
        )

    # Deterministic tie-breakers are important for replay/regression:
    # prefer higher hit-count across queries, then higher base score, then doc key.
    def _sort_key(item: tuple[str, Document]) -> tuple[float, float, int, float, str]:
        k, d = item
        m = d.metadata
        fused_score = m["score"]
        raw = m[f"{meta_prefix}_rrf_raw"]
        hits = m[f"{meta_prefix}_hits"]
        base = float(m.get(f"{meta_prefix}_base_score", 0.0) or 0.0)
        return (-fused_score, -raw, -hits, -base, k)

    fused_items.sort(key=_sort_key)
    return [d for _k, d in fused_items]


def fuse_doc_lists(
    doc_lists: list[list[Document]],
    *,
    rrf_k: int,
) -> list[Document]:
    if len(doc_lists) == 1:
        return doc_lists[0] or []
    return fuse_docs_rrf(doc_lists, rrf_k=rrf_k, meta_prefix="query_expansion")
