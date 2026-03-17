"""
Parent-Child chunking strategy.

Creates a two-level hierarchy:
- Parent chunks: Larger segments for context
- Child chunks: Smaller segments for precise retrieval

Child chunks maintain reference to parent via parent_id.
"""


from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.utils.hierarchical import apply_sibling_hierarchy_links
from app.rag.core.hashing import stable_hash


class ParentChildChunker(BaseChunker):
    """
    Two-level parent-child chunking strategy.

    Parent chunks use the specified chunk_size.
    Child chunks are derived from parents using child_ratio.
    """

    DEFAULT_SEPARATORS = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]

    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: int,
        child_ratio: float = 0.5,
        min_child_size: int = 200,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.child_ratio = child_ratio
        self.min_child_size = min_child_size

        # Parent splitter uses the full chunk size
        self.parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=self.DEFAULT_SEPARATORS,
            length_function=len,
        )

        # Child size is proportional to parent, with minimum threshold
        child_size = max(int(chunk_size * child_ratio), min_child_size)
        child_overlap = min(int(chunk_overlap * child_ratio), max(child_size // 4, 0))

        self.child_size = child_size
        self.child_overlap = child_overlap
        self.child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_size,
            chunk_overlap=child_overlap,
            separators=self.DEFAULT_SEPARATORS,
            length_function=len,
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        chunks: list[Document] = []
        parent_docs: list[Document] = []
        child_docs_by_parent: dict[str, list[Document]] = {}

        for doc in documents:
            text = doc.page_content
            if not text.strip():
                continue

            parent_texts = self.parent_splitter.split_text(text)
            search_start = 0

            for parent_text in parent_texts:
                if not parent_text.strip():
                    continue

                # Find parent position in original text
                parent_start = text.find(parent_text, search_start)
                if parent_start == -1:
                    parent_start = search_start
                parent_end = parent_start + len(parent_text)
                search_start = max(parent_end - self.child_overlap, parent_start + 1)

                # Deterministic parent ids:
                # - Parent-child chunking should be stable across runs for regression suites,
                #   caching, and trace diffs.
                # - Include both position and content hash to avoid collisions when text repeats.
                parent_id = stable_hash(
                    f"pc:{parent_start}:{parent_end}:{stable_hash(parent_text, length=None)}",
                    length=32,
                )
                parent_metadata = dict(doc.metadata or {})
                parent_metadata.update({
                    "start_char": parent_start,
                    "end_char": parent_end,
                    "chunk_strategy": "parent_child",
                    "chunk_role": "parent",
                    "parent_id": parent_id,
                    "hierarchy_basis": "parent_child",
                    "hierarchy_level": "parent",
                    "hierarchy_node_key": parent_id,
                    "hierarchy_family_key": parent_id,
                    "hierarchy_parent_key": None,
                    "child_chunk_size": self.child_size,
                    "child_chunk_overlap": self.child_overlap,
                })
                parent_doc = Document(page_content=parent_text, metadata=parent_metadata)
                chunks.append(parent_doc)
                parent_docs.append(parent_doc)

                # Split parent into child chunks
                child_texts = self.child_splitter.split_text(parent_text)
                child_search_start = 0
                parent_child_docs: list[Document] = []

                for child_text in child_texts:
                    if not child_text.strip():
                        continue

                    # Find child position relative to parent
                    child_rel_start = parent_text.find(child_text, child_search_start)
                    if child_rel_start == -1:
                        child_rel_start = child_search_start
                    child_rel_end = child_rel_start + len(child_text)
                    child_search_start = max(child_rel_end - self.child_overlap, child_rel_start + 1)

                    # Convert to absolute positions
                    child_start = parent_start + child_rel_start
                    child_end = parent_start + child_rel_end

                    child_metadata = dict(doc.metadata or {})
                    child_node_key = stable_hash(
                        f"pc-child:{parent_id}:{child_start}:{child_end}:{stable_hash(child_text, length=None)}",
                        length=32,
                    )
                    child_metadata.update({
                        "start_char": child_start,
                        "end_char": child_end,
                        "chunk_strategy": "parent_child",
                        "chunk_role": "child",
                        "parent_id": parent_id,
                        "hierarchy_basis": "parent_child",
                        "hierarchy_level": "child",
                        "hierarchy_node_key": child_node_key,
                        "hierarchy_parent_key": parent_id,
                        "hierarchy_family_key": parent_id,
                        "parent_start_char": parent_start,
                        "parent_end_char": parent_end,
                    })
                    child_doc = Document(page_content=child_text, metadata=child_metadata)
                    chunks.append(child_doc)
                    parent_child_docs.append(child_doc)

                child_docs_by_parent[parent_id] = parent_child_docs

        apply_sibling_hierarchy_links(
            [d.metadata for d in parent_docs if isinstance(getattr(d, "metadata", None), dict)],
            overwrite=True,
        )
        for siblings in child_docs_by_parent.values():
            apply_sibling_hierarchy_links(
                [d.metadata for d in siblings if isinstance(getattr(d, "metadata", None), dict)],
                overwrite=True,
            )

        return chunks
