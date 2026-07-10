"""
XML feed (RSS/Atom) item-aware chunking strategy.

Targets XML feeds with repeated <item> (RSS) or <entry> (Atom) blocks.
The chunker splits the document into items/entries first, then applies a
fallback RecursiveCharacterTextSplitter inside each block while preserving
character offsets.
"""


import html as _html
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Block:
    start: int
    end: int
    kind: str
    index: int
    title: str | None


_ITEM_START_RE = re.compile(r"(?is)<item\b[^>]*>")
_ITEM_END_RE = re.compile(r"(?is)</item\s*>")
_ENTRY_START_RE = re.compile(r"(?is)<entry\b[^>]*>")
_ENTRY_END_RE = re.compile(r"(?is)</entry\s*>")
_TITLE_RE = re.compile(r"(?is)<title\b[^>]*>(?P<body>.*?)</title\s*>")
_TAG_STRIP_RE = re.compile(r"(?is)<[^>]+>")


def _clean_text(s: str) -> str:
    out = _TAG_STRIP_RE.sub("", s or "")
    out = _html.unescape(out)
    return re.sub(r"\s+", " ", out).strip()


def _extract_title(block_text: str) -> str | None:
    m = _TITLE_RE.search(block_text or "")
    if not m:
        return None
    title = _clean_text(m.group("body") or "")
    return title[:200] or None


def _iter_blocks(text: str, *, kind: str) -> list[_Block]:
    if not text:
        return []

    if kind == "item":
        start_re, end_re = _ITEM_START_RE, _ITEM_END_RE
    else:
        start_re, end_re = _ENTRY_START_RE, _ENTRY_END_RE

    blocks: list[_Block] = []
    for sm in start_re.finditer(text):
        em = end_re.search(text, pos=sm.end())
        if not em:
            continue
        start = sm.start()
        end = em.end()
        if end < len(text) and text[end : end + 1] == "\n":
            end += 1
        blk_text = text[start:end]
        blocks.append(
            _Block(
                start=start,
                end=end,
                kind=kind,
                index=len(blocks),
                title=_extract_title(blk_text),
            )
        )
    return blocks


def looks_like_xml_feed(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    lowered = text.lower()
    if "<rss" not in lowered and "<feed" not in lowered:
        return False
    item_n = len(_ITEM_START_RE.findall(text[:200000]))
    entry_n = len(_ENTRY_START_RE.findall(text[:200000]))
    return max(item_n, entry_n) >= 2


class XMLFeedChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", "。", "！", "？", " ", ""],
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

            items = _iter_blocks(text, kind="item")
            entries = _iter_blocks(text, kind="entry")
            blocks = items if len(items) >= len(entries) else entries
            if not blocks:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "xml_feed"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["xml_feed_fallback"] = True
                    meta.setdefault("doc_type_kwd", "xml")
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            # Preamble before the first entry/item.
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
                        meta["chunk_strategy"] = "xml_feed"
                        meta["start_char"] = abs_start
                        meta["end_char"] = abs_end
                        meta["xml_feed_preamble"] = True
                        meta.setdefault("doc_type_kwd", "xml")
                        out.append(Document(page_content=sd.page_content, metadata=meta))

            for blk in blocks:
                blk_text = text[blk.start : blk.end]
                if not blk_text.strip():
                    continue
                split_docs = self._fallback_splitter.create_documents(texts=[blk_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = blk.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "xml_feed"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "xml")
                    meta["xml_feed_kind"] = blk.kind
                    meta["xml_feed_index"] = int(blk.index)
                    meta["xml_feed_count"] = int(len(blocks))
                    if blk.title:
                        meta["xml_feed_title"] = blk.title

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
