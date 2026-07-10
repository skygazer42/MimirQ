"""
API reference aware chunking strategy.

Targets API docs that enumerate endpoints, e.g.:
- ### GET /api/v1/users
- POST /v1/chat/completions
- - GET `/health`

The chunker splits the document into endpoint blocks first, then applies a
fallback RecursiveCharacterTextSplitter inside each block while preserving
character offsets.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Endpoint:
    start: int
    end: int
    index: int
    method: str
    path: str


_ENDPOINT_RE = re.compile(
    r"(?mi)^\s*(?:[-*+]\s*|\d+\.\s*)?(?:#{1,6}\s*)?"
    r"(?P<method>GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+"
    r"`?(?P<path>/[^\s`]+)`?\b.*$"
)


def _iter_endpoints(text: str) -> list[_Endpoint]:
    matches = list(_ENDPOINT_RE.finditer(text or ""))
    if len(matches) < 2:
        return []

    endpoints: list[_Endpoint] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        method = (m.group("method") or "").strip().upper()
        path = (m.group("path") or "").strip()
        if not method or not path:
            continue
        endpoints.append(_Endpoint(start=start, end=end, index=len(endpoints), method=method, path=path))
    return endpoints if len(endpoints) >= 2 else []


def looks_like_api_reference(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    eps = _iter_endpoints(text)
    return len(eps) >= 3


class APIReferenceChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", ". ", "!", "?", " ", ""],
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

            endpoints = _iter_endpoints(text)
            if not endpoints:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "api_reference"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["api_fallback"] = True
                    meta.setdefault("doc_type_kwd", "api")
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            # Prefix before first endpoint (overview, auth, etc.).
            if endpoints[0].start > 0 and (text[: endpoints[0].start] or "").strip():
                prefix = text[: endpoints[0].start]
                split_docs = self._fallback_splitter.create_documents(texts=[prefix], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "api_reference"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["endpoint_index"] = -1
                    meta.setdefault("doc_type_kwd", "api")
                    out.append(Document(page_content=sd.page_content, metadata=meta))

            for ep in endpoints:
                ep_text = text[ep.start : ep.end]
                if not ep_text.strip():
                    continue
                sig = f"{ep.method} {ep.path}"

                split_docs = self._fallback_splitter.create_documents(texts=[ep_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = ep.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "api_reference"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "api")
                    meta["endpoint_index"] = int(ep.index)
                    meta["http_method"] = ep.method
                    meta["api_path"] = ep.path
                    meta["endpoint_signature"] = sig
                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
