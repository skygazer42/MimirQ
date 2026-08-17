from types import SimpleNamespace

from langchain_core.documents import Document
from llama_index.core.schema import NodeRelationship

from app.rag.chunking.strategies.llama_index import LlamaIndexHierarchicalChunker


class _Node:
    def __init__(
        self,
        node_id: str,
        content: str,
        *,
        start: int,
        end: int,
        parent_id: str | None = None,
        child_ids: list[str] | None = None,
    ) -> None:
        self.node_id = node_id
        self.id_ = node_id
        self.metadata = {"node_meta": node_id}
        self.start_char_idx = start
        self.end_char_idx = end
        self.relationships: dict[NodeRelationship, object] = {}
        if parent_id is not None:
            self.relationships[NodeRelationship.PARENT] = SimpleNamespace(node_id=parent_id)
        if child_ids:
            self.relationships[NodeRelationship.CHILD] = [SimpleNamespace(node_id=child_id) for child_id in child_ids]
        self._content = content

    def get_content(self) -> str:
        return self._content


class _Parser:
    def __init__(self, nodes: list[_Node]) -> None:
        self._nodes = nodes

    def get_nodes_from_documents(self, _documents: list[object]) -> list[_Node]:
        return list(self._nodes)


def test_llama_hierarchical_chunker_preserves_levels_relationships_and_offsets() -> None:
    nodes = [
        _Node("root", "root text", start=0, end=9, child_ids=["child"]),
        _Node(
            "child",
            "child text",
            start=10,
            end=20,
            parent_id="root",
            child_ids=["grand"],
        ),
        _Node("grand", "grand text", start=21, end=31, parent_id="child"),
        _Node("orphan", "orphan text", start=32, end=43, parent_id="external"),
    ]
    chunker = object.__new__(LlamaIndexHierarchicalChunker)
    chunker.chunk_size = 100
    chunker.chunk_overlap = 10
    chunker.parser = _Parser(nodes)

    chunks = chunker.split_documents([Document(page_content="source text", metadata={"source": "fixture"})])

    assert [(chunk.page_content, chunk.metadata) for chunk in chunks] == [
        (
            "root text",
            {
                "source": "fixture",
                "node_meta": "root",
                "node_id": "root",
                "chunk_level": 0,
                "has_children": True,
                "start_char": 0,
                "end_char": 9,
                "chunk_strategy": "llama_index_hierarchical",
            },
        ),
        (
            "child text",
            {
                "source": "fixture",
                "node_meta": "child",
                "node_id": "child",
                "chunk_level": 1,
                "has_children": True,
                "start_char": 10,
                "end_char": 20,
                "chunk_strategy": "llama_index_hierarchical",
                "parent_node_id": "root",
            },
        ),
        (
            "grand text",
            {
                "source": "fixture",
                "node_meta": "grand",
                "node_id": "grand",
                "chunk_level": 2,
                "start_char": 21,
                "end_char": 31,
                "chunk_strategy": "llama_index_hierarchical",
                "parent_node_id": "child",
            },
        ),
        (
            "orphan text",
            {
                "source": "fixture",
                "node_meta": "orphan",
                "node_id": "orphan",
                "chunk_level": 1,
                "start_char": 32,
                "end_char": 43,
                "chunk_strategy": "llama_index_hierarchical",
                "parent_node_id": "external",
            },
        ),
    ]
