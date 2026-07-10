"""
Stacktrace aware chunking strategy.

Targets plain stack traces (Python/Java/Node/etc) and groups each traceback /
exception block together. For timestamped application logs, prefer log_events.

Offsets are preserved.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    plain: str


@dataclass(frozen=True)
class _Block:
    start: int
    end: int
    kind: str
    exception: str | None
    frame_count: int


_PY_START_RE = re.compile(r"(?m)^\s*Traceback \(most recent call last\):\s*$")
_JAVA_START_RE = re.compile(r"^\s*(Exception in thread .+|[A-Za-z0-9_.]+(?:Exception|Error)(?::|$).*)$")
_FRAME_RE = re.compile(r"^\s*(?:File \"|File '|at\s+|\tat\s+)")
_CAUSED_BY_RE = re.compile(r"^\s*Caused by:\s+")
_PY_EXCEPTION_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.]*)(?:Error|Exception)\b.*")
_JS_EXCEPTION_RE = re.compile(r"^\s*(Error|TypeError|ReferenceError|SyntaxError|RangeError|URIError)\b.*")


def _iter_lines(text: str) -> list[_Line]:
    out: list[_Line] = []
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        start = offset
        end = start + len(raw)
        offset = end
        out.append(_Line(start=start, end=end, plain=raw.rstrip("\r\n")))
    if not out and text:
        out.append(_Line(start=0, end=len(text), plain=text))
    return out


def _has_frames(lines: list[_Line], i: int) -> bool:
    for j in range(i, min(len(lines), i + 30)):
        p = lines[j].plain
        if _FRAME_RE.match(p):
            return True
    return False


def _is_block_start(lines: list[_Line], i: int) -> bool:
    p = lines[i].plain
    if _PY_START_RE.match(p):
        return True
    if _JAVA_START_RE.match(p) and _has_frames(lines, i):
        return True
    if _CAUSED_BY_RE.match(p) and _has_frames(lines, i):
        return True
    return False


def _infer_kind(block_text: str) -> str:
    lowered = (block_text or "").lower()
    if "traceback (most recent call last)" in lowered:
        return "python"
    if "\tat " in block_text or re.search(r"(?m)^\s*at\s+\S+", block_text):
        return "java"
    if re.search(r"(?m)^\s*at\s+\S+", block_text) and "error" in lowered:
        return "node"
    return "generic"


def _infer_exception(lines: list[_Line], start: int, end: int) -> str | None:
    for i in range(end - 1, start - 1, -1):
        p = lines[i].plain.strip()
        if not p:
            continue
        m = _JS_EXCEPTION_RE.match(p)
        if m:
            return (m.group(0) or "").strip()[:160] or None
        m = _PY_EXCEPTION_RE.match(p)
        if m:
            return p[:160] or None
        if p.lower().startswith("caused by:"):
            return p[:160] or None
        if "exception" in p.lower() or "error" in p.lower():
            return p[:160] or None
    return None


def _count_frames(lines: list[_Line], start: int, end: int) -> int:
    n = 0
    for i in range(start, end):
        if _FRAME_RE.match(lines[i].plain):
            n += 1
    return n


def _build_blocks(text: str) -> list[_Block]:
    if not text:
        return []
    lines = _iter_lines(text)
    if not lines:
        return []

    starts: list[int] = []
    for i in range(len(lines)):
        if _is_block_start(lines, i):
            starts.append(i)

    if not starts:
        return [_Block(start=0, end=len(text), kind=_infer_kind(text), exception=None, frame_count=0)]

    blocks: list[_Block] = []
    for idx, i in enumerate(starts):
        j = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        start_pos = lines[i].start
        end_pos = lines[j - 1].end if j - 1 >= i else lines[i].end
        block_text = text[start_pos:end_pos]
        kind = _infer_kind(block_text)
        exc = _infer_exception(lines, i, j)
        frames = _count_frames(lines, i, j)
        blocks.append(_Block(start=start_pos, end=end_pos, kind=kind, exception=exc, frame_count=frames))

    return blocks


def looks_like_stacktrace(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    if _PY_START_RE.search(text):
        return True
    head_lines = (text or "").splitlines()[:200]
    frame_lines = 0
    exc_lines = 0
    for ln in head_lines:
        if _FRAME_RE.match(ln):
            frame_lines += 1
        if "exception" in ln.lower() or "error" in ln.lower():
            exc_lines += 1
    return frame_lines >= 3 and exc_lines >= 1


class StackTraceChunker(BaseChunker):
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

            blocks = _build_blocks(text)
            for b in blocks:
                blk_text = text[b.start : b.end]
                if not blk_text.strip():
                    continue

                split_docs = self._fallback_splitter.create_documents(texts=[blk_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = b.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "stacktrace"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "stacktrace")

                    meta["stacktrace_kind"] = b.kind
                    meta["stacktrace_frame_count"] = int(b.frame_count)
                    if b.exception:
                        meta["stacktrace_exception"] = b.exception

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
