"""
SOP / procedure step-aware chunking strategy.

Targets documents that describe procedures with explicit step markers:
- Step 1: ...
- 步骤一：...

The chunker splits by detected steps first, then applies a fallback
RecursiveCharacterTextSplitter inside each step to respect chunk_size and
chunk_overlap while preserving offsets.
"""


from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class StepHeading:
    start: int
    end: int
    text: str
    step_no: str
    title: str | None


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: StepHeading | None


_CN_STEP_NUM_CHARS = frozenset("0123456789一二三四五六七八九十百千")


def _parse_step_heading(line: str) -> tuple[str, str | None] | None:
    """
    Parse a step heading line like:
      Step 1: Title
      步骤一：标题

    Returns (num, title).

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    s = str(line or "").strip()
    if not s:
        return None

    low = s.casefold()
    if low.startswith("step"):
        rest = s[len("step") :].strip()
        if not rest:
            return None
        i = 0
        while i < len(rest) and i < 3 and rest[i].isdigit():
            i += 1
        if i == 0:
            return None
        num = rest[:i]
        tail = rest[i:].lstrip()
        if tail[:1] in (":", "：", ".", "-"):
            tail = tail[1:].lstrip()
        title = tail.strip() or None
        return num, title

    if s.startswith("步骤"):
        rest = s[len("步骤") :].strip()
        if not rest:
            return None
        i = 0
        while i < len(rest) and i < 4 and rest[i] in _CN_STEP_NUM_CHARS:
            i += 1
        if i == 0:
            return None
        num = rest[:i]
        tail = rest[i:].lstrip()
        if tail[:1] in (":", "：", ".", "-"):
            tail = tail[1:].lstrip()
        title = tail.strip() or None
        return num, title

    return None


def _iter_steps(text: str) -> list[StepHeading]:
    steps: list[StepHeading] = []
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

        parsed = _parse_step_heading(line)
        if not parsed:
            continue

        num, title = parsed

        steps.append(
            StepHeading(
                start=line_start,
                end=line_start + len(raw_line),
                text=line,
                step_no=num or "?",
                title=title,
            )
        )

    deduped: list[StepHeading] = []
    last_start = -1
    for s in steps:
        if s.start == last_start:
            continue
        deduped.append(s)
        last_start = s.start
    return deduped


def _build_sections(text: str, steps: list[StepHeading]) -> list[_Section]:
    if not steps:
        return [_Section(start=0, end=len(text), heading=None)]

    sections: list[_Section] = []
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

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

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
