"""
SQL schema / DDL aware chunking strategy.

Targets SQL scripts dominated by DDL statements such as:
- CREATE TABLE ...
- CREATE VIEW ...
- ALTER TABLE ...
- CREATE FUNCTION/PROCEDURE/TRIGGER/INDEX ...

The chunker splits the document into statement blocks first, then applies a
fallback RecursiveCharacterTextSplitter inside each block while preserving
character offsets.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class SqlStmt:
    start: int
    end: int
    stmt_type: str
    object_name: str | None


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    stmt: SqlStmt | None


_CREATE_REPLACE_STMT_START_RE = re.compile(
    r"(?im)^\s*(?P<kw>create\s+or\s+replace\s+(?:table|view|function|procedure|trigger|index))\b"
)
_CREATE_STMT_START_RE = re.compile(r"(?im)^\s*(?P<kw>create\s+(?:table|view|function|procedure|trigger|index))\b")
_ALTER_STMT_START_RE = re.compile(r"(?im)^\s*(?P<kw>alter\s+table)\b")
_SEMICOLON_EOS_RE = re.compile(r"(?m);[ \t]*(?:--.*)?$")
_OBJ_NAME_RE = re.compile(
    r"(?im)^\s*create\s+(?:or\s+replace\s+)?(?P<kind>table|view|function|procedure|trigger|index)\s+"
    r"(?:if\s+not\s+exists\s+)?(?P<name>[`\"\\[]?[A-Z0-9_.$]+[`\"\\]]?(?:\.[`\"\\[]?[A-Z0-9_.$]+[`\"\\]]?)?)"
)
_ALTER_NAME_RE = re.compile(
    r"(?im)^\s*alter\s+table\s+(?:if\s+exists\s+)?(?P<name>[^\s(]+)"
)


def _infer_object_name(stmt_text: str) -> tuple[str, str | None]:
    if not stmt_text:
        return "sql", None
    m = _OBJ_NAME_RE.search(stmt_text[:2000])
    if m:
        kind = (m.group("kind") or "create").strip().lower()
        name = (m.group("name") or "").strip() or None
        return kind, name
    m = _ALTER_NAME_RE.search(stmt_text[:2000])
    if m:
        name = (m.group("name") or "").strip() or None
        return "alter_table", name
    head = stmt_text.strip().splitlines()[:1]
    head_str = head[0] if head else ""
    return (head_str[:40].strip().lower() or "sql"), None


def _find_stmt_end(text: str, *, start: int, next_start: int) -> int:
    if next_start <= start:
        return next_start
    window = text[start:next_start]
    last = None
    for m in _SEMICOLON_EOS_RE.finditer(window):
        last = m
    if last is None:
        return next_start
    end = start + last.end()
    # Include a trailing newline after semicolon if present.
    if end < len(text) and text[end : end + 1] == "\n":
        end += 1
    return min(end, next_start)


def _iter_statements(text: str) -> list[SqlStmt]:
    if not text:
        return []

    starts = []
    for pat in (_CREATE_REPLACE_STMT_START_RE, _CREATE_STMT_START_RE, _ALTER_STMT_START_RE):
        starts.extend(m.start() for m in pat.finditer(text))
    if not starts:
        return []

    starts = sorted(set(starts))
    stmts: list[SqlStmt] = []
    for idx, start in enumerate(starts):
        next_start = starts[idx + 1] if idx + 1 < len(starts) else len(text)
        end = _find_stmt_end(text, start=start, next_start=next_start)
        stmt_text = text[start:end]
        stmt_type, obj_name = _infer_object_name(stmt_text)
        stmts.append(SqlStmt(start=start, end=end, stmt_type=stmt_type, object_name=obj_name))
    return stmts


def _build_sections(text: str, stmts: list[SqlStmt]) -> list[_Section]:
    if not stmts:
        return [_Section(start=0, end=len(text), stmt=None)]

    sections: list[_Section] = []
    first = stmts[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, stmt=None))
    for idx, st in enumerate(stmts):
        start = st.start
        end = stmts[idx + 1].start if idx + 1 < len(stmts) else len(text)
        end = max(end, st.end)
        sections.append(_Section(start=start, end=end, stmt=st))
    return sections


def looks_like_sql_schema(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    head = text[:8000]
    hits = 0
    for pat in (_CREATE_REPLACE_STMT_START_RE, _CREATE_STMT_START_RE, _ALTER_STMT_START_RE):
        hits += len(pat.findall(head))
    if hits >= 2:
        return True
    if hits == 1 and ("create table" in head.lower() or "alter table" in head.lower()):
        return True
    return False


class SqlSchemaChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ";", " ", ""],
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

            stmts = _iter_statements(text)
            sections = _build_sections(text, stmts)

            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                split_docs = self._fallback_splitter.create_documents(
                    texts=[sec_text],
                    metadatas=[base_meta],
                )
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "sql_schema"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "sql")

                    if section.stmt is not None:
                        meta["sql_stmt_type"] = section.stmt.stmt_type
                        if section.stmt.object_name:
                            meta["sql_object"] = section.stmt.object_name

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
