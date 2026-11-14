"""Pure document/query utilities for the RAGEngine (no engine state).

Must not import ``app.rag.engine`` or ``app.rag.retrieval.orchestrator``.
All methods are staticmethods/classmethods and hold no instance state.
"""

from collections.abc import Callable
from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.core.hashing import stable_hash


def fuse_doc_lists(
    doc_lists: list[list[Document]],
    *,
    fuse_docs_rrf: Callable[..., list[Document]],
    rrf_k: int,
) -> list[Document]:
    if len(doc_lists) == 1:
        return doc_lists[0] or []
    return fuse_docs_rrf(doc_lists, rrf_k=rrf_k, meta_prefix="query_expansion")


class DocUtilsMixin:
    """Owns doc identity/dedup/annotation helpers and RRF fusion."""

    @staticmethod
    def _doc_key(doc: Document) -> str:
        meta = doc.metadata
        doc_id = meta.get("document_id")
        chunk_index = meta.get("chunk_index")
        if doc_id is not None and chunk_index is not None:
            return f"{doc_id}:{chunk_index}"
        cid = doc.id or meta.get("chunk_id")
        if cid:
            return str(cid)
        content = doc.page_content.strip()
        return f"content:{stable_hash(content)}"

    @staticmethod
    def _normalize_query_text(text: str) -> str:
        return " ".join(text.split())

    @classmethod
    def _dedup_retrieval_queries(cls, queries: list[tuple[str, str]]) -> list[tuple[str, str]]:
        if not queries:
            return []
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for kind, q in queries:
            norm = cls._normalize_query_text(q)
            if not norm:
                continue
            key = norm.casefold() if norm.isascii() else norm
            if key in seen:
                continue
            seen.add(key)
            out.append((kind, norm))
        return out

    @staticmethod
    def _annotate_docs_with_role(docs: list[Document], role: str) -> list[Document]:
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

    @staticmethod
    def _merge_meta(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
        for k, v in src.items():
            if k not in dst or dst.get(k) in (None, "", [], {}):
                dst[k] = v
        return dst

    @staticmethod
    def _doc_is_reranked(doc: Document) -> bool:
        meta = doc.metadata
        return meta.get("rerank_score") is not None

    @classmethod
    def _prefer_doc(cls, current: Document, candidate: Document) -> Document:
        if cls._doc_is_reranked(candidate) and not cls._doc_is_reranked(current):
            return candidate
        if cls._doc_is_reranked(current) and not cls._doc_is_reranked(candidate):
            return current
        a = float(current.metadata.get("score", 0.0) or 0.0)
        b = float(candidate.metadata.get("score", 0.0) or 0.0)
        return candidate if b > a else current

    @classmethod
    def fuse_docs_rrf(
        cls,
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
                key = cls._doc_key(doc)
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
                    merged_meta[key] = cls._merge_meta(merged_meta[key], meta)
                    best_docs[key] = cls._prefer_doc(best_docs[key], doc)

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
