"""
Chunker factory supporting multiple text splitting strategies.
"""
from __future__ import annotations

from typing import List, Optional
import re
import uuid

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter, TokenTextSplitter
from llama_index.core.node_parser import HierarchicalNodeParser
from llama_index.core.schema import NodeRelationship

from app.core.config import settings


class BaseChunker:
    """Chunker interface."""

    def split_documents(self, documents: List[Document]) -> List[Document]:
        raise NotImplementedError


class LangChainRecursiveChunker(BaseChunker):
    """RecursiveCharacterTextSplitter 包装，保留起止位置。"""

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
            length_function=len,
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []
        for doc in documents:
            docs = self.splitter.create_documents(
                texts=[doc.page_content],
                metadatas=[dict(doc.metadata)]
            )
            offset = 0
            for chunk in docs:
                start_index = chunk.metadata.pop("start_index", None)
                metadata = dict(doc.metadata)
                metadata.update(chunk.metadata or {})
                if start_index is not None:
                    metadata["start_char"] = start_index
                    metadata["end_char"] = start_index + len(chunk.page_content)
                metadata["chunk_strategy"] = "langchain_recursive"
                chunks.append(Document(page_content=chunk.page_content, metadata=metadata))
                offset += len(chunk.page_content)
        return chunks


class ParentChildChunker(BaseChunker):
    """
    二层 parent-child 切块：先较大的父块，再小块的子片。
    保留 parent_id 关联以便成组显示、搜索重排。
    """

    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: int,
        child_ratio: float = 0.5,
        min_child_size: int = 200,
    ):
        # 父片使用传入的大小，同 recursive 策略
        self.parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
            length_function=len,
        )

        # 优先相对比例计算子片大小，最低 min_child_size
        child_size = max(int(chunk_size * child_ratio), min_child_size)
        child_overlap = min(int(chunk_overlap * child_ratio), max(child_size // 4, 0))

        self.child_size = child_size
        self.child_overlap = child_overlap
        self.child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_size,
            chunk_overlap=child_overlap,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
            length_function=len,
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []

        for doc in documents:
            text = doc.page_content
            if not text.strip():
                continue

            parent_texts = self.parent_splitter.split_text(text)
            search_start = 0

            for parent_text in parent_texts:
                if not parent_text.strip():
                    continue

                parent_start = text.find(parent_text, search_start)
                if parent_start == -1:
                    parent_start = search_start
                parent_end = parent_start + len(parent_text)
                # 带重叠时，下一个最低从父片结束后开始
                search_start = max(parent_end - self.child_overlap, parent_start + 1)

                parent_id = str(uuid.uuid4())
                parent_metadata = dict(doc.metadata or {})
                parent_metadata.update(
                    {
                        "start_char": parent_start,
                        "end_char": parent_end,
                        "chunk_strategy": "parent_child",
                        "chunk_role": "parent",
                        "parent_id": parent_id,
                        "child_chunk_size": self.child_size,
                        "child_chunk_overlap": self.child_overlap,
                    }
                )
                chunks.append(Document(page_content=parent_text, metadata=parent_metadata))

                # 子片：同一份文本内再分片
                child_texts = self.child_splitter.split_text(parent_text)
                child_search_start = 0

                for child_text in child_texts:
                    if not child_text.strip():
                        continue

                    child_rel_start = parent_text.find(child_text, child_search_start)
                    if child_rel_start == -1:
                        child_rel_start = child_search_start
                    child_rel_end = child_rel_start + len(child_text)
                    child_search_start = max(child_rel_end - self.child_overlap, child_rel_start + 1)

                    child_start = parent_start + child_rel_start
                    child_end = parent_start + child_rel_end

                    child_metadata = dict(doc.metadata or {})
                    child_metadata.update(
                        {
                            "start_char": child_start,
                            "end_char": child_end,
                            "chunk_strategy": "parent_child",
                            "chunk_role": "child",
                            "parent_id": parent_id,
                            "parent_start_char": parent_start,
                            "parent_end_char": parent_end,
                        }
                    )
                    chunks.append(Document(page_content=child_text, metadata=child_metadata))

        return chunks


class LangChainTokenChunker(BaseChunker):
    """基于 LangChain TokenTextSplitter 的切片器，按 token 数量切分。"""

    def __init__(self, chunk_size: int, chunk_overlap: int, encoding_name: str = "cl100k_base"):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.encoding_name = encoding_name
        self.splitter = TokenTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            encoding_name=encoding_name,
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []
        for doc in documents:
            text = doc.page_content
            split_texts = self.splitter.split_text(text)
            current_pos = 0
            for split_text in split_texts:
                start_idx = text.find(split_text, current_pos)
                if start_idx == -1:
                    start_idx = current_pos
                end_idx = start_idx + len(split_text)
                metadata = dict(doc.metadata or {})
                metadata["start_char"] = start_idx
                metadata["end_char"] = end_idx
                metadata["chunk_strategy"] = "langchain_token"
                metadata["encoding_name"] = self.encoding_name
                chunks.append(Document(page_content=split_text, metadata=metadata))
                current_pos = max(start_idx + 1, end_idx - len(split_text) // 2)
        return chunks


class LlamaIndexChunker(BaseChunker):
    """基于 LlamaIndex SentenceSplitter 的切片器。"""

    def __init__(self, chunk_size: int, chunk_overlap: int):
        from llama_index.core.node_parser import SentenceSplitter
        self.splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def split_documents(self, documents: List[Document]) -> List[Document]:
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


class SemanticSentenceChunker(BaseChunker):
    """轻量语义切块：先按句子边界切，再按长度聚合。"""

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = max(chunk_size, 1)
        self.chunk_overlap = max(chunk_overlap, 0)

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []
        for doc in documents:
            text = doc.page_content
            sentence_matches = list(re.finditer(r"[^。！？.!?\n]+[。！？.!?\n]?", text, flags=re.S))
            buffer_text = ""
            buffer_start = 0
            last_end = 0

            def flush_chunk(end_idx: int):
                nonlocal buffer_text, buffer_start, last_end
                if not buffer_text:
                    return
                metadata = dict(doc.metadata or {})
                metadata["start_char"] = buffer_start
                metadata["end_char"] = end_idx
                metadata["chunk_strategy"] = "semantic_sentence"
                chunks.append(Document(page_content=buffer_text, metadata=metadata))
                if self.chunk_overlap > 0 and len(buffer_text) > self.chunk_overlap:
                    overlap_text = buffer_text[-self.chunk_overlap:]
                    buffer_text = overlap_text
                    buffer_start = end_idx - len(overlap_text)
                else:
                    buffer_text = ""
                    buffer_start = end_idx
                last_end = end_idx

            for m in sentence_matches:
                sentence = m.group()
                start_idx, end_idx = m.start(), m.end()
                if not buffer_text:
                    buffer_start = start_idx
                if len(buffer_text) + len(sentence) > self.chunk_size and buffer_text:
                    flush_chunk(last_end)
                buffer_text += sentence
                last_end = end_idx
            if buffer_text:
                flush_chunk(last_end)
        return chunks


class SeparatorChunker(BaseChunker):
    """自定义分隔符切块器（类似 Dify）。"""

    PRESET_SEPARATORS = {
        "paragraph": "\n\n",
        "line": "\n",
        "sentence_cn": "。",
        "sentence_en": ".",
        "markdown_hr": "---",
        "markdown_h1": "# ",
        "markdown_h2": "## ",
        "custom": None,
    }

    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: int,
        separator: str = "\n\n",
        keep_separator: bool = True,
        max_chunk_size: int = 0,
    ):
        self.chunk_size = chunk_size
        self.separator = separator
        self.keep_separator = keep_separator
        self.max_chunk_size = max_chunk_size if max_chunk_size > 0 else chunk_size * 3

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []
        for doc in documents:
            text = doc.page_content
            if not text.strip():
                continue
            if self.keep_separator:
                parts = re.split(f"({re.escape(self.separator)})", text)
                merged_parts = []
                for i, part in enumerate(parts):
                    if i % 2 == 0:
                        merged_parts.append(part)
                    else:
                        if merged_parts:
                            merged_parts[-1] += part
                        else:
                            merged_parts.append(part)
                parts = merged_parts
            else:
                parts = text.split(self.separator)
            current_pos = 0
            for part in parts:
                if not part.strip():
                    current_pos += len(part) + (0 if self.keep_separator else len(self.separator))
                    continue
                if len(part) > self.max_chunk_size:
                    sub_chunks = self._split_large_chunk(part, current_pos, doc.metadata)
                    chunks.extend(sub_chunks)
                else:
                    metadata = dict(doc.metadata or {})
                    start_idx = text.find(part, current_pos)
                    if start_idx == -1:
                        start_idx = current_pos
                    end_idx = start_idx + len(part)
                    metadata["start_char"] = start_idx
                    metadata["end_char"] = end_idx
                    metadata["chunk_strategy"] = "separator"
                    metadata["separator"] = repr(self.separator)
                    chunks.append(Document(page_content=part.strip(), metadata=metadata))
                current_pos += len(part) + (0 if self.keep_separator else len(self.separator))
        return chunks

    def _split_large_chunk(self, text: str, base_pos: int, base_metadata: dict) -> List[Document]:
        chunks = []
        pos = 0
        while pos < len(text):
            end = min(pos + self.max_chunk_size, len(text))
            if end < len(text):
                for sep in ["。", ".", "！", "!", "？", "?", "\n", " "]:
                    last_sep = text.rfind(sep, pos, end)
                    if last_sep > pos:
                        end = last_sep + 1
                        break
            chunk_text = text[pos:end].strip()
            if chunk_text:
                metadata = dict(base_metadata or {})
                metadata["start_char"] = base_pos + pos
                metadata["end_char"] = base_pos + end
                metadata["chunk_strategy"] = "separator"
                metadata["separator"] = repr(self.separator)
                metadata["is_sub_chunk"] = True
                chunks.append(Document(page_content=chunk_text, metadata=metadata))
            pos = end
        return chunks


class LlamaIndexHierarchicalChunker(BaseChunker):
    """LlamaIndex HierarchicalNodeParser，生成父子块并保留层级信息。"""

    def __init__(self, chunk_size: int, chunk_overlap: int):
        base = max(chunk_size, 1)
        self.chunk_sizes = [base, max(base // 2, 1), max(base // 4, 1)]
        self.chunk_overlap = max(chunk_overlap, 0)
        try:
            self.parser = HierarchicalNodeParser.from_defaults(
                chunk_sizes=self.chunk_sizes, chunk_overlap=self.chunk_overlap
            )
        except TypeError:
            self.parser = HierarchicalNodeParser.from_defaults(chunk_sizes=self.chunk_sizes)

    def split_documents(self, documents: List[Document]) -> List[Document]:
        from llama_index.core import Document as LlamaDocument
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


class ChunkerFactory:
    """负责解析策略并返回对应 chunker。"""

    SUPPORTED_STRATEGIES = {
        "langchain_recursive": LangChainRecursiveChunker,
        "langchain_token": LangChainTokenChunker,
        "semantic_sentence": SemanticSentenceChunker,
        "separator": SeparatorChunker,
        "llama_index": LlamaIndexChunker,
        "llama_index_hierarchical": LlamaIndexHierarchicalChunker,
        "parent_child": ParentChildChunker,
    }

    RAGFLOW_STRATEGIES = {"ragflow_naive", "ragflow_book", "ragflow_laws", "ragflow_email"}

    def resolve_strategy(self, strategy: Optional[str]) -> str:
        normalized = (strategy or settings.DEFAULT_CHUNK_STRATEGY).lower()
        if normalized == "auto":
            normalized = settings.DEFAULT_CHUNK_STRATEGY
        if normalized in self.RAGFLOW_STRATEGIES:
            return normalized
        if normalized not in self.SUPPORTED_STRATEGIES:
            raise ValueError(
                f"Unsupported chunk strategy '{strategy}'. "
                f"Supported strategies: {sorted(self.SUPPORTED_STRATEGIES)} + {sorted(self.RAGFLOW_STRATEGIES)}"
            )
        if normalized.startswith("llama_index") and not settings.LLAMA_INDEX_ENABLED:
            raise ValueError("LlamaIndex chunker is disabled. Set LLAMA_INDEX_ENABLED=True to use it.")
        return normalized

    def get_chunker(self, strategy: Optional[str], chunk_size: int, chunk_overlap: int) -> BaseChunker:
        resolved = self.resolve_strategy(strategy)
        if resolved in self.RAGFLOW_STRATEGIES:
            raise ValueError(f"Chunk strategy '{resolved}' is handled by ragflow pipeline and has no chunker.")
        chunker_cls = self.SUPPORTED_STRATEGIES[resolved]
        return chunker_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)


chunker_factory = ChunkerFactory()
