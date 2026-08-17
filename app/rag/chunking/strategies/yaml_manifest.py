"""
YAML manifest / multi-document aware chunking strategy.

Targets YAML text (including Kubernetes manifests) with patterns like:
- apiVersion: v1
- kind: Deployment
- metadata:
    name: ...
- --- document separators

The chunker splits the text into YAML documents first, then applies a fallback
RecursiveCharacterTextSplitter inside each document while preserving offsets.
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
    text: str
    plain: str


@dataclass(frozen=True)
class _Doc:
    start: int
    end: int
    index: int
    kind: str | None
    name: str | None
    api_version: str | None


@dataclass(frozen=True)
class _YamlSignalStats:
    key_with_value: int
    key_only: int
    indented: int
    list_items: int
    total_lines: int


_DOC_SEP_RE = re.compile(r"(?m)^\s*---\s*(?:#.*)?$")
_KEY_ONLY_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_.-]{0,80})\s*:\s*(?:#.*)?$")
_INDENTED_KEY_RE = re.compile(r"^\s{2,}[A-Za-z_][A-Za-z0-9_.-]{0,80}\s*:\s*")
_LIST_ITEM_RE = re.compile(r"^\s*-\s+\S+")
_API_VERSION_RE = re.compile(r"(?m)^\s*apiVersion\s*:\s*(?P<val>[^\s#]+)")
_KIND_RE = re.compile(r"(?m)^\s*kind\s*:\s*(?P<val>[^\s#]+)")
_METADATA_RE = re.compile(r"^(?P<indent>\s*)metadata\s*:\s*(?:#.*)?$")
_NAME_RE = re.compile(r"^(?P<indent>\s*)name\s*:\s*(?P<val>[^\s#]+)")


def _parse_yaml_kv_line(line: str) -> tuple[str, str] | None:
    """
    Parse a simple YAML key/value line like:
      apiVersion: v1
      kind: Deployment

    Returns (key, value) or None.

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    s = str(line or "").strip()
    if not s or s.startswith("#") or ":" not in s:
        return None
    key_raw, rest = s.split(":", 1)
    key = key_raw.strip()
    if not key or len(key) > 81:
        return None
    first = key[0]
    if not (first.isascii() and (first.isalpha() or first == "_")):
        return None
    for ch in key[1:]:
        if not ch.isascii():
            return None
        if ch.isalnum() or ch in "_.-":
            continue
        return None
    val = rest.strip()
    if not val or val.startswith("#"):
        return None
    if " #" in val:
        val = val.split(" #", 1)[0].strip()
    return key, val


def _iter_lines(text: str) -> list[_Line]:
    out: list[_Line] = []
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        start = offset
        end = start + len(raw)
        offset = end
        out.append(_Line(start=start, end=end, text=raw, plain=raw.rstrip("\r\n")))
    if not out and text:
        out.append(_Line(start=0, end=len(text), text=text, plain=text))
    return out


def _extract_doc_meta(doc_text: str) -> tuple[str | None, str | None, str | None]:
    if not doc_text:
        return None, None, None
    api = None
    kind = None
    name = None

    m = _API_VERSION_RE.search(doc_text[:4000])
    if m:
        api = (m.group("val") or "").strip() or None
    m = _KIND_RE.search(doc_text[:4000])
    if m:
        kind = (m.group("val") or "").strip() or None

    lines = _iter_lines(doc_text[:8000])
    meta_indent: int | None = None
    for ln in lines:
        if meta_indent is None:
            mm = _METADATA_RE.match(ln.plain)
            if mm:
                meta_indent = len(mm.group("indent") or "")
            continue
        if not ln.plain.strip() or ln.plain.lstrip().startswith("#"):
            continue
        indent = len(ln.plain) - len(ln.plain.lstrip(" "))
        if indent <= meta_indent:
            break
        nm = _NAME_RE.match(ln.plain)
        if nm:
            name = (nm.group("val") or "").strip() or None
            break

    return kind, name, api


def _build_docs(text: str) -> list[_Doc]:
    if not text:
        return []

    seps = [m.start() for m in _DOC_SEP_RE.finditer(text)]
    docs: list[_Doc] = []
    if not seps:
        kind, name, api = _extract_doc_meta(text)
        return [_Doc(start=0, end=len(text), index=0, kind=kind, name=name, api_version=api)]

    starts = [0] + seps
    starts = sorted(set(starts))
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(text)
        doc_text = text[start:end]
        if not doc_text.strip():
            continue
        kind, name, api = _extract_doc_meta(doc_text)
        docs.append(_Doc(start=start, end=end, index=len(docs), kind=kind, name=name, api_version=api))
    return docs


def _collect_yaml_signal_stats(lines: list[str]) -> _YamlSignalStats:
    key_with_value = 0
    key_only = 0
    indented = 0
    list_items = 0

    for ln in lines:
        if _LIST_ITEM_RE.match(ln):
            list_items += 1
        if _INDENTED_KEY_RE.match(ln):
            indented += 1
        if _KEY_ONLY_RE.match(ln):
            key_only += 1
            continue
        if _parse_yaml_kv_line(ln) is not None:
            key_with_value += 1

    return _YamlSignalStats(
        key_with_value=key_with_value,
        key_only=key_only,
        indented=indented,
        list_items=list_items,
        total_lines=len(lines),
    )


def _looks_like_yaml_from_doc_separators(head: str) -> bool:
    if _DOC_SEP_RE.search(head) is None:
        return False
    kv = sum(1 for ln in head.splitlines() if _parse_yaml_kv_line(ln) is not None)
    return kv >= 4


def _looks_like_structured_yaml(text: str) -> bool:
    raw_lines = [ln for ln in (text or "").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if len(raw_lines) < 8:
        return False

    stats = _collect_yaml_signal_stats(raw_lines[:200])
    key_lines = stats.key_with_value + stats.key_only
    if key_lines < 6:
        return False

    ratio = key_lines / max(1, stats.total_lines)
    if ratio < 0.25:
        return False

    return bool(stats.key_only >= 1 or stats.indented >= 2 or stats.list_items >= 2)


def _build_yaml_chunk_metadata(
    *,
    base_meta: dict[str, Any],
    split_meta: dict[str, Any],
    doc_info: _Doc,
    doc_count: int,
    abs_start: int,
    abs_end: int,
) -> dict[str, Any]:
    meta: dict[str, Any] = dict(base_meta)
    meta.update(split_meta)
    meta["chunk_strategy"] = "yaml_manifest"
    meta["start_char"] = abs_start
    meta["end_char"] = abs_end
    meta.setdefault("doc_type_kwd", "yaml")
    meta["yaml_doc_index"] = int(doc_info.index)
    meta["yaml_doc_count"] = int(doc_count)
    if doc_info.api_version:
        meta["yaml_api_version"] = doc_info.api_version
    if doc_info.kind:
        meta["yaml_kind"] = doc_info.kind
    if doc_info.name:
        meta["yaml_name"] = doc_info.name
    if doc_info.kind and doc_info.name:
        meta["yaml_id"] = f"{doc_info.kind}/{doc_info.name}"
    return meta


def looks_like_yaml_manifest(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    if "\t" in text:
        # Tabs are rare in YAML; avoid false positives from other formats.
        return False

    head = text[:6000]
    if re.search(r"(?m)^\s*apiVersion\s*:\s*\S+", head) and re.search(r"(?m)^\s*kind\s*:\s*\S+", head):
        return True
    if _looks_like_yaml_from_doc_separators(head):
        return True
    return _looks_like_structured_yaml(text)


class YAMLManifestChunker(BaseChunker):
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

            docs = _build_docs(text)
            if not docs:
                continue

            doc_count = len(docs)
            for d in docs:
                doc_text = text[d.start : d.end]
                if not doc_text.strip():
                    continue

                split_docs = self._fallback_splitter.create_documents(texts=[doc_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = d.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta = _build_yaml_chunk_metadata(
                        base_meta=base_meta,
                        split_meta=sd.metadata or {},
                        doc_info=d,
                        doc_count=doc_count,
                        abs_start=abs_start,
                        abs_end=abs_end,
                    )
                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
