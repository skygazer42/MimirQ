"""
LlamaIndex-based chunking strategies.

Provides intelligent chunking strategies based on LlamaIndex.
"""

from collections.abc import Callable
from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.chunking.base import BaseChunker
from app.rag.core.logging import get_logger

logger = get_logger(__name__)
_LLAMA_INDEX_CHUNKING_FALLBACK_LOG_MESSAGE = "Ignoring non-critical LlamaIndex chunking fallback failure: %s"


def _estimate_tokens_from_chars(chars: int, *, min_tokens: int = 0) -> int:
    # Rough heuristic: 1 token ~= 4 chars for mixed English/Chinese.
    value = int(chars or 0)
    if value <= 0:
        return 0
    return max(int(min_tokens or 0), value // 4)


def _node_id(node: Any) -> str | None:
    value = getattr(node, "node_id", None) or getattr(node, "id_", None)
    return str(value) if value else None


def _relationship_node_id(node: Any, relationship_key: Any) -> Any | None:
    try:
        relationship = (getattr(node, "relationships", {}) or {}).get(relationship_key)
        return getattr(relationship, "node_id", None) if relationship else None
    except Exception as exc:
        logger.debug(_LLAMA_INDEX_CHUNKING_FALLBACK_LOG_MESSAGE, exc)
        return None


def _relationship_child_count(node: Any, relationship_key: Any) -> int:
    try:
        relationship = (getattr(node, "relationships", {}) or {}).get(relationship_key)
        if not relationship:
            return 0
        return len(relationship) if hasattr(relationship, "__len__") else 1
    except Exception as exc:
        logger.debug(_LLAMA_INDEX_CHUNKING_FALLBACK_LOG_MESSAGE, exc)
        return 0


def _collect_hierarchy_relationships(
    nodes: list[Any],
    *,
    parent_key: Any,
    child_key: Any,
) -> tuple[set[str], dict[str, str], dict[str, int]]:
    node_ids: set[str] = set()
    parent_by_id: dict[str, str] = {}
    child_counts: dict[str, int] = {}
    for node in nodes:
        node_id = _node_id(node)
        if node_id is None:
            continue
        node_ids.add(node_id)
        parent_id = _relationship_node_id(node, parent_key)
        if parent_id:
            parent_by_id[node_id] = str(parent_id)
        child_count = _relationship_child_count(node, child_key)
        if child_count:
            child_counts[node_id] = child_count
    return node_ids, parent_by_id, child_counts


def _build_level_resolver(
    *,
    node_ids: set[str],
    parent_by_id: dict[str, str],
) -> Callable[[str], int]:
    level_cache: dict[str, int] = {}

    def resolve(node_id: str) -> int:
        cached = level_cache.get(node_id)
        if cached is not None:
            return cached
        parent_id = parent_by_id.get(node_id)
        if not parent_id:
            level_cache[node_id] = 0
        elif parent_id not in node_ids:
            level_cache[node_id] = 1
        else:
            level_cache[node_id] = resolve(parent_id) + 1
        return level_cache[node_id]

    return resolve


def _hierarchical_node_metadata(
    node: Any,
    *,
    base_metadata: dict[str, Any],
    child_counts: dict[str, int],
    resolve_level: Callable[[str], int],
    parent_key: Any,
) -> dict[str, Any]:
    metadata = dict(base_metadata)
    metadata.update(getattr(node, "metadata", {}) or {})
    node_id = _node_id(node)
    if node_id is not None:
        metadata["node_id"] = node_id
        metadata["chunk_level"] = resolve_level(node_id)
        if child_counts.get(node_id):
            metadata["has_children"] = True
    start = getattr(node, "start_char_idx", None)
    end = getattr(node, "end_char_idx", None)
    if start is not None:
        metadata["start_char"] = int(start)
    if end is not None:
        metadata["end_char"] = int(end)
    metadata["chunk_strategy"] = "llama_index_hierarchical"
    parent_id = _relationship_node_id(node, parent_key)
    if parent_id:
        metadata["parent_node_id"] = parent_id
    return metadata


class LlamaIndexChunker(BaseChunker):
    """
    LlamaIndex SentenceSplitter-based chunking.

    Intelligent chunking based on sentence boundaries, maintaining semantic integrity.
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        if not settings.LLAMA_INDEX_ENABLED:
            raise RuntimeError("LlamaIndexChunker is disabled. Set LLAMA_INDEX_ENABLED=true in your .env file.")

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
            li_doc = LlamaDocument(text=doc.page_content, metadata={})
            nodes = self.parser.get_nodes_from_documents([li_doc])
            node_ids, parent_by_id, child_counts = _collect_hierarchy_relationships(
                nodes,
                parent_key=NodeRelationship.PARENT,
                child_key=NodeRelationship.CHILD,
            )
            resolve_level = _build_level_resolver(
                node_ids=node_ids,
                parent_by_id=parent_by_id,
            )
            for node in nodes:
                chunks.append(
                    Document(
                        page_content=node.get_content(),
                        metadata=_hierarchical_node_metadata(
                            node,
                            base_metadata=dict(doc.metadata or {}),
                            child_counts=child_counts,
                            resolve_level=resolve_level,
                            parent_key=NodeRelationship.PARENT,
                        ),
                    )
                )
        return chunks
