"""
LlamaIndex-based chunking strategies.

NOTE: These are currently DISABLED due to llama-index-core
dependency compilation issues with Python 3.11.
"""
from __future__ import annotations

from typing import List

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker


class LlamaIndexChunker(BaseChunker):
    """
    LlamaIndex SentenceSplitter-based chunking.

    DISABLED: Requires llama-index-core which has compilation issues.
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        raise RuntimeError(
            "LlamaIndexChunker is disabled due to llama-index-core dependency issues. "
            "Use 'langchain_recursive' or 'semantic_sentence' as alternatives."
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        # Implementation kept for reference when dependencies are resolved
        from llama_index.core import Document as LlamaDocument

        chunks: List[Document] = []
        for doc in documents:
            li_doc = LlamaDocument(text=doc.page_content, metadata=dict(doc.metadata or {}))
            nodes = self.splitter.get_nodes_from_documents([li_doc])
            for node in nodes:
                metadata = dict(doc.metadata or {})
                metadata.update(node.metadata or {})
                start_idx = getattr(node, "start_char_idx", None)
                end_idx = getattr(node, "end_char_idx", None)
                if start_idx is not None:
                    metadata["start_char"] = int(start_idx)
                if end_idx is not None:
                    metadata["end_char"] = int(end_idx)
                metadata["chunk_strategy"] = "llama_index"
                chunks.append(Document(page_content=node.get_content(), metadata=metadata))
        return chunks


class LlamaIndexHierarchicalChunker(BaseChunker):
    """
    LlamaIndex HierarchicalNodeParser-based chunking.

    Creates multi-level chunks with parent-child relationships.

    DISABLED: Requires llama-index-core which has compilation issues.
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        raise RuntimeError(
            "LlamaIndexHierarchicalChunker is disabled due to llama-index-core dependency issues. "
            "Use 'parent_child' strategy as an alternative."
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        # Implementation kept for reference
        from llama_index.core import Document as LlamaDocument
        from llama_index.core.schema import NodeRelationship

        chunks: List[Document] = []
        for doc in documents:
            li_doc = LlamaDocument(text=doc.page_content, metadata=dict(doc.metadata or {}))
            nodes = self.parser.get_nodes_from_documents([li_doc])
            for node in nodes:
                metadata = dict(doc.metadata or {})
                metadata.update(getattr(node, "metadata", {}) or {})
                start_idx = getattr(node, "start_char_idx", None)
                end_idx = getattr(node, "end_char_idx", None)
                if start_idx is not None:
                    metadata["start_char"] = int(start_idx)
                if end_idx is not None:
                    metadata["end_char"] = int(end_idx)
                metadata["chunk_strategy"] = "llama_index_hierarchical"
                level = metadata.get("level")
                if level is not None:
                    metadata["chunk_level"] = level
                try:
                    parent_rel = getattr(node, "relationships", {}).get(NodeRelationship.PARENT)
                    if parent_rel and getattr(parent_rel, "node_id", None):
                        metadata["parent_node_id"] = parent_rel.node_id
                except Exception:
                    pass
                chunks.append(Document(page_content=node.get_content(), metadata=metadata))
        return chunks
