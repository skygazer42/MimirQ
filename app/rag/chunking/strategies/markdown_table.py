"""
Markdown table-aware chunking strategy.

This chunker detects Markdown table blocks and avoids splitting inside a row.
For large tables, it splits at row boundaries (while keeping each chunk a
substring of the original text so highlight offsets remain valid).

Non-table text is chunked with a fallback RecursiveCharacterTextSplitter.
"""


from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class _Block:
    start: int
    end: int
    kind: str  # "text" | "table"
    header_end: int | None = None  # for table blocks


@dataclass(frozen=True)
class _Span:
    start: int
    end: int


def _trim_table_edges(line: str) -> str:
    inner = str(line or "").strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return inner


def _is_alignment_cell(cell: str) -> bool:
    text = (cell or "").strip().strip(":").strip()
    return len(text) >= 3 and all(ch == "-" for ch in text)


def _looks_like_align_row(line: str) -> bool:
    """
    Detect a Markdown table alignment row like:
      | --- | :---: | ---: |

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    s = str(line or "").strip()
    if not s or "|" not in s:
        return False
    inner = _trim_table_edges(s)
    if "|" not in inner:
        return False
    cells = [c.strip() for c in inner.split("|")]
    return len(cells) >= 2 and all(_is_alignment_cell(cell) for cell in cells)


def _is_table_start(lines: list[_Line], i: int) -> bool:
    if i + 1 >= len(lines):
        return False
    a = lines[i].text.rstrip("\r\n")
    b = lines[i + 1].text.rstrip("\r\n")
    if "|" not in a or "|" not in b:
        return False
    return _looks_like_align_row(b)


def _iter_lines(text: str) -> list[_Line]:
    out: list[_Line] = []
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        start = offset
        end = start + len(raw)
        offset = end
        out.append(_Line(start=start, end=end, text=raw))
    if not out and text:
        out.append(_Line(start=0, end=len(text), text=text))
    return out


def _is_table_body_line(line: _Line) -> bool:
    text = line.text.rstrip("\r\n")
    return bool(text.strip()) and "|" in text


def _merge_adjacent_text_blocks(blocks: list[_Block]) -> list[_Block]:
    merged: list[_Block] = []
    for block in blocks:
        if merged and block.kind == "text" and merged[-1].kind == "text" and merged[-1].end == block.start:
            prev = merged.pop()
            merged.append(_Block(start=prev.start, end=block.end, kind="text"))
            continue
        merged.append(block)
    return merged


def _scan_table_block(lines: list[_Line], start_idx: int, text: str) -> tuple[_Block, int]:
    table_start = lines[start_idx].start
    header_end = lines[start_idx + 1].end
    end_idx = start_idx + 2
    while end_idx < len(lines) and _is_table_body_line(lines[end_idx]):
        end_idx += 1
    table_end = lines[end_idx].start if end_idx < len(lines) else len(text)
    return _Block(start=table_start, end=table_end, kind="table", header_end=header_end), end_idx


def _build_blocks(text: str) -> list[_Block]:
    lines = _iter_lines(text)
    if not lines:
        return [_Block(start=0, end=len(text), kind="text")]

    blocks: list[_Block] = []
    i = 0
    cursor = 0
    while i < len(lines):
        if not _is_table_start(lines, i):
            i += 1
            continue

        table_block, next_idx = _scan_table_block(lines, i, text)
        if table_block.start > cursor:
            blocks.append(_Block(start=cursor, end=table_block.start, kind="text"))
        blocks.append(table_block)
        cursor = table_block.end
        i = next_idx

    if cursor < len(text):
        blocks.append(_Block(start=cursor, end=len(text), kind="text"))
    return _merge_adjacent_text_blocks(blocks)


def looks_like_markdown_table(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    blocks = _build_blocks(text)
    return any(b.kind == "table" for b in blocks)


def _iter_table_rows(text: str, *, start: int, end: int, header_end: int) -> list[_Span]:
    # Rows are any non-empty lines after the alignment row.
    _ = start
    body = text[header_end:end]
    if not body:
        return []

    rows: list[_Span] = []
    offset = header_end
    for raw in body.splitlines(keepends=True):
        line_start = offset
        offset += len(raw)
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        if "|" not in line:
            continue
        rows.append(_Span(start=line_start, end=line_start + len(raw)))
    return rows


class MarkdownTableChunker(BaseChunker):
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

    def _build_text_chunk(self, base_meta: dict[str, Any], block: _Block, split_doc: Document) -> Document:
        local_start = split_doc.metadata.pop("start_index", None) or 0
        abs_start = block.start + int(local_start)
        abs_end = abs_start + len(split_doc.page_content)
        meta: dict[str, Any] = dict(base_meta)
        meta.update(split_doc.metadata or {})
        meta["chunk_strategy"] = "markdown_table"
        meta["start_char"] = abs_start
        meta["end_char"] = abs_end
        return Document(page_content=split_doc.page_content, metadata=meta)

    def _table_meta(
        self,
        base_meta: dict[str, Any],
        *,
        chunk_start: int,
        chunk_end: int,
        table_start: int,
        table_end: int,
        header_text: str,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = dict(base_meta)
        meta["chunk_strategy"] = "markdown_table"
        meta["start_char"] = chunk_start
        meta["end_char"] = chunk_end
        meta.setdefault("doc_type_kwd", "table")
        meta["table_start_char"] = table_start
        meta["table_end_char"] = table_end
        if header_text.strip():
            meta["table_header"] = header_text
        return meta

    def _fit_table_rows(
        self,
        block: _Block,
        rows: list[_Span],
        *,
        start_idx: int,
        first_chunk: bool,
    ) -> tuple[int, int, int]:
        end_idx = start_idx
        while end_idx < len(rows):
            cand_start = block.start if first_chunk else rows[start_idx].start
            cand_end = rows[end_idx].end
            cand_len = cand_end - cand_start
            if end_idx == start_idx or cand_len <= self.chunk_size:
                end_idx += 1
                continue
            break
        if end_idx == start_idx:
            end_idx += 1
        chunk_start = block.start if first_chunk else rows[start_idx].start
        chunk_end = rows[end_idx - 1].end
        return end_idx, chunk_start, chunk_end

    def _next_table_row_start(self, rows: list[_Span], *, start_idx: int, end_idx: int) -> int:
        if self.chunk_overlap <= 0 or (end_idx - start_idx) <= 1:
            return end_idx

        desired = end_idx - 1
        while desired > start_idx:
            overlap_len = rows[end_idx - 1].end - rows[desired - 1].start
            if overlap_len <= self.chunk_overlap:
                desired -= 1
                continue
            break
        return desired if desired > start_idx else (end_idx - 1)

    def _split_text_block(self, block_text: str, base_meta: dict[str, Any], block: _Block) -> list[Document]:
        split_docs = self._fallback_splitter.create_documents(texts=[block_text], metadatas=[base_meta])
        return [self._build_text_chunk(base_meta, block, split_doc) for split_doc in split_docs]

    def _split_table_block(self, text: str, base_meta: dict[str, Any], block: _Block) -> list[Document]:
        header_end = int(block.header_end or block.start)
        header_text = text[block.start:header_end]
        rows = _iter_table_rows(text, start=block.start, end=block.end, header_end=header_end)
        if not rows:
            meta = self._table_meta(
                base_meta,
                chunk_start=block.start,
                chunk_end=block.end,
                table_start=block.start,
                table_end=block.end,
                header_text=header_text,
            )
            return [Document(page_content=text[block.start : block.end], metadata=meta)]

        chunks: list[Document] = []
        start_idx = 0
        first_chunk = True
        while start_idx < len(rows):
            end_idx, chunk_start, chunk_end = self._fit_table_rows(
                block,
                rows,
                start_idx=start_idx,
                first_chunk=first_chunk,
            )
            meta = self._table_meta(
                base_meta,
                chunk_start=chunk_start,
                chunk_end=chunk_end,
                table_start=block.start,
                table_end=block.end,
                header_text=header_text,
            )
            meta["table_row_count"] = int(end_idx - start_idx)
            meta["table_row_start_index"] = int(start_idx)
            meta["table_row_end_index"] = int(end_idx - 1)
            chunks.append(Document(page_content=text[chunk_start:chunk_end], metadata=meta))

            next_start = self._next_table_row_start(rows, start_idx=start_idx, end_idx=end_idx)
            start_idx = end_idx if next_start <= start_idx else next_start
            first_chunk = False
        return chunks

    def _split_document(self, doc: Document) -> list[Document]:
        text = doc.page_content or ""
        if not text.strip():
            return []

        base_meta = dict(doc.metadata or {})
        chunks: list[Document] = []
        for block in _build_blocks(text):
            block_text = text[block.start : block.end]
            if not block_text.strip():
                continue
            if block.kind == "text":
                chunks.extend(self._split_text_block(block_text, base_meta, block))
                continue
            chunks.extend(self._split_table_block(text, base_meta, block))
        return chunks

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            out.extend(self._split_document(doc))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
