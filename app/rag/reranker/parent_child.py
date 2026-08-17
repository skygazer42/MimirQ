"""
Parent-child reranker.

Groups results by parent/child relationships and keeps the best child per parent.
"""

from app.models.chunk import Document
from app.rag.reranker.base import DocumentReranker


class ParentChildReranker(DocumentReranker):
    """Parent-child reranker: group by parent_id and keep the top child per group."""

    def run(
        self,
        query: str,
        documents: list[Document],
        score_threshold: float | None = None,
        top_n: int | None = None,
        user: str | None = None,
    ) -> list[Document]:
        """
        Run parent-child reranking.

        Group by parent_id/parent_node_id in metadata and select the highest-scoring
        child as the representative for each group.
        """
        if not documents:
            return []

        groups: dict[str, list[Document]] = {}
        scores: dict[int, float] = {}

        for doc in documents:
            meta = doc.metadata or {}
            score = float(meta.get("score", 0.0) or 0.0)
            scores[id(doc)] = score

            # Determine the group ID.
            group_id = meta.get("parent_id") or meta.get("parent_node_id")
            if not group_id:
                doc_id = meta.get("document_id")
                chunk_index = meta.get("chunk_index")
                if doc_id is not None and chunk_index is not None:
                    group_id = f"{doc_id}:{chunk_index}"
                else:
                    group_id = f"self:{id(doc)}"
            groups.setdefault(str(group_id), []).append(doc)

        # Pick the best representative per group.
        ranked: list[tuple[Document, float]] = []
        for items in groups.values():
            children = [d for d in items if (d.metadata or {}).get("chunk_role") == "child"]
            if children:
                rep = max(children, key=lambda d: scores.get(id(d), 0.0))
            else:
                rep = max(items, key=lambda d: scores.get(id(d), 0.0))
            ranked.append((rep, scores.get(id(rep), 0.0)))

        # Sort by score descending.
        ranked.sort(key=lambda x: x[1], reverse=True)

        # Apply threshold and top_n.
        output: list[Document] = []
        for doc, score in ranked:
            if score_threshold is not None and score < score_threshold:
                continue
            output.append(doc)
            if top_n and len(output) >= top_n:
                break

        return output
