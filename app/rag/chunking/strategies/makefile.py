"""
Makefile-aware chunking strategy.

Targets Makefiles / build scripts with targets like:
build: deps
\t@echo building

The chunker splits by target blocks (target line + recipe) and groups multiple
targets per chunk to respect chunk_size/overlap while preserving offsets.
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


@dataclass(frozen=True)
class _Target:
    start: int
    end: int
    name: str


_TARGET_NAME_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./%:@+-")


def _parse_target_line(line: str) -> str | None:
    """
    Parse a Make target line:
      target: deps

    Returns the target name or None.

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    s = str(line or "")
    if not s:
        return None
    colon = s.find(":")
    if colon <= 0:
        return None
    if colon + 1 < len(s) and s[colon + 1] == "=":
        # Exclude variable assignments like VAR:=
        return None
    name = s[:colon].strip()
    if not name or len(name) > 80:
        return None
    if any(ch not in _TARGET_NAME_ALLOWED for ch in name):
        return None
    return name


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


def _iter_targets(text: str) -> list[_Target]:
    lines = _iter_lines(text)
    idxs: list[int] = []
    names: list[str] = []
    for i, ln in enumerate(lines):
        p = ln.plain
        if not p.strip() or p.lstrip().startswith("#"):
            continue
        if p.startswith("\t"):
            continue
        name = _parse_target_line(p)
        if not name:
            continue
        idxs.append(i)
        names.append(name)

    targets: list[_Target] = []
    for k, i in enumerate(idxs):
        start = lines[i].start
        end = lines[idxs[k + 1]].start if k + 1 < len(idxs) else len(text)
        targets.append(_Target(start=start, end=end, name=names[k]))
    return targets


def looks_like_makefile(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    lowered = (text or "").lower()
    if ".phony" in lowered:
        return True
    targets = _iter_targets(text)
    if len(targets) < 2:
        return False
    # Require at least one recipe line.
    for ln in (text or "").splitlines()[:400]:
        if ln.startswith("\t"):
            return True
    return False


class MakefileChunker(BaseChunker):
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

            targets = _iter_targets(text)
            if not targets:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "makefile"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "makefile")
                    meta["make_fallback"] = True
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            start_idx = 0
            while start_idx < len(targets):
                end_idx = start_idx
                while end_idx < len(targets):
                    cand_start = targets[start_idx].start
                    cand_end = targets[end_idx].end
                    cand_len = cand_end - cand_start
                    if end_idx == start_idx or cand_len <= self.chunk_size:
                        end_idx += 1
                        continue
                    break
                if end_idx == start_idx:
                    end_idx = start_idx + 1

                chunk_start = targets[start_idx].start
                chunk_end = targets[end_idx - 1].end
                content = text[chunk_start:chunk_end]

                names = [t.name for t in targets[start_idx:end_idx] if t.name]
                uniq: list[str] = []
                for n in names:
                    if n not in uniq:
                        uniq.append(n)
                uniq = uniq[:25]

                meta: dict[str, Any] = dict(base_meta)
                meta["chunk_strategy"] = "makefile"
                meta["start_char"] = chunk_start
                meta["end_char"] = chunk_end
                meta.setdefault("doc_type_kwd", "makefile")
                meta["make_target_count"] = int(end_idx - start_idx)
                if uniq:
                    meta["make_targets"] = uniq
                    meta["make_target"] = uniq[0]
                out.append(Document(page_content=content, metadata=meta))

                next_start = end_idx
                if self.chunk_overlap > 0 and (end_idx - start_idx) > 1:
                    desired = end_idx - 1
                    while desired > start_idx:
                        overlap_len = targets[end_idx - 1].end - targets[desired - 1].start
                        if overlap_len <= self.chunk_overlap:
                            desired -= 1
                            continue
                        break
                    next_start = desired if desired > start_idx else (end_idx - 1)

                if next_start <= start_idx:
                    next_start = end_idx
                start_idx = next_start

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
