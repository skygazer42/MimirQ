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

    def _append_chunks(
        self,
        out: list[Document],
        *,
        text: str,
        base_meta: dict[str, Any],
        offset: int,
        extra_meta: dict[str, Any],
        doc_type_kwd: str | None = None,
    ) -> None:
        split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
        for sd in split_docs:
            local_start = sd.metadata.pop("start_index", None) or 0
            abs_start = offset + int(local_start)
            abs_end = abs_start + len(sd.page_content)
            meta: dict[str, Any] = dict(base_meta)
            meta.update(sd.metadata or {})
            meta["chunk_strategy"] = "api_reference"
            meta["start_char"] = abs_start
            meta["end_char"] = abs_end
            if doc_type_kwd:
                meta.setdefault("doc_type_kwd", doc_type_kwd)
            meta.update(extra_meta)
            out.append(Document(page_content=sd.page_content, metadata=meta))

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            endpoints = _iter_endpoints(text)
            if not endpoints:
                self._append_chunks(
                    out,
                    text=text,
                    base_meta=base_meta,
                    offset=0,
                    extra_meta={"api_fallback": True},
                    doc_type_kwd="api",
                )
                continue

            # Prefix before first endpoint (overview, auth, etc.).
            if endpoints[0].start > 0 and (text[: endpoints[0].start] or "").strip():
                prefix = text[: endpoints[0].start]
                self._append_chunks(
                    out,
                    text=prefix,
                    base_meta=base_meta,
                    offset=0,
                    extra_meta={"endpoint_index": -1},
                    doc_type_kwd="api",
                )

            for ep in endpoints:
                ep_text = text[ep.start : ep.end]
                if not ep_text.strip():
                    continue
                sig = f"{ep.method} {ep.path}"
                self._append_chunks(
                    out,
                    text=ep_text,
                    base_meta=base_meta,
                    offset=ep.start,
                    extra_meta={
                        "endpoint_index": int(ep.index),
                        "http_method": ep.method,
                        "api_path": ep.path,
                        "endpoint_signature": sig,
                    },
                    doc_type_kwd="api",
                )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
