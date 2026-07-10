"""
Deterministic RAPTOR-style chunking scaffold.

This is not the full paper implementation. It provides a production-safe
hierarchical contract that keeps the retrieval surface compatible with a
collapsed tree:
- leaf chunks (layer 0)
- summary parent chunks (layer 1)
"""


import re

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.strategies.semantic import SemanticSentenceChunker
from app.rag.chunking.utils.hierarchical import apply_sibling_hierarchy_links
from app.rag.core.hashing import stable_hash

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*|[\u4e00-\u9fff]{1,4}")


def _token_set(text: str) -> set[str]:
    return {str(tok or "").strip().casefold() for tok in _TOKEN_RE.findall(text or "") if str(tok or "").strip()}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union <= 0:
        return 0.0
    return float(inter) / float(union)


def build_semantic_leiden_proxy_clusters(
    texts: list[str],
    *,
    similarity_threshold: float = 0.2,
) -> list[list[int]]:
    """
    Deterministic proxy for Leiden clustering.

    We build a bounded similarity graph over semantic pre-chunks and return
    connected components in stable order. This is intentionally lightweight and
    serves as a safe stand-in for future Leiden/GMM clustering.
    """
    token_sets = [_token_set(text) for text in (texts or [])]
    n = len(token_sets)
    if n <= 0:
        return []

    visited: set[int] = set()
    clusters: list[list[int]] = []
    threshold = max(0.0, float(similarity_threshold or 0.0))

    for start in range(n):
        if start in visited:
            continue
        stack = [start]
        component: list[int] = []
        while stack:
            idx = stack.pop()
            if idx in visited:
                continue
            visited.add(idx)
            component.append(idx)
            for other in range(n):
                if other == idx or other in visited:
                    continue
                if _jaccard(token_sets[idx], token_sets[other]) >= threshold:
                    stack.append(other)
        clusters.append(sorted(component))

    clusters.sort(key=lambda cluster: (cluster[0], len(cluster)))
    return clusters


class RaptorChunker(BaseChunker):
    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: int,
        summary_cluster_size: int = 4,
        cluster_strategy: str = "sequential",
        similarity_threshold: float = 0.2,
    ) -> None:
        self.chunk_size = max(1, int(chunk_size or 1))
        self.chunk_overlap = max(0, int(chunk_overlap or 0))
        self.summary_cluster_size = max(2, int(summary_cluster_size or 2))
        self.cluster_strategy = str(cluster_strategy or "sequential").strip().lower() or "sequential"
        self.similarity_threshold = max(0.0, float(similarity_threshold or 0.0))
        self._leaf_chunker = SemanticSentenceChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

    def _summarize_cluster(self, cluster: list[Document]) -> str:
        parts: list[str] = []
        for doc in cluster:
            text = str(doc.page_content or "").strip()
            if text:
                parts.append(text)
        merged = " ".join(parts).strip()
        if len(merged) <= self.chunk_size:
            return merged
        return merged[: self.chunk_size].rstrip() + "..."

    def _cluster_leafs(self, leafs: list[Document]) -> list[list[Document]]:
        if self.cluster_strategy == "leiden_proxy":
            groups = build_semantic_leiden_proxy_clusters(
                [str(doc.page_content or "") for doc in leafs],
                similarity_threshold=self.similarity_threshold,
            )
            out = [[leafs[idx] for idx in group] for group in groups if group]
            return out or [leafs]

        out: list[list[Document]] = []
        for start in range(0, len(leafs), self.summary_cluster_size):
            cluster = leafs[start : start + self.summary_cluster_size]
            if cluster:
                out.append(cluster)
        return out

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []
        for doc in documents or []:
            leafs = self._leaf_chunker.split_documents([doc])
            if not leafs:
                continue

            family_key = stable_hash(
                f"raptor:{stable_hash(doc.page_content or '', length=None)}:{stable_hash(str(doc.metadata or {}), length=None)}",
                length=24,
            )
            normalized_leafs: list[Document] = []
            for idx, leaf in enumerate(leafs):
                meta = dict(leaf.metadata or {})
                leaf_id = stable_hash(
                    f"{family_key}:leaf:{idx}:{meta.get('start_char')}:{meta.get('end_char')}:{stable_hash(leaf.page_content or '', length=None)}",
                    length=24,
                )
                meta.update(
                    {
                        "chunk_strategy": "raptor",
                        "chunk_role": "leaf",
                        "hierarchy_basis": "raptor",
                        "hierarchy_level": "leaf",
                        "hierarchy_family_key": family_key,
                        "hierarchy_node_key": leaf_id,
                        "raptor_layer": 0,
                        "raptor_tree_mode": "collapsed",
                    }
                )
                normalized_leafs.append(
                    Document(
                        page_content=leaf.page_content,
                        metadata=meta,
                        id=getattr(leaf, "id", None),
                    )
                )

            summaries: list[Document] = []
            clustered_leafs = self._cluster_leafs(normalized_leafs)
            for start, cluster in enumerate(clustered_leafs):
                if not cluster:
                    continue
                summary_id = stable_hash(
                    f"{family_key}:summary:{start}:{','.join(str((item.metadata or {}).get('hierarchy_node_key') or '') for item in cluster)}",
                    length=24,
                )
                for leaf in cluster:
                    leaf_meta = dict(leaf.metadata or {})
                    leaf_meta["raptor_parent_id"] = summary_id
                    leaf.metadata.clear()
                    leaf.metadata.update(leaf_meta)

                first_meta = dict(cluster[0].metadata or {})
                last_meta = dict(cluster[-1].metadata or {})
                summary_meta = dict(doc.metadata or {})
                summary_meta.update(
                    {
                        "chunk_strategy": "raptor",
                        "chunk_role": "summary",
                        "hierarchy_basis": "raptor",
                        "hierarchy_level": "summary",
                        "hierarchy_family_key": family_key,
                        "hierarchy_node_key": summary_id,
                        "raptor_layer": 1,
                        "raptor_tree_mode": "collapsed",
                        "raptor_cluster_strategy": self.cluster_strategy,
                        "raptor_child_ids": [str((item.metadata or {}).get("hierarchy_node_key") or "") for item in cluster],
                        "start_char": first_meta.get("start_char"),
                        "end_char": last_meta.get("end_char"),
                    }
                )
                summaries.append(Document(page_content=self._summarize_cluster(cluster), metadata=summary_meta))

            apply_sibling_hierarchy_links([d.metadata for d in normalized_leafs if isinstance(d.metadata, dict)], overwrite=True)
            apply_sibling_hierarchy_links([d.metadata for d in summaries if isinstance(d.metadata, dict)], overwrite=True)
            out.extend(normalized_leafs)
            out.extend(summaries)
        return out


__all__ = ["RaptorChunker", "build_semantic_leiden_proxy_clusters"]
