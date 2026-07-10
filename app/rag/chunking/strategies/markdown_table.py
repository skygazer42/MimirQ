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


def _looks_like_align_row(line: str) -> bool:
    """
    Detect a Markdown table alignment row like:
      | --- | :---: | ---: |

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    s = str(line or "").strip()
    if not s or "|" not in s:
        return False
    inner = s
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    if "|" not in inner:
        return False
    cells = [c.strip() for c in inner.split("|")]
    if len(cells) < 2:
        return False
    for cell in cells:
        c = (cell or "").strip()
        if not c:
            return False
        if c.startswith(":"):
            c = c[1:].strip()
        if c.endswith(":"):
            c = c[:-1].strip()
        if len(c) < 3:
            return False
        if any(ch != "-" for ch in c):
            return False
    return True


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


def _build_blocks(text: str) -> list[_Block]:
    lines = _iter_lines(text)
    if not lines:
        return [_Block(start=0, end=len(text), kind="text")]

    blocks: list[_Block] = []
    i = 0
    cursor = 0
    while i < len(lines):
        if _is_table_start(lines, i):
            table_start = lines[i].start
            header_end = lines[i + 1].end

            # Flush preceding non-table text.
            if table_start > cursor:
                blocks.append(_Block(start=cursor, end=table_start, kind="text"))

            j = i + 2
            while j < len(lines):
                ln = lines[j].text.rstrip("\r\n")
                if not ln.strip():
                    break
                if "|" not in ln:
                    break
                j += 1

            table_end = lines[j].start if j < len(lines) else len(text)
            blocks.append(_Block(start=table_start, end=table_end, kind="table", header_end=header_end))

            cursor = table_end
            i = j
            continue

        i += 1

    if cursor < len(text):
        blocks.append(_Block(start=cursor, end=len(text), kind="text"))

    # Merge adjacent text blocks.
    merged: list[_Block] = []
    for b in blocks:
        if merged and b.kind == "text" and merged[-1].kind == "text" and merged[-1].end == b.start:
            prev = merged.pop()
            merged.append(_Block(start=prev.start, end=b.end, kind="text"))
        else:
            merged.append(b)
    return merged


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

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            blocks = _build_blocks(text)
            for block in blocks:
                block_text = text[block.start : block.end]
                if not block_text.strip():
                    continue

                if block.kind == "text":
                    split_docs = self._fallback_splitter.create_documents(texts=[block_text], metadatas=[base_meta])
                    for sd in split_docs:
                        local_start = sd.metadata.pop("start_index", None) or 0
                        abs_start = block.start + int(local_start)
                        abs_end = abs_start + len(sd.page_content)
                        meta: dict[str, Any] = dict(base_meta)
                        meta.update(sd.metadata or {})
                        meta["chunk_strategy"] = "markdown_table"
                        meta["start_char"] = abs_start
                        meta["end_char"] = abs_end
                        out.append(Document(page_content=sd.page_content, metadata=meta))
                    continue

                # Table block
                header_end = int(block.header_end or block.start)
                header_text = text[block.start:header_end]
                rows = _iter_table_rows(text, start=block.start, end=block.end, header_end=header_end)

                if not rows:
                    meta: dict[str, Any] = dict(base_meta)
                    meta["chunk_strategy"] = "markdown_table"
                    meta["start_char"] = block.start
                    meta["end_char"] = block.end
                    meta.setdefault("doc_type_kwd", "table")
                    meta["table_start_char"] = block.start
                    meta["table_end_char"] = block.end
                    if header_text.strip():
                        meta["table_header"] = header_text
                    out.append(Document(page_content=block_text, metadata=meta))
                    continue

                start_idx = 0
                first = True
                while start_idx < len(rows):
                    end_idx = start_idx
                    while end_idx < len(rows):
                        cand_start = block.start if first else rows[start_idx].start
                        cand_end = rows[end_idx].end
                        cand_len = cand_end - cand_start
                        if end_idx == start_idx or cand_len <= self.chunk_size:
                            end_idx += 1
                            continue
                        break

                    if end_idx == start_idx:
                        end_idx = start_idx + 1

                    chunk_start = block.start if first else rows[start_idx].start
                    chunk_end = rows[end_idx - 1].end
                    content = text[chunk_start:chunk_end]

                    meta: dict[str, Any] = dict(base_meta)
                    meta["chunk_strategy"] = "markdown_table"
                    meta["start_char"] = chunk_start
                    meta["end_char"] = chunk_end
                    meta.setdefault("doc_type_kwd", "table")
                    meta["table_start_char"] = block.start
                    meta["table_end_char"] = block.end
                    meta["table_row_count"] = int(end_idx - start_idx)
                    meta["table_row_start_index"] = int(start_idx)
                    meta["table_row_end_index"] = int(end_idx - 1)
                    if header_text.strip():
                        meta["table_header"] = header_text
                    out.append(Document(page_content=content, metadata=meta))

                    # Row-level overlap.
                    next_start = end_idx
                    if self.chunk_overlap > 0 and (end_idx - start_idx) > 1:
                        desired = end_idx - 1
                        while desired > start_idx:
                            overlap_len = rows[end_idx - 1].end - rows[desired - 1].start
                            if overlap_len <= self.chunk_overlap:
                                desired -= 1
                                continue
                            break
                        next_start = desired if desired > start_idx else (end_idx - 1)

                    if next_start <= start_idx:
                        next_start = end_idx
                    start_idx = next_start
                    first = False

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
