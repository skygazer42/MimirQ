"""
Policy/manual structured chunking strategy.

Goal:
- Detect policy/manual style headings (chapter/article/clause)
- Emit parent/child chunks with stable identifiers for clause-addressable retrieval

This is intentionally deterministic and conservative:
- No LLM calls
- Heuristics aim to avoid misclassifying generic outlines
"""


import hashlib
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.utils.heading_parsing import parse_cn_clause_marker, parse_cn_prefixed_heading


@dataclass(frozen=True)
class PolicyHeading:
    start: int
    end: int
    text: str
    level: int
    kind: str  # chapter|section|article|clause
    number: str | None = None


def _sha256_hex(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _stable_id24(text: str) -> str:
    return _sha256_hex(text)[:24]


def _iter_headings(text: str) -> list[PolicyHeading]:
    headings: list[PolicyHeading] = []
    if not text:
        return headings

    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)

        line = raw_line.strip()
        if not line:
            continue
        # Avoid absurdly long "lines" being misdetected as headings.
        if len(line) > 240:
            continue

        kind: str | None = None
        level: int | None = None
        num: str | None = None

        if (prefix := parse_cn_prefixed_heading(line, suffixes="章")) is not None:
            kind, level, num = "chapter", 1, prefix
        elif (prefix := parse_cn_prefixed_heading(line, suffixes="节")) is not None:
            kind, level, num = "section", 2, prefix
        elif (prefix := parse_cn_prefixed_heading(line, suffixes="条")) is not None:
            kind, level, num = "article", 3, prefix
        elif (prefix := parse_cn_clause_marker(line)) is not None:
            kind, level, num = "clause", 4, prefix

        if kind is None or level is None:
            continue

        headings.append(
            PolicyHeading(
                start=line_start,
                end=line_start + len(raw_line),
                text=line,
                level=int(level),
                kind=kind,
                number=num,
            )
        )

    return headings


def _update_heading_stack(stack: list[PolicyHeading], *, heading: PolicyHeading) -> None:
    while stack and stack[-1].level >= heading.level:
        stack.pop()
    stack.append(heading)


def looks_like_policy_manual(text: str) -> bool:
    """
    Heuristic detection for policy/manual style documents.

    We require multiple article markers, and at least one extra signal
    (chapter/clause marker, or bracketed titles) to avoid matching generic outlines.
    """
    raw = (text or "").strip()
    if not raw:
        return False

    headings = _iter_headings(raw)
    if not headings:
        return False

    articles = [h for h in headings if h.kind == "article"]
    if len(articles) < 2:
        return False

    chapters = any(h.kind == "chapter" for h in headings)
    clauses = any(h.kind == "clause" for h in headings)
    bracket_titles = "【" in raw and "】" in raw

    # Short texts can still be policy-like if they clearly use the format.
    return bool(chapters or clauses or bracket_titles or len(raw) >= 400)


def _resolve_document_id(base_meta: dict[str, Any]) -> str:
    doc_id = str(base_meta.get("document_id") or "").strip()
    if doc_id:
        return doc_id
    return str(base_meta.get("source") or "").strip() or "unknown"


def _article_headings(headings: list[PolicyHeading]) -> list[PolicyHeading]:
    article_heads = [heading for heading in headings if heading.kind == "article"]
    if article_heads:
        return article_heads
    return [PolicyHeading(start=0, end=0, text="(document)", level=3, kind="article", number="document")]


def _policy_paths_by_article_start(headings: list[PolicyHeading]) -> dict[int, list[str]]:
    stack: list[PolicyHeading] = []
    path_by_article_start: dict[int, list[str]] = {}
    for heading in headings:
        _update_heading_stack(stack, heading=heading)
        if heading.kind == "article":
            path_by_article_start[heading.start] = [item.text for item in stack]
    return path_by_article_start


class PolicyManualStructuredChunker(BaseChunker):
    """
    Structured chunker for policy/manual documents.

    Emits both:
    - parent chunks (per-article, stable parent_id)
    - child chunks (bounded by chunk_size, with parent_id reference)
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "；", "，", ". ", "!", "?", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def _append_article_chunks(
        self,
        out: list[Document],
        *,
        sec_text: str,
        sec_start: int,
        sec_end: int,
        base_meta: dict[str, Any],
        doc_id: str,
        article_number: str,
        path: list[str],
    ) -> None:
        parent_id = _stable_id24(f"{doc_id}:{article_number}")
        path_str = " / ".join(path)
        parent_content_hash = _sha256_hex(sec_text)
        parent_clause_id = _stable_id24(f"{doc_id}:{article_number}:{parent_content_hash}")
        parent_meta: dict[str, Any] = dict(base_meta)
        parent_meta.update(
            {
                "chunk_strategy": "policy_manual_structured",
                "chunk_role": "parent",
                "parent_id": parent_id,
                "start_char": sec_start,
                "end_char": sec_end,
                "policy_clause_id": parent_clause_id,
                "policy_clause_number": article_number,
                "policy_path": list(path),
                "policy_path_str": path_str,
            }
        )
        out.append(Document(page_content=sec_text, metadata=parent_meta))

        split_docs = self._child_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
        for sd in split_docs:
            sd_meta = dict(sd.metadata or {})
            local_start = sd_meta.pop("start_index", None) or 0
            abs_start = sec_start + int(local_start)
            abs_end = abs_start + len(sd.page_content)
            child_content = sd.page_content or ""
            child_content_hash = _sha256_hex(child_content)
            child_clause_id = _stable_id24(f"{doc_id}:{article_number}:{child_content_hash}")

            meta: dict[str, Any] = dict(base_meta)
            meta.update(sd_meta)
            meta.update(
                {
                    "chunk_strategy": "policy_manual_structured",
                    "chunk_role": "child",
                    "parent_id": parent_id,
                    "start_char": abs_start,
                    "end_char": abs_end,
                    "policy_clause_id": child_clause_id,
                    "policy_clause_number": article_number,
                    "policy_path": list(path),
                    "policy_path_str": path_str,
                }
            )
            out.append(Document(page_content=child_content, metadata=meta))

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            doc_id = _resolve_document_id(base_meta)
            headings = _iter_headings(text)
            article_heads = _article_headings(headings)
            path_by_article_start = _policy_paths_by_article_start(headings)

            preamble = text[: article_heads[0].start]
            first_start = 0 if preamble.strip() else article_heads[0].start

            for idx, heading in enumerate(article_heads):
                sec_start = first_start if idx == 0 else heading.start
                sec_end = article_heads[idx + 1].start if idx + 1 < len(article_heads) else len(text)
                sec_text = text[sec_start:sec_end]
                if not sec_text.strip():
                    continue

                article_number = str(heading.number or "").strip() or f"article_{idx + 1}"
                path = path_by_article_start.get(heading.start) or ([heading.text] if heading.text else [])
                if not path:
                    path = [article_number]
                self._append_article_chunks(
                    out,
                    sec_text=sec_text,
                    sec_start=sec_start,
                    sec_end=sec_end,
                    base_meta=base_meta,
                    doc_id=doc_id,
                    article_number=article_number,
                    path=path,
                )

        # Add a stable chunk_index within this output list for convenience/debugging.
        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta.setdefault("chunk_index", idx)
            chunk.metadata = meta

        return out
