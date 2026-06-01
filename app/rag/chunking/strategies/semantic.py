"""
Semantic sentence-based chunking strategy.

Splits text at sentence boundaries, then aggregates
sentences into chunks of the target size.
"""

import re
from dataclasses import dataclass

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker
from app.rag.core.logging import get_logger

logger = get_logger(__name__)


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

    def _extract_list_item_spans(self, text: str, *, blocked: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """
        Best-effort list item span extraction (supports markdown-ish bullets and indented continuations).

        This intentionally ignores list items inside fenced code blocks.
        """
        raw = text or ""
        spans: list[tuple[int, int]] = []

        lines = raw.splitlines(keepends=True)
        if not lines:
            return spans

        # Pre-compute per-line absolute offsets.
        offsets: list[int] = []
        pos = 0
        for ln in lines:
            offsets.append(pos)
            pos += len(ln)

        def is_item_start(line: str) -> bool:
            return bool(self._LIST_ITEM_RE.match(line or ""))

        def is_continuation(line: str) -> bool:
            if not line:
                return False
            if line.strip() == "":
                return True
            return bool(re.match(r"^\s{2,}\S", line))

        idx = 0
        while idx < len(lines):
            line = lines[idx]
            start_off = offsets[idx]
            if not is_item_start(line) or self._in_any_span(start_off, blocked):
                idx += 1
                continue

            start = start_off
            idx += 1

            while idx < len(lines):
                nxt = lines[idx]
                nxt_off = offsets[idx]
                if self._in_any_span(nxt_off, blocked):
                    break
                if is_item_start(nxt):
                    break
                if nxt.strip() == "":
                    # Keep blank line only if the next non-empty line is indented (still part of item).
                    j = idx + 1
                    while j < len(lines) and lines[j].strip() == "":
                        j += 1
                    if j < len(lines) and is_continuation(lines[j]):
                        idx += 1
                        continue
                    break
                if is_continuation(nxt):
                    idx += 1
                    continue
                break

            end = offsets[idx] if idx < len(offsets) else len(raw)
            if end > start:
                spans.append((start, end))

        spans.sort(key=lambda x: x[0])
        return spans

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

        def merge_numeric_dot_runs(local_units: list[SemanticSentenceChunker._Unit]) -> list[SemanticSentenceChunker._Unit]:
            """
            Merge units that were split at a '.' inside numeric runs (e.g. 3.14, v1.2.3).

            Without this, small chunk sizes can split a decimal across chunk boundaries:
            "3." and "14 ..." which harms retrieval.
            """
            if not local_units:
                return local_units

            merged: list[SemanticSentenceChunker._Unit] = []
            i = 0
            while i < len(local_units):
                cur = local_units[i]
                if (
                    merged
                    and merged[-1].kind == "text"
                    and cur.kind == "text"
                ):
                    prev = merged[-1]
                    try:
                        if (
                            prev.end < len(raw)
                            and raw[prev.end - 1 : prev.end] == "."
                            and prev.end - 2 >= 0
                            and raw[prev.end - 2].isdigit()
                            and raw[prev.end].isdigit()
                        ):
                            # Merge prev + cur into a single unit covering the raw substring.
                            start = prev.start
                            end = cur.end
                            merged[-1] = self._Unit(text=raw[start:end], start=start, end=end, kind="text")
                            i += 1
                            continue
                    except Exception as exc:
                        logger.debug("Ignoring semantic chunk numeric-run merge failure: %s", exc)

                merged.append(cur)
                i += 1

            return merged

        def add_text_units(seg_start: int, seg_end: int) -> None:
            seg = raw[seg_start:seg_end]
            if not seg:
                return
            local: list[SemanticSentenceChunker._Unit] = []
            for m in self.SENTENCE_PATTERN.finditer(seg):
                s = seg_start + int(m.start())
                e = seg_start + int(m.end())
                if e <= s:
                    continue
                local.append(self._Unit(text=raw[s:e], start=s, end=e, kind="text"))
            units.extend(merge_numeric_dot_runs(local))

        for s, e, kind in spans:
            if e <= s:
                continue
            if s > cursor:
                add_text_units(cursor, s)
            units.append(self._Unit(text=raw[s:e], start=s, end=e, kind=kind))
            cursor = max(cursor, e)

        if cursor < len(raw):
            add_text_units(cursor, len(raw))

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

    def split_documents(self, documents: list[Document]) -> list[Document]:
        chunks: list[Document] = []
        effective_floor = self._effective_min_chunk_size()

        for doc in documents:
            text = doc.page_content or ""
            units = self._build_units(text)
            if not units:
                continue

            buffer: list[SemanticSentenceChunker._Unit] = []
            buffer_len = 0

            def flush() -> None:
                nonlocal buffer, buffer_len
                if not buffer:
                    return
                start_idx = buffer[0].start
                end_idx = buffer[-1].end
                payload = "".join(u.text for u in buffer)
                meta = dict(doc.metadata or {})
                meta["start_char"] = start_idx
                meta["end_char"] = end_idx
                meta["chunk_strategy"] = "semantic_sentence"
                if effective_floor > 0:
                    meta["min_chunk_size"] = effective_floor
                chunks.append(Document(page_content=payload, metadata=meta))

                # Overlap by unit boundaries (avoid cutting inside list/code blocks).
                if self.chunk_overlap <= 0:
                    buffer = []
                    buffer_len = 0
                    return

                keep: list[SemanticSentenceChunker._Unit] = []
                kept_len = 0
                for u in reversed(buffer):
                    keep.append(u)
                    kept_len += len(u.text)
                    if kept_len >= self.chunk_overlap:
                        break
                buffer = list(reversed(keep))
                buffer_len = kept_len

            for u in units:
                if not buffer:
                    buffer = [u]
                    buffer_len = len(u.text)
                    continue

                if buffer_len + len(u.text) > self.chunk_size:
                    if effective_floor > 0 and buffer_len < effective_floor:
                        buffer.append(u)
                        buffer_len += len(u.text)
                        continue
                    flush()
                    if not buffer:
                        buffer = [u]
                        buffer_len = len(u.text)
                        continue

                buffer.append(u)
                buffer_len += len(u.text)

            flush()

            while effective_floor > 0 and len(chunks) >= 2:
                tail = chunks[-1]
                if len(tail.page_content or "") >= effective_floor:
                    break
                prev = chunks[-2]
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
                merged_doc = Document(
                    page_content=merged_content,
                    metadata=merged_meta,
                )
                chunks[-2:] = [merged_doc]

        return chunks
