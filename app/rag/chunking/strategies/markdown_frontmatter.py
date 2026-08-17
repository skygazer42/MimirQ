"""
Markdown frontmatter aware chunking strategy.

Targets Markdown documents that start with YAML frontmatter (--- ... ---).
The chunker keeps the frontmatter as its own chunk(s), then chunks the body
using markdown-friendly separators while preserving character offsets.
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
    plain: str


_FRONTMATTER_DELIM = "---"


def _is_frontmatter_end_delim(line: str) -> bool:
    s = str(line or "").strip()
    return s in {"---", "..."}


def _looks_like_yaml_kv_line(line: str) -> bool:
    s = str(line or "").strip()
    if not s or s.startswith("#") or ":" not in s:
        return False
    key, rest = s.split(":", 1)
    key = key.strip()
    if not key or len(key) > 80:
        return False
    if not all(ch.isascii() and (ch.isalnum() or ch in "_.-") for ch in key):
        return False
    return bool(rest.strip())


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


def _find_frontmatter(text: str) -> tuple[int, int] | None:
    if not text:
        return None
    lines = _iter_lines(text)
    if not lines:
        return None

    first_plain = lines[0].plain.lstrip("\ufeff").strip()
    if first_plain != _FRONTMATTER_DELIM:
        return None

    for i in range(1, len(lines)):
        plain = lines[i].plain.strip()
        if _is_frontmatter_end_delim(plain):
            return 0, lines[i].end
    return None


def _extract_title(frontmatter: str) -> str | None:
    for ln in (frontmatter or "").splitlines():
        s = ln.strip()
        if not s or ":" not in s:
            continue
        key, rest = s.split(":", 1)
        if key.strip().casefold() != "title":
            continue
        val = rest.strip().strip("'\"")
        return val[:200] or None
    return None


def looks_like_markdown_frontmatter(text: str) -> bool:
    fm = _find_frontmatter(text)
    if not fm:
        return False
    start, end = fm
    block = (text or "")[start:end]
    if len(block) > 30000:
        return False
    # Require at least one key-value line inside the block.
    for ln in block.splitlines()[:400]:
        if _looks_like_yaml_kv_line(ln):
            return True
    return False


class MarkdownFrontmatterChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._frontmatter_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=0,
            separators=["\n", " ", ""],
            length_function=len,
            add_start_index=True,
        )

        separators: list[str] = []
        for i in range(1, 7):
            separators.append("\n" + "#" * i + " ")
        separators.extend(["\n\n", "\n", ". ", "。", "？", "！", " ", ""])

        self._body_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=separators,
            length_function=len,
            add_start_index=True,
        )

    def _append_chunks(
        self,
        out: list[Document],
        *,
        splitter: RecursiveCharacterTextSplitter,
        text: str,
        base_meta: dict[str, Any],
        offset: int,
        extra_meta: dict[str, Any],
        doc_type_kwd: str | None = None,
    ) -> None:
        split_docs = splitter.create_documents(texts=[text], metadatas=[base_meta])
        for sd in split_docs:
            local_start = sd.metadata.pop("start_index", None) or 0
            abs_start = offset + int(local_start)
            abs_end = abs_start + len(sd.page_content)
            meta: dict[str, Any] = dict(base_meta)
            meta.update(sd.metadata or {})
            meta["chunk_strategy"] = "markdown_frontmatter"
            meta["start_char"] = abs_start
            meta["end_char"] = abs_end
            if doc_type_kwd:
                meta.setdefault("doc_type_kwd", doc_type_kwd)
            meta.update(extra_meta)
            out.append(Document(page_content=sd.page_content, metadata=meta))

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            fm = _find_frontmatter(text)
            if not fm:
                self._append_chunks(
                    out,
                    splitter=self._body_splitter,
                    text=text,
                    base_meta=base_meta,
                    offset=0,
                    extra_meta={"markdown_frontmatter_fallback": True},
                    doc_type_kwd="markdown",
                )
                continue

            fm_start, fm_end = fm
            fm_text = text[fm_start:fm_end]
            title = _extract_title(fm_text)
            frontmatter_meta: dict[str, Any] = {
                "markdown_frontmatter": True,
                "frontmatter_end_char": int(fm_end),
            }
            if title:
                frontmatter_meta["frontmatter_title"] = title
            self._append_chunks(
                out,
                splitter=self._frontmatter_splitter,
                text=fm_text,
                base_meta=base_meta,
                offset=fm_start,
                extra_meta=frontmatter_meta,
                doc_type_kwd="markdown",
            )

            body_text = text[fm_end:]
            if body_text.strip():
                body_meta: dict[str, Any] = {
                    "frontmatter_present": True,
                    "frontmatter_end_char": int(fm_end),
                }
                if title:
                    body_meta["frontmatter_title"] = title
                self._append_chunks(
                    out,
                    splitter=self._body_splitter,
                    text=body_text,
                    base_meta=base_meta,
                    offset=fm_end,
                    extra_meta=body_meta,
                    doc_type_kwd="markdown",
                )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
