"""
Academic paper / report aware chunking strategy.

Targets documents with common paper section headings, such as:
- Abstract / 摘要
- Introduction / 引言
- Methods / 方法
- Results / 结果
- Discussion / 讨论
- Conclusion / 结论
- References / 参考文献

The chunker splits by detected section headings first, then applies a fallback
RecursiveCharacterTextSplitter inside each section to respect chunk_size and
chunk_overlap while preserving character offsets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class PaperHeading:
    start: int
    end: int
    text: str
    section: str


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: PaperHeading | None


_EN_SECTIONS: dict[str, str] = {
    "abstract": "abstract",
    "introduction": "introduction",
    "background": "background",
    "related work": "related_work",
    "related works": "related_work",
    "method": "methods",
    "methods": "methods",
    "methodology": "methods",
    "materials and methods": "methods",
    "experiment": "experiments",
    "experiments": "experiments",
    "result": "results",
    "results": "results",
    "discussion": "discussion",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "acknowledgement": "acknowledgements",
    "acknowledgements": "acknowledgements",
    "references": "references",
    "bibliography": "references",
    "appendix": "appendix",
    "supplementary material": "supplementary",
    "supplementary materials": "supplementary",
}

_CN_SECTIONS: dict[str, str] = {
    "摘要": "abstract",
    "引言": "introduction",
    "绪论": "introduction",
    "前言": "introduction",
    "背景": "background",
    "相关工作": "related_work",
    "研究现状": "related_work",
    "方法": "methods",
    "研究方法": "methods",
    "材料与方法": "methods",
    "实验": "experiments",
    "实验设计": "experiments",
    "实验结果": "results",
    "结果": "results",
    "讨论": "discussion",
    "结论": "conclusion",
    "总结": "conclusion",
    "致谢": "acknowledgements",
    "参考文献": "references",
    "附录": "appendix",
    "补充材料": "supplementary",
}

def _normalize_section(title: str) -> str | None:
    raw = (title or "").strip()
    if not raw:
        return None
    if raw in _CN_SECTIONS:
        return _CN_SECTIONS[raw]
    lower = raw.lower().strip()
    lower = " ".join(lower.split())
    return _EN_SECTIONS.get(lower)


def _strip_leading_number_prefix(line: str) -> str:
    """
    Strip common section numbering like:
      1 Introduction
      1.2.3 Methods

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    s = str(line or "").lstrip()
    if not s or not s[:1].isdigit():
        return s

    i = 0
    # First group: 1-2 digits.
    digits = 0
    while i < len(s) and digits < 2 and s[i].isdigit():
        i += 1
        digits += 1
    if digits == 0:
        return s

    # Optional ".<digits>" groups (up to 3).
    groups = 0
    while groups < 3 and i < len(s) and s[i] == ".":
        j = i + 1
        d2 = 0
        while j < len(s) and d2 < 2 and s[j].isdigit():
            j += 1
            d2 += 1
        if d2 == 0:
            break
        i = j
        groups += 1

    # Skip trailing whitespace after numbering.
    while i < len(s) and s[i].isspace():
        i += 1
    return s[i:]


def _iter_headings(text: str) -> list[PaperHeading]:
    headings: list[PaperHeading] = []
    if not text:
        return headings

    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)

        line = raw_line.strip()
        if not line:
            continue
        if len(line) > 90:
            continue

        # Best-effort heading extraction without regex. We rely on _normalize_section's
        # tight mapping to keep false positives low.
        candidate = _strip_leading_number_prefix(line).strip()
        candidate = candidate.rstrip(":：").strip()

        section = _normalize_section(candidate)
        if not section:
            continue

        headings.append(
            PaperHeading(
                start=line_start,
                end=line_start + len(raw_line),
                text=line,
                section=section,
            )
        )

    # Best-effort de-dup.
    deduped: list[PaperHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: list[PaperHeading]) -> list[_Section]:
    if not headings:
        return [_Section(start=0, end=len(text), heading=None)]

    sections: list[_Section] = []
    first = headings[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, heading=None))
    for idx, h in enumerate(headings):
        start = h.start
        end = headings[idx + 1].start if idx + 1 < len(headings) else len(text)
        sections.append(_Section(start=start, end=end, heading=h))
    return sections


def looks_like_paper(text: str) -> bool:
    if not text or len(text) < 600:
        return False
    headings = _iter_headings(text)
    if len(headings) < 2:
        return False
    sections = {h.section for h in headings}
    # Require at least one strong signal section.
    return bool(sections & {"abstract", "introduction", "methods", "references"})


class PaperChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", "。", "，", "!", "?", " ", ""],
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

            headings = _iter_headings(text)
            sections = _build_sections(text, headings)

            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                heading = section.heading
                split_docs = self._fallback_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None)
                    if local_start is None:
                        local_start = 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "paper"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    if heading is not None:
                        meta["paper_heading"] = heading.text
                        meta["paper_section"] = heading.section
                        if heading.section == "references":
                            meta["paper_is_references"] = True

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
