"""
GraphQL schema aware chunking strategy.

Targets .graphql/.gql schema files and splits by top-level definitions such as:
- type / input / enum / interface / union / scalar / directive / schema

Offsets are preserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Def:
    start: int
    end: int
    kind: str
    name: str | None
    index: int


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    definition: _Def | None


_KINDS = frozenset({"type", "input", "enum", "interface", "union", "scalar", "directive", "schema"})


def _take_name_token(text: str) -> str | None:
    s = str(text or "").lstrip()
    if not s:
        return None
    first = s[0]
    if not (first.isalpha() or first == "_"):
        return None
    i = 1
    while i < len(s) and (s[i].isalnum() or s[i] == "_"):
        i += 1
    return s[:i] if i > 0 else None


def _parse_def_line(line: str) -> tuple[str, str | None] | None:
    """
    Parse a top-level GraphQL definition line.

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    raw = str(line or "").strip()
    if not raw or raw.startswith("#"):
        return None

    parts = raw.split(None, 1)
    if not parts:
        return None
    first = parts[0].casefold()
    rest = parts[1] if len(parts) > 1 else ""

    if first == "extend":
        parts2 = rest.strip().split(None, 1)
        if not parts2:
            return None
        first = parts2[0].casefold()
        rest = parts2[1] if len(parts2) > 1 else ""

    kind = first
    if kind not in _KINDS:
        return None

    name: str | None = None
    if kind in {"type", "input", "enum", "interface", "union", "scalar"}:
        name = _take_name_token(rest)
    elif kind == "directive":
        at = rest.find("@")
        if at >= 0:
            name = _take_name_token(rest[at + 1 :])
    return kind, (name or None)


def _iter_defs(text: str) -> list[_Def]:
    defs: list[_Def] = []
    offset = 0
    for raw_line in (text or "").splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)
        plain = raw_line.rstrip("\r\n")
        parsed = _parse_def_line(plain)
        if not parsed:
            continue
        kind, name = parsed
        defs.append(
            _Def(
                start=int(line_start),
                end=int(line_start + len(raw_line)),
                kind=str(kind),
                name=name,
                index=len(defs),
            )
        )

    deduped: list[_Def] = []
    last_start = -1
    for d in defs:
        if d.start == last_start:
            continue
        deduped.append(d)
        last_start = d.start
    return deduped


def _build_sections(text: str, defs: list[_Def]) -> list[_Section]:
    if not defs:
        return [_Section(start=0, end=len(text), definition=None)]

    sections: list[_Section] = []
    first = defs[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, definition=None))
    for idx, d in enumerate(defs):
        start = d.start
        end = defs[idx + 1].start if idx + 1 < len(defs) else len(text)
        sections.append(_Section(start=start, end=end, definition=d))
    return sections


def looks_like_graphql_schema(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    defs = _iter_defs(text)
    if len(defs) >= 3:
        return True
    # Heuristic: at least 2 defs + GraphQL-ish punctuation.
    if len(defs) >= 2 and ("type " in (text or "").lower() or "schema {" in (text or "").lower()):
        return True
    return False


class GraphQLSchemaChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "}", " ", ""],
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

            defs = _iter_defs(text)
            sections = _build_sections(text, defs)

            current: _Def | None = None
            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue
                if section.definition is not None:
                    current = section.definition

                split_docs = self._fallback_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "graphql_schema"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "graphql")
                    if current is not None:
                        meta["graphql_kind"] = current.kind
                        if current.name:
                            meta["graphql_name"] = current.name

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
