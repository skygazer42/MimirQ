"""
Sitemap XML aware chunking strategy.

Targets sitemap.xml / sitemap index XML and splits by <url> or <sitemap> entry
blocks while preserving offsets.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Entry:
    start: int
    end: int
    kind: str
    index: int
    loc: str | None


_URL_START_RE = re.compile(r"(?is)<url\b[^>]*>")
_URL_END_RE = re.compile(r"(?is)</url\s*>")
_SITEMAP_START_RE = re.compile(r"(?is)<sitemap\b[^>]*>")
_SITEMAP_END_RE = re.compile(r"(?is)</sitemap\s*>")
_LOC_RE = re.compile(r"(?is)<loc\b[^>]*>(?P<body>.*?)</loc\s*>")


def _extract_loc(block_text: str) -> str | None:
    m = _LOC_RE.search(block_text or "")
    if not m:
        return None
    loc = (m.group("body") or "").strip()
    loc = re.sub(r"\s+", " ", loc)
    return loc[:300] or None


def _iter_entries(text: str, *, kind: str) -> list[_Entry]:
    if not text:
        return []
    if kind == "url":
        start_re, end_re = _URL_START_RE, _URL_END_RE
    else:
        start_re, end_re = _SITEMAP_START_RE, _SITEMAP_END_RE

    entries: list[_Entry] = []
    for sm in start_re.finditer(text):
        em = end_re.search(text, pos=sm.end())
        if not em:
            continue
        start = sm.start()
        end = em.end()
        if end < len(text) and text[end : end + 1] == "\n":
            end += 1
        blk_text = text[start:end]
        entries.append(
            _Entry(
                start=start,
                end=end,
                kind=kind,
                index=len(entries),
                loc=_extract_loc(blk_text),
            )
        )
    return entries


def looks_like_sitemap_xml(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    lowered = text.lower()
    if "<urlset" not in lowered and "<sitemapindex" not in lowered:
        return False
    urls = len(_URL_START_RE.findall(text[:200000]))
    maps = len(_SITEMAP_START_RE.findall(text[:200000]))
    return max(urls, maps) >= 2


def _build_split_documents(
    *,
    split_docs: list[Document],
    base_meta: dict[str, Any],
    start_offset: int = 0,
    extra_meta: dict[str, Any] | None = None,
) -> list[Document]:
    out: list[Document] = []
    for sd in split_docs:
        local_start = sd.metadata.pop("start_index", None) or 0
        abs_start = start_offset + int(local_start)
        abs_end = abs_start + len(sd.page_content)
        meta: dict[str, Any] = dict(base_meta)
        meta.update(sd.metadata or {})
        meta["chunk_strategy"] = "sitemap_xml"
        meta["start_char"] = abs_start
        meta["end_char"] = abs_end
        meta.setdefault("doc_type_kwd", "sitemap")
        if extra_meta:
            meta.update(extra_meta)
        out.append(Document(page_content=sd.page_content, metadata=meta))
    return out


class SitemapXMLChunker(BaseChunker):
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

            urls = _iter_entries(text, kind="url")
            maps = _iter_entries(text, kind="sitemap")
            entries = urls if len(urls) >= len(maps) else maps

            if not entries:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                out.extend(
                    _build_split_documents(
                        split_docs=split_docs,
                        base_meta=base_meta,
                        extra_meta={"sitemap_xml_fallback": True},
                    )
                )
                continue

            first = entries[0]
            if first.start > 0:
                pre = text[: first.start]
                if pre.strip():
                    split_docs = self._fallback_splitter.create_documents(texts=[pre], metadatas=[base_meta])
                    out.extend(
                        _build_split_documents(
                            split_docs=split_docs,
                            base_meta=base_meta,
                            extra_meta={"sitemap_xml_preamble": True},
                        )
                    )

            for ent in entries:
                ent_text = text[ent.start : ent.end]
                if not ent_text.strip():
                    continue
                split_docs = self._fallback_splitter.create_documents(texts=[ent_text], metadatas=[base_meta])
                extra_meta: dict[str, Any] = {
                    "sitemap_kind": ent.kind,
                    "sitemap_index": int(ent.index),
                    "sitemap_count": int(len(entries)),
                }
                if ent.loc:
                    extra_meta["sitemap_loc"] = ent.loc
                out.extend(
                    _build_split_documents(
                        split_docs=split_docs,
                        base_meta=base_meta,
                        start_offset=ent.start,
                        extra_meta=extra_meta,
                    )
                )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
