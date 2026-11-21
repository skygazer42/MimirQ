"""
Presentation / slides chunking strategy.

Targets slide-like documents with explicit slide separators or markers:
- '---' (common slide separator in Markdown/Pandoc)
- 'Slide 1', 'Page 2'
- '第3页'

The chunker splits into slide blocks first, then applies a fallback
RecursiveCharacterTextSplitter inside each slide to respect chunk_size and
chunk_overlap while preserving character offsets.
"""

import re
from dataclasses import dataclass
from itertools import chain, islice
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.utils.source_lines import apply_splitter_span


@dataclass(frozen=True)
class _Slide:
    start: int
    end: int
    index: int


_HR_RE = re.compile(r"(?m)^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")

_SLIDE_MARK_RE = re.compile(
    r"(?m)^\s*(?:#+\s*)?(?P<prefix>slide|page)\s*(?P<num>\d{1,4})\b.*$",
    flags=re.IGNORECASE,
)
_CN_PAGE_RE = re.compile(r"(?m)^\s*(?:#+\s*)?第\s*(?P<num>\d{1,4})\s*页\b.*$")


def _split_by_hr(text: str) -> list[_Slide]:
    matches = list(_HR_RE.finditer(text))
    if len(matches) < 2:
        return []

    slides: list[_Slide] = []
    cursor = 0
    idx = 0
    for m in matches:
        start = cursor
        end = m.start()
        if end > start and (text[start:end]).strip():
            slides.append(_Slide(start=start, end=end, index=idx))
            idx += 1
        cursor = m.end()

    if cursor < len(text) and (text[cursor:]).strip():
        slides.append(_Slide(start=cursor, end=len(text), index=idx))

    return slides if len(slides) >= 2 else []


def _split_by_markers(text: str) -> list[_Slide]:
    starts: list[int] = []
    for m in _SLIDE_MARK_RE.finditer(text):
        starts.append(m.start())
    for m in _CN_PAGE_RE.finditer(text):
        starts.append(m.start())

    starts = sorted(set(starts))
    if len(starts) < 2:
        return []

    slides: list[_Slide] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(text)
        slides.append(_Slide(start=start, end=end, index=idx))
    return slides if len(slides) >= 2 else []


def looks_like_presentation(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    if next(islice(_HR_RE.finditer(text), 1, None), None) is not None:
        return True
    markers = chain(_SLIDE_MARK_RE.finditer(text), _CN_PAGE_RE.finditer(text))
    return next(islice(markers, 1, None), None) is not None


def _slide_title(slide_text: str) -> str | None:
    for ln in (slide_text).splitlines():
        t = ln.strip()
        if not t:
            continue
        t = re.sub(r"^\s*#{1,6}\s+", "", t).strip()
        if not t:
            continue
        if len(t) > 120:
            t = t[:117].rstrip() + "..."
        return t
    return None


class PresentationSlidesChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "，", ". ", "!", "?", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def _append_slide_chunks(
        self,
        out: list[Document],
        *,
        text: str,
        base_meta: dict[str, Any],
        base_start: int,
        slide_index: int | None = None,
        title: str | None = None,
        fallback: bool = False,
        preamble: bool = False,
    ) -> None:
        split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
        for split_doc in split_docs:
            local_start = split_doc.metadata.pop("start_index", None)
            meta = dict(base_meta)
            meta.update(split_doc.metadata)
            meta["chunk_strategy"] = "presentation_slides"
            apply_splitter_span(meta, start_index=local_start, content=split_doc.page_content, base_offset=base_start)
            if slide_index is not None:
                meta["slide_index"] = slide_index
            if title:
                meta["slide_title"] = title
            if fallback:
                meta["presentation_fallback"] = True
            if preamble:
                meta["presentation_preamble"] = True
            out.append(Document(page_content=split_doc.page_content, metadata=meta))

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content
            base_meta = dict(doc.metadata)
            if not text.strip():
                continue

            slides = _split_by_hr(text)
            if not slides:
                slides = _split_by_markers(text)
                if slides:
                    preamble = text[: slides[0].start]
                    if preamble.strip():
                        self._append_slide_chunks(
                            out,
                            text=preamble,
                            base_meta=base_meta,
                            base_start=0,
                            fallback=True,
                            preamble=True,
                        )
            if not slides:
                self._append_slide_chunks(out, text=text, base_meta=base_meta, base_start=0, fallback=True)
                continue

            for slide in slides:
                slide_text = text[slide.start : slide.end]
                title = _slide_title(slide_text)
                self._append_slide_chunks(
                    out,
                    text=slide_text,
                    base_meta=base_meta,
                    base_start=slide.start,
                    slide_index=slide.index,
                    title=title,
                )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata)
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
