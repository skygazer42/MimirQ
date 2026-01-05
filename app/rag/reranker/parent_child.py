"""
Parent-Child Reranker

对检索结果进行父子关系分组重排，每个父节点只保留最佳的子节点。
"""
from __future__ import annotations

from app.models.chunk import Document
from app.rag.reranker.base import DocumentReranker


class ParentChildReranker(DocumentReranker):
    """父子关系重排器：按 parent_id 分组，保留每组中得分最高的子节点"""

    def run(
        self,
        query: str,
        documents: list[Document],
        score_threshold: float | None = None,
        top_n: int | None = None,
        user: str | None = None,
    ) -> list[Document]:
        """
        运行父子关系重排
        
        根据 metadata 中的 parent_id/parent_node_id 分组，
        每组中选择得分最高的子节点作为代表。
        """
        if not documents:
            return []

        groups: dict[str, list[Document]] = {}
        scores: dict[int, float] = {}
        
        for doc in documents:
            meta = doc.metadata or {}
            score = float(meta.get("score", 0.0) or 0.0)
            scores[id(doc)] = score
            
            # 确定分组 ID
            group_id = meta.get("parent_id") or meta.get("parent_node_id")
            if not group_id:
                doc_id = meta.get("document_id")
                chunk_index = meta.get("chunk_index")
                if doc_id is not None and chunk_index is not None:
                    group_id = f"{doc_id}:{chunk_index}"
                else:
                    group_id = f"self:{id(doc)}"
            groups.setdefault(str(group_id), []).append(doc)

        # 每组选择最佳代表
        ranked: list[tuple[Document, float]] = []
        for _, items in groups.items():
            children = [d for d in items if (d.metadata or {}).get("chunk_role") == "child"]
            if children:
                rep = max(children, key=lambda d: scores.get(id(d), 0.0))
            else:
                rep = max(items, key=lambda d: scores.get(id(d), 0.0))
            ranked.append((rep, scores.get(id(rep), 0.0)))

        # 按分数降序排序
        ranked.sort(key=lambda x: x[1], reverse=True)

        # 应用阈值和 top_n
        output: list[Document] = []
        for doc, score in ranked:
            if score_threshold is not None and score < score_threshold:
                continue
            output.append(doc)
            if top_n and len(output) >= top_n:
                break

        return output


