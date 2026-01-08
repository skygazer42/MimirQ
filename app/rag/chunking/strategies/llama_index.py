"""
LlamaIndex-based chunking strategies.

提供基于 LlamaIndex 的智能切分策略。
"""
from __future__ import annotations

from typing import List

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker
from app.core.config import settings


class LlamaIndexChunker(BaseChunker):
    """
    LlamaIndex SentenceSplitter-based chunking.
    
    基于句子边界的智能切分，保持语义完整性。
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        if not settings.LLAMA_INDEX_ENABLED:
            raise RuntimeError(
                "LlamaIndexChunker is disabled. Set LLAMA_INDEX_ENABLED=true in your .env file."
            )
        
        try:
            from llama_index.core.node_parser import SentenceSplitter
        except ImportError as e:
            raise RuntimeError(
                "llama-index-core is not installed. "
                "Install it with: pip install llama-index-core"
            ) from e
        
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = SentenceSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        try:
            from llama_index.core import Document as LlamaDocument
        except ImportError as e:
            raise RuntimeError("llama-index-core is required") from e
        
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

    创建多层级切片，具有父子关系。
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        if not settings.LLAMA_INDEX_ENABLED:
            raise RuntimeError(
                "LlamaIndexHierarchicalChunker is disabled. Set LLAMA_INDEX_ENABLED=true in your .env file."
            )
        
        try:
            from llama_index.core.node_parser import HierarchicalNodeParser
        except ImportError as e:
            raise RuntimeError(
                "llama-index-core is not installed. "
                "Install it with: pip install llama-index-core"
            ) from e
        
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Create three-level structure: large chunks, medium chunks, small chunks
        chunk_sizes = [chunk_size * 4, chunk_size * 2, chunk_size]
        
        self.parser = HierarchicalNodeParser.from_defaults(
            chunk_sizes=chunk_sizes,
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        try:
            from llama_index.core import Document as LlamaDocument
            from llama_index.core.schema import NodeRelationship
        except ImportError as e:
            raise RuntimeError("llama-index-core is required") from e
        
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

                # Get hierarchy information
                level = metadata.get("level")
                if level is not None:
                    metadata["chunk_level"] = level

                # Get parent node relationship
                try:
                    parent_rel = getattr(node, "relationships", {}).get(NodeRelationship.PARENT)
                    if parent_rel and getattr(parent_rel, "node_id", None):
                        metadata["parent_node_id"] = parent_rel.node_id
                except Exception:
                    pass
                
                chunks.append(Document(page_content=node.get_content(), metadata=metadata))
        return chunks
