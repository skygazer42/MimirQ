"""
Chunker factory supporting multiple text splitting strategies.
"""
from __future__ import annotations

from typing import List, Optional
import re

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter, TokenTextSplitter
from llama_index.core.node_parser import HierarchicalNodeParser
from llama_index.core.schema import NodeRelationship

from app.config import settings


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


class LangChainTokenChunker(BaseChunker):
    """基于 LangChain TokenTextSplitter 的切片器，按 token 数量切分。"""

    def __init__(self, chunk_size: int, chunk_overlap: int, encoding_name: str = "cl100k_base"):
        """
        初始化 Token 切片器。

        Args:
            chunk_size: 每个块的最大 token 数量
            chunk_overlap: 块之间重叠的 token 数量
            encoding_name: tiktoken 编码名称，默认 cl100k_base (GPT-4/ChatGPT)
        """
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

            # 计算每个块的起止位置
            current_pos = 0
            for split_text in split_texts:
                # 查找文本在原文中的位置
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

                # 更新搜索位置，考虑重叠
                current_pos = max(start_idx + 1, end_idx - len(split_text) // 2)

        return chunks


class LlamaIndexChunker(BaseChunker):
    """基于 LlamaIndex SentenceSplitter 的切片器。"""

    def __init__(self, chunk_size: int, chunk_overlap: int):
        from llama_index.core.node_parser import SentenceSplitter

        self.splitter = SentenceSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

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
    """
    轻量“语义”切块：先按句子边界切，再按长度聚合，尽量不打断句子。
    不依赖额外模型，适合无法安装 SemanticChunker 依赖的环境。
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = max(chunk_size, 1)
        self.chunk_overlap = max(chunk_overlap, 0)

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []
        for doc in documents:
            text = doc.page_content
            # 句子粗分，兼容中英文标点与换行
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
                # 重叠：保留尾部 overlap 作为下个块的起点
                if self.chunk_overlap > 0 and len(buffer_text) > self.chunk_overlap:
                    overlap_text = buffer_text[-self.chunk_overlap :]
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
                # 如果加上当前句子超长，先输出现有块
                if len(buffer_text) + len(sentence) > self.chunk_size and buffer_text:
                    flush_chunk(last_end)
                buffer_text += sentence
                last_end = end_idx

            # 收尾
            if buffer_text:
                flush_chunk(last_end)

        return chunks


class LlamaIndexHierarchicalChunker(BaseChunker):
    """LlamaIndex HierarchicalNodeParser，生成父子块并保留层级信息。"""

    def __init__(self, chunk_size: int, chunk_overlap: int):
        # 构造多级 chunk_sizes：顶层使用传入值，向下按 1/2、1/4 递减
        base = max(chunk_size, 1)
        self.chunk_sizes = [
            base,
            max(base // 2, 1),
            max(base // 4, 1),
        ]
        self.chunk_overlap = max(chunk_overlap, 0)
        try:
            self.parser = HierarchicalNodeParser.from_defaults(
                chunk_sizes=self.chunk_sizes,
                chunk_overlap=self.chunk_overlap,
            )
        except TypeError:
            # 旧版本 HierarchicalNodeParser 不支持 chunk_overlap 参数
            self.parser = HierarchicalNodeParser.from_defaults(
                chunk_sizes=self.chunk_sizes,
            )

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
                # 保留层级与父节点信息，便于前端标注/后端检索调试
                level = metadata.get("level")
                if level is not None:
                    metadata["chunk_level"] = level

                try:
                    parent_rel = getattr(node, "relationships", {}).get(NodeRelationship.PARENT)
                    if parent_rel and getattr(parent_rel, "node_id", None):
                        metadata["parent_node_id"] = parent_rel.node_id
                except Exception:
                    # relationships 结构变化时忽略，不阻断流程
                    pass

                chunks.append(Document(page_content=node.get_content(), metadata=metadata))

        return chunks


class ChunkerFactory:
    """负责解析策略并返回对应 chunker。"""

    SUPPORTED_STRATEGIES = {
        "langchain_recursive": LangChainRecursiveChunker,
        "langchain_token": LangChainTokenChunker,
        "semantic_sentence": SemanticSentenceChunker,
        "llama_index": LlamaIndexChunker,
        "llama_index_hierarchical": LlamaIndexHierarchicalChunker,
    }

    # ragflow 预设（在 document_processor 中直连，不在此处真正分片）
    RAGFLOW_STRATEGIES = {"ragflow_naive", "ragflow_book", "ragflow_laws", "ragflow_email"}

    def resolve_strategy(self, strategy: Optional[str]) -> str:
        normalized = (strategy or settings.DEFAULT_CHUNK_STRATEGY).lower()
        if normalized == "auto":
            normalized = settings.DEFAULT_CHUNK_STRATEGY

        if normalized in self.RAGFLOW_STRATEGIES:
            return normalized  # 让上层识别后走 ragflow 分支

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
            # ragflow 分支在 document_processor 里直接处理，不应走到这里
            raise ValueError(f"Chunk strategy '{resolved}' is handled by ragflow pipeline and has no chunker.")
        chunker_cls = self.SUPPORTED_STRATEGIES[resolved]
        return chunker_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)


chunker_factory = ChunkerFactory()
