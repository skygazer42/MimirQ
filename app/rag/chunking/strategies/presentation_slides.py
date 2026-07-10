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
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


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
    matches = list(_HR_RE.finditer(text or ""))
    if len(matches) < 2:
        return []

    slides: list[_Slide] = []
    cursor = 0
    idx = 0
    for m in matches:
        start = cursor
        end = m.start()
        if end > start and (text[start:end] or "").strip():
            slides.append(_Slide(start=start, end=end, index=idx))
            idx += 1
        cursor = m.end()

    if cursor < len(text) and (text[cursor:] or "").strip():
        slides.append(_Slide(start=cursor, end=len(text), index=idx))

    return slides if len(slides) >= 2 else []


def _split_by_markers(text: str) -> list[_Slide]:
    starts: list[int] = []
    for m in _SLIDE_MARK_RE.finditer(text or ""):
        starts.append(m.start())
    for m in _CN_PAGE_RE.finditer(text or ""):
        starts.append(m.start())

    starts = sorted({i for i in starts if 0 <= i < len(text)})
    if len(starts) < 2:
        return []

    slides: list[_Slide] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(text)
        if end <= start:
            continue
        if not (text[start:end] or "").strip():
            continue
        slides.append(_Slide(start=start, end=end, index=idx))
    return slides if len(slides) >= 2 else []


def looks_like_presentation(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    if len(list(_HR_RE.finditer(text))) >= 2:
        return True
    if len(list(_SLIDE_MARK_RE.finditer(text))) >= 2:
        return True
    if len(list(_CN_PAGE_RE.finditer(text))) >= 2:
        return True
    return False


def _slide_title(slide_text: str) -> str | None:
    for ln in (slide_text or "").splitlines():
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
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "，", ". ", "!", "?", " ", ""],
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

            slides = _split_by_hr(text) or _split_by_markers(text)
            if not slides:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "presentation_slides"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["presentation_fallback"] = True
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            for slide in slides:
                slide_text = text[slide.start : slide.end]
                if not slide_text.strip():
                    continue

                title = _slide_title(slide_text)
                split_docs = self._fallback_splitter.create_documents(texts=[slide_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = slide.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "presentation_slides"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["slide_index"] = int(slide.index)
                    if title:
                        meta["slide_title"] = title
                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

