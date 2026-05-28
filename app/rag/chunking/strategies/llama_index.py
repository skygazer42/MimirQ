"""
LlamaIndex-based chunking strategies.

Provides intelligent chunking strategies based on LlamaIndex.
"""


from langchain_core.documents import Document

from app.core.config import settings
from app.rag.chunking.base import BaseChunker
from app.rag.core.logging import get_logger

logger = get_logger(__name__)


def _estimate_tokens_from_chars(chars: int, *, min_tokens: int = 0) -> int:
    # Rough heuristic: 1 token ~= 4 chars for mixed English/Chinese.
    value = int(chars or 0)
    if value <= 0:
        return 0
    return max(int(min_tokens or 0), value // 4)


class LlamaIndexChunker(BaseChunker):
    """
    LlamaIndex SentenceSplitter-based chunking.

    Intelligent chunking based on sentence boundaries, maintaining semantic integrity.
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        if not settings.LLAMA_INDEX_ENABLED:
            raise RuntimeError(
                "LlamaIndexChunker is disabled. Set LLAMA_INDEX_ENABLED=true in your .env file."
            )
        
        from llama_index.core.node_parser import SentenceSplitter

        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        # MimirQ uses character-based chunk_size/chunk_overlap across strategies.
        # LlamaIndex SentenceSplitter interprets these values as tokens, so convert.
        token_chunk_size = _estimate_tokens_from_chars(self.chunk_size, min_tokens=20)
        token_chunk_overlap = _estimate_tokens_from_chars(self.chunk_overlap, min_tokens=0)
        if token_chunk_overlap >= token_chunk_size:
            token_chunk_overlap = max(0, token_chunk_size - 1)

        self.splitter = SentenceSplitter(
            chunk_size=token_chunk_size,
            chunk_overlap=token_chunk_overlap,
            # Avoid metadata consuming the token budget (MimirQ injects metadata separately).
            include_metadata=False,
            include_prev_next_rel=False,
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        from llama_index.core import Document as LlamaDocument
        
        chunks: list[Document] = []
        for doc in documents:
            # LlamaIndex subtracts document metadata from the chunk token budget
            # even when include_metadata=False. MimirQ stores parser/provenance
            # metadata separately on the LangChain document/chunks, so keep the
            # LlamaIndex input metadata empty and merge the original metadata
            # back onto output chunks below.
            li_doc = LlamaDocument(text=doc.page_content, metadata={})
            nodes = self.splitter.get_nodes_from_documents([li_doc])
            for node in nodes:
                metadata = dict(doc.metadata or {})
                metadata.update(node.metadata or {})
                node_id = getattr(node, "node_id", None) or getattr(node, "id_", None)
                if node_id:
                    metadata["node_id"] = str(node_id)
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
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        if not settings.LLAMA_INDEX_ENABLED:
            raise RuntimeError(
                "LlamaIndexHierarchicalChunker is disabled. Set LLAMA_INDEX_ENABLED=true in your .env file."
            )
        
        from llama_index.core.node_parser import HierarchicalNodeParser
        
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        # Create three-level structure: large chunks, medium chunks, small chunks
        base_tokens = _estimate_tokens_from_chars(self.chunk_size, min_tokens=20)
        token_overlap = _estimate_tokens_from_chars(self.chunk_overlap, min_tokens=0)
        if token_overlap >= base_tokens:
            token_overlap = max(0, base_tokens - 1)

        chunk_sizes = [base_tokens * 4, base_tokens * 2, base_tokens]
        
        self.parser = HierarchicalNodeParser.from_defaults(
            chunk_sizes=chunk_sizes,
            chunk_overlap=token_overlap,
            # Avoid metadata consuming the token budget (MimirQ injects metadata separately).
            include_metadata=False,
            include_prev_next_rel=False,
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        from llama_index.core import Document as LlamaDocument
        from llama_index.core.schema import NodeRelationship
        
        chunks: list[Document] = []
        for doc in documents:
            # See LlamaIndexChunker above: keep metadata out of LlamaIndex's
            # splitting budget, then restore MimirQ metadata on emitted chunks.
            li_doc = LlamaDocument(text=doc.page_content, metadata={})
            nodes = self.parser.get_nodes_from_documents([li_doc])

            node_ids: set[str] = set()
            parent_by_id: dict[str, str] = {}
            child_counts: dict[str, int] = {}

            # First pass: record relationships so we can derive a stable level.
            for node in nodes:
                node_id = getattr(node, "node_id", None) or getattr(node, "id_", None)
                if not node_id:
                    continue
                node_id_str = str(node_id)
                node_ids.add(node_id_str)

                rels = getattr(node, "relationships", {}) or {}
                try:
                    parent_rel = rels.get(NodeRelationship.PARENT)
                    parent_id = getattr(parent_rel, "node_id", None) if parent_rel else None
                    if parent_id:
                        parent_by_id[node_id_str] = str(parent_id)
                except Exception as exc:
                    logger.debug("Ignoring non-critical LlamaIndex chunking fallback failure: %s", exc)

                try:
                    children_rel = rels.get(NodeRelationship.CHILD)
                    if children_rel:
                        child_counts[node_id_str] = len(children_rel) if hasattr(children_rel, "__len__") else 1
                except Exception as exc:
                    logger.debug("Ignoring non-critical LlamaIndex chunking fallback failure: %s", exc)

            level_cache: dict[str, int] = {}

            def _get_level(node_id_str: str) -> int:
                cached = level_cache.get(node_id_str)
                if cached is not None:
                    return cached
                parent_id = parent_by_id.get(node_id_str)
                if not parent_id:
                    level_cache[node_id_str] = 0
                    return 0
                if parent_id not in node_ids:
                    level_cache[node_id_str] = 1
                    return 1
                level = _get_level(parent_id) + 1
                level_cache[node_id_str] = level
                return level

            for node in nodes:
                metadata = dict(doc.metadata or {})
                metadata.update(getattr(node, "metadata", {}) or {})

                node_id = getattr(node, "node_id", None) or getattr(node, "id_", None)
                node_id_str = str(node_id) if node_id else None
                if node_id_str:
                    metadata["node_id"] = node_id_str
                    metadata["chunk_level"] = _get_level(node_id_str)
                    if child_counts.get(node_id_str):
                        metadata["has_children"] = True
                start_idx = getattr(node, "start_char_idx", None)
                end_idx = getattr(node, "end_char_idx", None)
                if start_idx is not None:
                    metadata["start_char"] = int(start_idx)
                if end_idx is not None:
                    metadata["end_char"] = int(end_idx)
                metadata["chunk_strategy"] = "llama_index_hierarchical"

                # Get parent node relationship
                try:
                    parent_rel = getattr(node, "relationships", {}).get(NodeRelationship.PARENT)
                    if parent_rel and getattr(parent_rel, "node_id", None):
                        metadata["parent_node_id"] = parent_rel.node_id
                except Exception as exc:
                    logger.debug("Ignoring non-critical LlamaIndex chunking fallback failure: %s", exc)
                
                chunks.append(Document(page_content=node.get_content(), metadata=metadata))
        return chunks
