"""
Dockerfile-aware chunking strategy.

Targets Dockerfile text with instructions like:
- FROM python:3.11-slim AS base
- RUN ...
- COPY ...

The chunker groups whole instruction blocks together, and splits by stages
when multiple FROM instructions exist. Offsets are preserved.
"""

import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    plain: str


@dataclass(frozen=True)
class _Instr:
    start: int
    end: int
    keyword: str


@dataclass(frozen=True)
class _Stage:
    start: int
    end: int
    index: int
    from_image: str | None
    from_alias: str | None


_INSTR_RE = re.compile(
    r"^(?P<kw>FROM|RUN|CMD|ENTRYPOINT|LABEL|MAINTAINER|EXPOSE|ENV|ADD|COPY|VOLUME|USER|WORKDIR|ARG|ONBUILD|STOPSIGNAL|HEALTHCHECK|SHELL)\b",
    re.IGNORECASE,
)
_FROM_RE = re.compile(r"(?i)^\s*from\s+(?P<img>\S+)(?:\s+as\s+(?P<as>\S+))?\s*$")


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


def _iter_instructions(text: str, *, start: int, end: int) -> list[_Instr]:
    lines = _iter_lines(text[start:end])
    instr_idx: list[int] = []
    kws: list[str] = []

    for i, ln in enumerate(lines):
        plain = ln.plain
        if not plain.strip() or plain.lstrip().startswith("#"):
            continue
        m = _INSTR_RE.match(plain.lstrip())
        if not m:
            continue
        kw = (m.group("kw") or "").upper()
        instr_idx.append(i)
        kws.append(kw)

    instrs: list[_Instr] = []
    for idx, i in enumerate(instr_idx):
        ln = lines[i]
        instr_start = start + ln.start
        instr_end = start + (lines[instr_idx[idx + 1]].start if idx + 1 < len(instr_idx) else (end - start))
        instrs.append(_Instr(start=instr_start, end=instr_end, keyword=kws[idx]))
    return instrs


def _build_stages(text: str) -> list[_Stage]:
    lines = _iter_lines(text)
    from_lines: list[int] = []
    for i, ln in enumerate(lines):
        if _FROM_RE.match(ln.plain):
            from_lines.append(i)
    if not from_lines:
        return [_Stage(start=0, end=len(text), index=0, from_image=None, from_alias=None)]

    stages: list[_Stage] = []
    for idx, i in enumerate(from_lines):
        start = lines[i].start
        end = lines[from_lines[idx + 1]].start if idx + 1 < len(from_lines) else len(text)
        m = _FROM_RE.match(lines[i].plain)
        img = (m.group("img") or "").strip() if m else ""
        als = (m.group("as") or "").strip() if m else ""
        stages.append(
            _Stage(
                start=start,
                end=end,
                index=int(idx),
                from_image=img or None,
                from_alias=als or None,
            )
        )
    return stages


def looks_like_dockerfile(text: str) -> bool:
    if not text or len(text) < 40:
        return False
    lines = [ln for ln in (text or "").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return False
    head = "\n".join(lines[:80])
    if re.search(r"(?mi)^\s*from\s+\S+", head) and re.search(
        r"(?mi)^\s*(run|copy|add|cmd|entrypoint|env|workdir)\b", head
    ):
        return True
    return False


def _docker_stage_meta(base_meta: dict[str, Any], *, stage: _Stage, start_char: int, end_char: int) -> dict[str, Any]:
    meta: dict[str, Any] = dict(base_meta)
    meta["chunk_strategy"] = "dockerfile"
    meta["start_char"] = start_char
    meta["end_char"] = end_char
    meta.setdefault("doc_type_kwd", "dockerfile")
    meta["docker_stage_index"] = int(stage.index)
    if stage.from_image:
        meta["docker_from_image"] = stage.from_image
    if stage.from_alias:
        meta["docker_from_alias"] = stage.from_alias
    return meta


def _instruction_window_end(instrs: list[_Instr], start_idx: int, chunk_size: int) -> int:
    end_idx = start_idx
    while end_idx < len(instrs):
        cand_len = instrs[end_idx].end - instrs[start_idx].start
        if end_idx == start_idx or cand_len <= chunk_size:
            end_idx += 1
            continue
        break
    return end_idx if end_idx > start_idx else start_idx + 1


def _window_instruction_keywords(instrs: list[_Instr], start_idx: int, end_idx: int) -> list[str]:
    uniq: list[str] = []
    for instr in instrs[start_idx:end_idx]:
        if instr.keyword and instr.keyword not in uniq:
            uniq.append(instr.keyword)
    return uniq[:20]


def _next_instruction_start(instrs: list[_Instr], start_idx: int, end_idx: int, chunk_overlap: int) -> int:
    next_start = end_idx
    if chunk_overlap <= 0 or (end_idx - start_idx) <= 1:
        return next_start

    desired = end_idx - 1
    while desired > start_idx:
        overlap_len = instrs[end_idx - 1].end - instrs[desired - 1].start
        if overlap_len <= chunk_overlap:
            desired -= 1
            continue
        break
    next_start = desired if desired > start_idx else (end_idx - 1)
    return next_start if next_start > start_idx else end_idx


class DockerfileChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            out.extend(self._split_document(doc))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

    def _split_document(self, doc: Document) -> list[Document]:
        text = doc.page_content or ""
        if not text.strip():
            return []

        base_meta = dict(doc.metadata or {})
        chunks: list[Document] = []
        for stage in _build_stages(text):
            chunks.extend(self._split_stage(text, base_meta, stage))
        return chunks

    def _split_stage(self, text: str, base_meta: dict[str, Any], stage: _Stage) -> list[Document]:
        instrs = _iter_instructions(text, start=stage.start, end=stage.end)
        if not instrs:
            return self._stage_fallback_chunk(text, base_meta, stage)

        chunks: list[Document] = []
        start_idx = 0
        while start_idx < len(instrs):
            end_idx = _instruction_window_end(instrs, start_idx, self.chunk_size)
            chunk = self._instruction_chunk(text, base_meta, stage, instrs, start_idx, end_idx)
            if chunk is not None:
                chunks.append(chunk)
            start_idx = _next_instruction_start(instrs, start_idx, end_idx, self.chunk_overlap)
        return chunks

    def _stage_fallback_chunk(self, text: str, base_meta: dict[str, Any], stage: _Stage) -> list[Document]:
        content = text[stage.start : stage.end]
        if not content.strip():
            return []
        meta = _docker_stage_meta(base_meta, stage=stage, start_char=stage.start, end_char=stage.end)
        return [Document(page_content=content, metadata=meta)]

    def _instruction_chunk(
        self,
        text: str,
        base_meta: dict[str, Any],
        stage: _Stage,
        instrs: list[_Instr],
        start_idx: int,
        end_idx: int,
    ) -> Document | None:
        chunk_start = instrs[start_idx].start
        chunk_end = instrs[end_idx - 1].end
        content = text[chunk_start:chunk_end]
        if not content.strip():
            return None

        meta = _docker_stage_meta(base_meta, stage=stage, start_char=chunk_start, end_char=chunk_end)
        keywords = _window_instruction_keywords(instrs, start_idx, end_idx)
        if keywords:
            meta["docker_instructions"] = keywords
        return Document(page_content=content, metadata=meta)
