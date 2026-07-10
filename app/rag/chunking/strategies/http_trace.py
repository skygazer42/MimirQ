"""
HTTP trace / request-response log aware chunking strategy.

Targets HTTP request/response transcripts such as curl -v output or raw
HTTP dumps. The chunker splits by request blocks and preserves offsets.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _RequestBlock:
    start: int
    end: int
    index: int
    method: str
    path: str


_REQ_RE = re.compile(
    r"(?m)^(?:>\s*)?(?P<method>GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\s+(?P<path>\S{1,300})\s+HTTP/(?P<ver>\d(?:\.\d)?)\s*$",
    re.IGNORECASE,
)
_RESP_RE = re.compile(r"(?m)^(?:<\s*)?HTTP/(?P<ver>\d(?:\.\d)?)\s+(?P<status>\d{3})\b.*$")


def _build_request_blocks(text: str) -> list[_RequestBlock]:
    matches = list(_REQ_RE.finditer(text or ""))
    if not matches:
        return []
    blocks: list[_RequestBlock] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        method = (m.group("method") or "").upper()
        path = (m.group("path") or "").strip()
        blocks.append(_RequestBlock(start=start, end=end, index=int(idx), method=method, path=path))
    return blocks


def _extract_status(block_text: str) -> int | None:
    m = _RESP_RE.search((block_text or "")[:20000])
    if not m:
        return None
    try:
        return int(m.group("status") or "")
    except Exception:
        return None


def looks_like_http_trace(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    head = text[:120000]
    reqs = list(_REQ_RE.finditer(head))
    if not reqs:
        return False
    if not _RESP_RE.search(head):
        return False
    # curl -v style uses ">" and "<" prefixes for headers and start lines.
    if len(reqs) >= 2:
        return True
    lowered = head.lower()
    return "> host:" in lowered or "< server:" in lowered or "< content-type:" in lowered


class HTTPTraceChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            blocks = _build_request_blocks(text)
            if not blocks:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "http_trace"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["http_trace_fallback"] = True
                    meta.setdefault("doc_type_kwd", "http")
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            first = blocks[0]
            if first.start > 0:
                pre = text[: first.start]
                if pre.strip():
                    split_docs = self._fallback_splitter.create_documents(texts=[pre], metadatas=[base_meta])
                    for sd in split_docs:
                        local_start = sd.metadata.pop("start_index", None) or 0
                        abs_start = int(local_start)
                        abs_end = abs_start + len(sd.page_content)
                        meta: dict[str, Any] = dict(base_meta)
                        meta.update(sd.metadata or {})
                        meta["chunk_strategy"] = "http_trace"
                        meta["start_char"] = abs_start
                        meta["end_char"] = abs_end
                        meta["http_trace_preamble"] = True
                        meta.setdefault("doc_type_kwd", "http")
                        out.append(Document(page_content=sd.page_content, metadata=meta))

            for blk in blocks:
                blk_text = text[blk.start : blk.end]
                if not blk_text.strip():
                    continue
                status = _extract_status(blk_text)

                split_docs = self._fallback_splitter.create_documents(texts=[blk_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = blk.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "http_trace"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "http")
                    meta["http_method"] = blk.method
                    meta["http_path"] = blk.path
                    meta["http_request_index"] = int(blk.index)
                    meta["http_request_count"] = int(len(blocks))
                    if status is not None:
                        meta["http_status"] = int(status)

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
