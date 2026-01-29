"""
SOP / procedure step-aware chunking strategy.

Targets documents that describe procedures with explicit step markers:
- Step 1: ...
- 步骤一：...

The chunker splits by detected steps first, then applies a fallback
RecursiveCharacterTextSplitter inside each step to respect chunk_size and
chunk_overlap while preserving offsets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class StepHeading:
    start: int
    end: int
    text: str
    step_no: str
    title: Optional[str]


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: Optional[StepHeading]


_RE_EN_STEP = re.compile(
    r"^\s*(?:step)\s*(?P<num>\d{1,3})\s*[:：.\-]?\s*(?P<title>.+?)?\s*$",
    flags=re.IGNORECASE,
)
_RE_CN_STEP = re.compile(
    r"^\s*(?:步骤)\s*(?P<num>[0-9一二三四五六七八九十百千]{1,4})\s*[:：.\-]?\s*(?P<title>.+?)?\s*$"
)


def _iter_steps(text: str) -> List[StepHeading]:
    steps: List[StepHeading] = []
    if not text:
        return steps

    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)

        line = raw_line.strip()
        if not line:
            continue
        if len(line) > 200:
            continue

        m = _RE_CN_STEP.match(raw_line) or _RE_EN_STEP.match(raw_line)
        if not m:
            continue

        num = (m.group("num") or "").strip()
        title = (m.group("title") or "").strip() if m.groupdict().get("title") is not None else None
        title = title or None

        steps.append(
            StepHeading(
                start=line_start,
                end=line_start + len(raw_line),
                text=line,
                step_no=num or "?",
                title=title,
            )
        )

    deduped: List[StepHeading] = []
    last_start = -1
    for s in steps:
        if s.start == last_start:
            continue
        deduped.append(s)
        last_start = s.start
    return deduped


def _build_sections(text: str, steps: List[StepHeading]) -> List[_Section]:
    if not steps:
        return [_Section(start=0, end=len(text), heading=None)]

    sections: List[_Section] = []
    first = steps[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, heading=None))
    for idx, h in enumerate(steps):
        start = h.start
        end = steps[idx + 1].start if idx + 1 < len(steps) else len(text)
        sections.append(_Section(start=start, end=end, heading=h))
    return sections


def looks_like_sop(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    steps = _iter_steps(text)
    return len(steps) >= 3


class SOPStepsChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "；", "，", ". ", "!", "?", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        out: List[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            steps = _iter_steps(text)
            sections = _build_sections(text, steps)
            if not steps:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "sop_steps"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["sop_fallback"] = True
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                heading = section.heading
                split_docs = self._fallback_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "sop_steps"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    if heading is not None:
                        meta["sop_step_heading"] = heading.text
                        meta["sop_step_no"] = heading.step_no
                        if heading.title:
                            meta["sop_step_title"] = heading.title
                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

