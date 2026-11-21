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
from itertools import islice
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.utils.source_lines import apply_splitter_span


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
    r"`?(?P<path>/[^\s`]*)(?=[`\s]|$)`?.*$"
)


def _iter_endpoints(text: str) -> list[_Endpoint]:
    matches = list(_ENDPOINT_RE.finditer(text))
    if len(matches) < 2:
        return []

    endpoints: list[_Endpoint] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        method = m.group("method").upper()
        path = m.group("path")
        endpoints.append(_Endpoint(start=start, end=end, index=len(endpoints), method=method, path=path))
    return endpoints


def looks_like_api_reference(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    return next(islice(_ENDPOINT_RE.finditer(text), 2, None), None) is not None


class APIReferenceChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
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
    ) -> None:
        split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
        for sd in split_docs:
            local_start = sd.metadata.pop("start_index", None)
            meta: dict[str, Any] = dict(base_meta)
            meta.update(sd.metadata)
            meta["chunk_strategy"] = "api_reference"
            apply_splitter_span(meta, start_index=local_start, content=sd.page_content, base_offset=offset)
            meta.setdefault("doc_type_kwd", "api")
            meta.update(extra_meta)
            out.append(Document(page_content=sd.page_content, metadata=meta))

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content
            base_meta = dict(doc.metadata)
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
                )
                continue

            # Prefix before first endpoint (overview, auth, etc.).
            if endpoints[0].start > 0 and (text[: endpoints[0].start]).strip():
                prefix = text[: endpoints[0].start]
                self._append_chunks(
                    out,
                    text=prefix,
                    base_meta=base_meta,
                    offset=0,
                    extra_meta={"endpoint_index": -1},
                )

            for ep in endpoints:
                ep_text = text[ep.start : ep.end]
                sig = f"{ep.method} {ep.path}"
                self._append_chunks(
                    out,
                    text=ep_text,
                    base_meta=base_meta,
                    offset=ep.start,
                    extra_meta={
                        "endpoint_index": ep.index,
                        "http_method": ep.method,
                        "api_path": ep.path,
                        "endpoint_signature": sig,
                    },
                )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata)
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
