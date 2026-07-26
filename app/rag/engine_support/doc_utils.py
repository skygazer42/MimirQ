"""Pure document/query utility mixin for the RAGEngine (no engine state).

Must not import ``app.rag.engine`` or ``app.rag.retrieval.orchestrator``.
All methods are staticmethods/classmethods and hold no instance state.
"""

from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.core.hashing import stable_hash


class DocUtilsMixin:
    """Owns doc identity/dedup/annotation helpers and RRF fusion."""

    @staticmethod
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

    @staticmethod
    def _normalize_query_text(text: str) -> str:
        return " ".join((text or "").strip().split())

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
        for d in docs:
            meta = dict(d.metadata or {})
            if str(role or "").strip() == "main":
                meta.setdefault("retrieval_role", "main")
            else:
                meta["retrieval_role"] = str(role or "").strip() or "main"
            out.append(
                Document(
                    page_content=d.page_content,
                    metadata=meta,
                    id=getattr(d, "id", None) or meta.get("chunk_id"),
                )
            )
        return out

    @staticmethod
    def _merge_meta(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
        for k, v in (src or {}).items():
            if k not in dst or dst.get(k) in (None, "", [], {}):
                dst[k] = v
        return dst

    @staticmethod
    def _doc_is_reranked(doc: Document) -> bool:
        meta = doc.metadata or {}
        return meta.get("rerank_score") is not None

    @classmethod
    def _prefer_doc(cls, current: Document, candidate: Document) -> Document:
        if cls._doc_is_reranked(candidate) and not cls._doc_is_reranked(current):
            return candidate
        if cls._doc_is_reranked(current) and not cls._doc_is_reranked(candidate):
            return current
        a = float((current.metadata or {}).get("score", 0.0) or 0.0)
        b = float((candidate.metadata or {}).get("score", 0.0) or 0.0)
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

        k0 = int(rrf_k or 0) or int(settings.RETRIEVAL_RRF_K or 60)
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

                score_map[key] = float(score_map.get(key, 0.0) or 0.0) + (1.0 / (k0 + rank))
                hit_counts[key] = int(hit_counts.get(key, 0) or 0) + 1

                meta = dict(doc.metadata or {})
                if key not in best_docs:
                    best_docs[key] = doc
                    merged_meta[key] = meta
                else:
                    merged_meta[key] = cls._merge_meta(merged_meta.get(key) or {}, meta)
                    best_docs[key] = cls._prefer_doc(best_docs[key], doc)

        if not score_map:
            return []

        raw_scores = list(score_map.values())
        min_s = min(raw_scores) if raw_scores else 0.0
        max_s = max(raw_scores) if raw_scores else 0.0
        # When every fused doc shares one RRF score (single hit, or all docs hit
        # the same number of queries at the same rank), min == max. Min-max
        # normalization would map them all to 0.0 and wipe out the signal, so
        # treat that degenerate case as "uniformly relevant" (1.0) instead.
        degenerate_range = not (max_s > min_s)
        rng = 1.0 if degenerate_range else (max_s - min_s)

        fused_items: list[tuple[str, Document]] = []
        for key, doc in best_docs.items():
            meta = dict(merged_meta.get(key) or {})
            base_score = meta.get("score")
            if base_score is not None and f"{meta_prefix}_base_score" not in meta:
                meta[f"{meta_prefix}_base_score"] = base_score
            raw_rrf = float(score_map.get(key, 0.0) or 0.0)
            meta[f"{meta_prefix}_rrf_raw"] = raw_rrf
            meta[f"{meta_prefix}_rrf_k"] = k0
            meta[f"{meta_prefix}_hits"] = int(hit_counts.get(key, 0) or 0)
            meta[f"{meta_prefix}_fused"] = True
            meta["score"] = 1.0 if degenerate_range else (raw_rrf - min_s) / rng
            fused_items.append(
                (
                    key,
                    Document(
                    page_content=doc.page_content,
                    metadata=meta,
                    id=getattr(doc, "id", None) or meta.get("chunk_id"),
                )
                ),
            )

        # Deterministic tie-breakers are important for replay/regression:
        # prefer higher hit-count across queries, then higher base score, then doc key.
        def _sort_key(item: tuple[str, Document]) -> tuple[float, float, int, float, str]:
            k, d = item
            m = d.metadata or {}
            fused_score = float(m.get("score", 0.0) or 0.0)
            raw = float(m.get(f"{meta_prefix}_rrf_raw", 0.0) or 0.0)
            hits = int(m.get(f"{meta_prefix}_hits", 0) or 0)
            base = float(m.get(f"{meta_prefix}_base_score", 0.0) or 0.0)
            return (-fused_score, -raw, -hits, -base, k)

        fused_items.sort(key=_sort_key)
        return [d for _k, d in fused_items]
