"""
Semantic sentence-based chunking strategy.

Splits text at sentence boundaries, then aggregates
sentences into chunks of the target size.
"""

import re
from dataclasses import dataclass

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker


class SemanticSentenceChunker(BaseChunker):
    """
    Lightweight semantic chunking based on sentence boundaries.

    Splits at sentence-ending punctuation, then aggregates
    sentences to reach the target chunk size.
    """

    # Regex pattern for sentence boundaries (Chinese and English)
    SENTENCE_PATTERN = re.compile(r"[^。！？.!?\n]+[。！？.!?\n]?", flags=re.S)
    _FENCED_CODE_PATTERN = re.compile(r"```.*?```", flags=re.S)
    _LIST_ITEM_RE = re.compile(r"^\s{0,3}(?:[-*+]\s+|\d+[.)]\s+)")

    def __init__(self, chunk_size: int, chunk_overlap: int, min_chunk_size: int | None = 256):
        self.chunk_size = max(chunk_size, 1)
        self.chunk_overlap = max(chunk_overlap, 0)
        self.min_chunk_size = max(0, int(256 if min_chunk_size is None else min_chunk_size))

    @dataclass(frozen=True)
    class _Unit:
        text: str
        start: int
        end: int
        kind: str  # "text" | "code" | "list"

    @dataclass
    class _BufferState:
        units: list["SemanticSentenceChunker._Unit"]
        length: int = 0

    def _in_any_span(self, idx: int, spans: list[tuple[int, int]]) -> bool:
        for s, e in spans:
            if s <= idx < e:
                return True
        return False

    def _extract_fenced_code_spans(self, text: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        for m in self._FENCED_CODE_PATTERN.finditer(text or ""):
            s, e = int(m.start()), int(m.end())
            if e > s:
                spans.append((s, e))
        spans.sort(key=lambda x: x[0])
        return spans

    def _is_list_item_start(self, line: str) -> bool:
        return bool(self._LIST_ITEM_RE.match(line or ""))

    def _is_list_item_continuation(self, line: str) -> bool:
        if not line:
            return False
        if line.strip() == "":
            return True
        return bool(re.match(r"^\s{2,}\S", line))

    def _line_offsets(self, lines: list[str]) -> list[int]:
        offsets: list[int] = []
        pos = 0
        for line in lines:
            offsets.append(pos)
            pos += len(line)
        return offsets

    def _next_non_empty_line(self, lines: list[str], start_idx: int) -> int | None:
        for idx in range(start_idx, len(lines)):
            if lines[idx].strip():
                return idx
        return None

    def _find_list_item_end(
        self,
        lines: list[str],
        offsets: list[int],
        start_idx: int,
        *,
        blocked: list[tuple[int, int]],
    ) -> int:
        idx = start_idx + 1
        while idx < len(lines):
            nxt = lines[idx]
            nxt_off = offsets[idx]
            if self._in_any_span(nxt_off, blocked) or self._is_list_item_start(nxt):
                return idx
            if nxt.strip() == "":
                next_non_empty = self._next_non_empty_line(lines, idx + 1)
                if next_non_empty is None or not self._is_list_item_continuation(lines[next_non_empty]):
                    return idx
                idx += 1
                continue
            if self._is_list_item_continuation(nxt):
                idx += 1
                continue
            return idx
        return len(lines)

    def _extract_list_item_spans(self, text: str, *, blocked: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """
        Best-effort list item span extraction (supports markdown-ish bullets and indented continuations).

        This intentionally ignores list items inside fenced code blocks.
        """
        raw = text or ""
        lines = raw.splitlines(keepends=True)
        if not lines:
            return []

        spans: list[tuple[int, int]] = []
        offsets = self._line_offsets(lines)
        idx = 0
        while idx < len(lines):
            start_off = offsets[idx]
            if not self._is_list_item_start(lines[idx]) or self._in_any_span(start_off, blocked):
                idx += 1
                continue

            start = start_off
            idx = self._find_list_item_end(lines, offsets, idx, blocked=blocked)
            end = offsets[idx] if idx < len(lines) else len(raw)
            if end > start:
                spans.append((start, end))

        spans.sort(key=lambda x: x[0])
        return spans

    def _merge_numeric_dot_runs(self, raw: str, units: list[_Unit]) -> list[_Unit]:
        if not units:
            return units

        merged: list[SemanticSentenceChunker._Unit] = []
        for unit in units:
            if merged and self._is_numeric_dot_run(raw, merged[-1], unit):
                prev = merged[-1]
                merged[-1] = self._Unit(
                    text=raw[prev.start : unit.end],
                    start=prev.start,
                    end=unit.end,
                    kind="text",
                )
                continue
            merged.append(unit)
        return merged

    def _is_numeric_dot_run(self, raw: str, left: _Unit, right: _Unit) -> bool:
        if left.kind != "text" or right.kind != "text":
            return False
        boundary = left.end
        if boundary <= 1 or boundary >= len(raw):
            return False
        return raw[boundary - 1] == "." and raw[boundary - 2].isdigit() and raw[boundary].isdigit()

    def _text_units_in_segment(self, raw: str, seg_start: int, seg_end: int) -> list[_Unit]:
        seg = raw[seg_start:seg_end]
        if not seg:
            return []

        local_units: list[SemanticSentenceChunker._Unit] = []
        for match in self.SENTENCE_PATTERN.finditer(seg):
            start = seg_start + int(match.start())
            end = seg_start + int(match.end())
            if end > start:
                local_units.append(self._Unit(text=raw[start:end], start=start, end=end, kind="text"))
        return self._merge_numeric_dot_runs(raw, local_units)

    def _build_units(self, text: str) -> list[_Unit]:
        raw = text or ""
        if not raw:
            return []

        code_spans = self._extract_fenced_code_spans(raw)
        list_spans = self._extract_list_item_spans(raw, blocked=code_spans)

        spans: list[tuple[int, int, str]] = []
        spans.extend([(s, e, "code") for s, e in code_spans])
        spans.extend([(s, e, "list") for s, e in list_spans])
        spans.sort(key=lambda x: x[0])

        units: list[SemanticSentenceChunker._Unit] = []
        cursor = 0

        for s, e, kind in spans:
            if e <= s:
                continue
            if s > cursor:
                units.extend(self._text_units_in_segment(raw, cursor, s))
            units.append(self._Unit(text=raw[s:e], start=s, end=e, kind=kind))
            cursor = max(cursor, e)

        if cursor < len(raw):
            units.extend(self._text_units_in_segment(raw, cursor, len(raw)))

        return units

    def _effective_min_chunk_size(self) -> int:
        if self.min_chunk_size <= 0:
            return 0
        return min(self.min_chunk_size, self.chunk_size)

    def _merge_text_with_overlap(self, left: str, right: str) -> str:
        if not left:
            return right
        if not right:
            return left
        max_overlap = min(len(left), len(right), max(0, int(self.chunk_overlap or 0)))
        if max_overlap <= 0:
            return left + right
        for size in range(max_overlap, 0, -1):
            if left.endswith(right[:size]):
                return left + right[size:]
        return left + right

    def _overlap_buffer_state(self, buffer: list[_Unit]) -> _BufferState:
        if self.chunk_overlap <= 0:
            return self._BufferState(units=[])

        keep: list[SemanticSentenceChunker._Unit] = []
        kept_len = 0
        for unit in reversed(buffer):
            keep.append(unit)
            kept_len += len(unit.text)
            if kept_len >= self.chunk_overlap:
                break
        return self._BufferState(units=list(reversed(keep)), length=kept_len)

    def _build_chunk_document(self, doc: Document, buffer: list[_Unit], effective_floor: int) -> Document:
        start_idx = buffer[0].start
        end_idx = buffer[-1].end
        meta = dict(doc.metadata or {})
        meta["start_char"] = start_idx
        meta["end_char"] = end_idx
        meta["chunk_strategy"] = "semantic_sentence"
        if effective_floor > 0:
            meta["min_chunk_size"] = effective_floor
        return Document(page_content="".join(unit.text for unit in buffer), metadata=meta)

    def _merge_small_tail_chunks(
        self,
        doc_chunks: list[Document],
        *,
        text: str,
        effective_floor: int,
    ) -> list[Document]:
        if effective_floor <= 0:
            return doc_chunks

        merged_chunks = list(doc_chunks)
        while len(merged_chunks) >= 2:
            tail = merged_chunks[-1]
            if len(tail.page_content or "") >= effective_floor:
                break
            prev = merged_chunks[-2]
            merged_meta = dict(prev.metadata or {})
            tail_meta = dict(tail.metadata or {})
            start_idx = int(merged_meta.get("start_char", 0) or 0)
            end_idx = int(tail_meta.get("end_char", merged_meta.get("end_char", start_idx)) or start_idx)
            merged_meta["end_char"] = end_idx
            merged_meta["chunk_strategy"] = "semantic_sentence"
            merged_meta["min_chunk_size"] = effective_floor
            merged_meta["min_chunk_floor_merged"] = True
            if 0 <= start_idx <= end_idx <= len(text):
                merged_content = text[start_idx:end_idx]
            else:
                merged_content = self._merge_text_with_overlap(prev.page_content or "", tail.page_content or "")
            merged_chunks[-2:] = [Document(page_content=merged_content, metadata=merged_meta)]
        return merged_chunks

    def _split_document(self, doc: Document, *, effective_floor: int) -> list[Document]:
        text = doc.page_content or ""
        units = self._build_units(text)
        if not units:
            return []

        doc_chunks: list[Document] = []
        buffer = self._BufferState(units=[])
        for unit in units:
            if not buffer.units:
                buffer.units = [unit]
                buffer.length = len(unit.text)
                continue

            would_overflow = buffer.length + len(unit.text) > self.chunk_size
            if would_overflow and not (effective_floor > 0 and buffer.length < effective_floor):
                doc_chunks.append(self._build_chunk_document(doc, buffer.units, effective_floor))
                buffer = self._overlap_buffer_state(buffer.units)

            if not buffer.units:
                buffer.units = [unit]
                buffer.length = len(unit.text)
                continue

            buffer.units.append(unit)
            buffer.length += len(unit.text)

        if buffer.units:
            doc_chunks.append(self._build_chunk_document(doc, buffer.units, effective_floor))
        return self._merge_small_tail_chunks(doc_chunks, text=text, effective_floor=effective_floor)

    def split_documents(self, documents: list[Document]) -> list[Document]:
        chunks: list[Document] = []
        effective_floor = self._effective_min_chunk_size()

        for doc in documents:
            chunks.extend(self._split_document(doc, effective_floor=effective_floor))

        return chunks
