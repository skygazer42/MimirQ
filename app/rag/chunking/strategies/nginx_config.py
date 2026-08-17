"""
Nginx config aware chunking strategy.

Targets nginx-like configuration files containing blocks like:
- http { ... }
- server { ... }
- location / { ... }

The chunker prefers splitting by server blocks when present; otherwise it falls
back to a brace-aware block splitter. Offsets are preserved.
"""

import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Block:
    start: int
    end: int
    kind: str
    title: str | None
    level: int


_SERVER_OPEN_RE = re.compile(r"(?m)^\s*server\s*\{")
_BLOCK_OPEN_RE = re.compile(
    r"(?m)^\s*(?P<kind>http|server|location|upstream|map|events)\b(?P<rest>[^;{]*)\{\s*(?:#.*)?$"
)


def _extract_directive_value(text: str, directive: str) -> str | None:
    """
    Extract a simple Nginx directive value like:
      server_name example.com www.example.com;
      listen 80;

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    raw = str(text or "")
    d = str(directive or "").strip()
    if not raw or not d:
        return None
    d_cf = d.casefold()

    for ln in raw.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        low = s.casefold()
        if not low.startswith(d_cf):
            continue
        if len(s) > len(d) and not s[len(d)].isspace():
            continue
        rest = s[len(d) :].strip()
        if not rest:
            continue
        if "#" in rest:
            rest = rest.split("#", 1)[0].strip()
        semi = rest.find(";")
        if semi != -1:
            rest = rest[:semi].strip()
        rest = " ".join(rest.split())
        return rest[:200] or None

    return None


def _find_matching_brace(text: str, start: int) -> int | None:
    i = text.find("{", start)
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(text)):
        ch = text[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = j + 1
                if end < len(text) and text[end : end + 1] == "\n":
                    end += 1
                return end
    return None


def _iter_named_blocks(text: str, kind: str) -> list[_Block]:
    blocks: list[_Block] = []
    for m in _BLOCK_OPEN_RE.finditer(text):
        if (m.group("kind") or "").strip().lower() != kind:
            continue
        start = m.start()
        end = _find_matching_brace(text, start)
        if end is None:
            continue
        rest = (m.group("rest") or "").strip()
        title = rest if rest else None
        blocks.append(_Block(start=start, end=end, kind=kind, title=title, level=1))
    return blocks


def _build_blocks(text: str) -> list[_Block]:
    if not text:
        return []

    server_blocks = _iter_named_blocks(text, "server")
    if server_blocks:
        # Ensure stable ordering and no overlaps.
        server_blocks = sorted(server_blocks, key=lambda b: b.start)
        dedup: list[_Block] = []
        last_end = -1
        for b in server_blocks:
            if b.start < last_end:
                continue
            dedup.append(b)
            last_end = b.end
        return dedup

    # Fall back to other top-ish blocks.
    for k in ("http", "upstream", "location", "events", "map"):
        blocks = _iter_named_blocks(text, k)
        if blocks:
            blocks = sorted(blocks, key=lambda b: b.start)
            return blocks

    return [_Block(start=0, end=len(text), kind="nginx", title=None, level=0)]


def looks_like_nginx_config(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    lowered = text.lower()
    if "server {" in lowered and "listen " in lowered:
        return True
    if "http {" in lowered and "server {" in lowered:
        return True
    if re.search(r"(?m)^\s*(events|http|server|location)\b.*\{\s*$", text):
        return True
    return False


class NginxConfigChunker(BaseChunker):
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

    def _append_block_chunks(
        self,
        out: list[Document],
        *,
        block: _Block,
        block_text: str,
        base_meta: dict[str, Any],
        server_names: str | None,
        listen: str | None,
    ) -> None:
        split_docs = self._fallback_splitter.create_documents(texts=[block_text], metadatas=[base_meta])
        for sd in split_docs:
            local_start = sd.metadata.pop("start_index", None) or 0
            abs_start = block.start + int(local_start)
            abs_end = abs_start + len(sd.page_content)

            meta: dict[str, Any] = dict(base_meta)
            meta.update(sd.metadata or {})
            meta["chunk_strategy"] = "nginx_config"
            meta["start_char"] = abs_start
            meta["end_char"] = abs_end
            meta.setdefault("doc_type_kwd", "nginx")
            meta["nginx_block_kind"] = block.kind
            if block.title:
                meta["nginx_block_title"] = block.title
            if server_names:
                meta["nginx_server_name"] = server_names
            if listen:
                meta["nginx_listen"] = listen

            out.append(Document(page_content=sd.page_content, metadata=meta))

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            blocks = _build_blocks(text)
            for b in blocks:
                blk_text = text[b.start : b.end]
                if not blk_text.strip():
                    continue

                server_names = None
                listen = None
                if b.kind == "server":
                    server_names = _extract_directive_value(blk_text[:5000], "server_name")
                    listen = _extract_directive_value(blk_text[:5000], "listen")
                self._append_block_chunks(
                    out,
                    block=b,
                    block_text=blk_text,
                    base_meta=base_meta,
                    server_names=server_names,
                    listen=listen,
                )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
