"""
PDF layout-aware chunking.

This strategy is intended for parsed PDF markdown that contains position tags of the form:

  @@page\tleft\tright\ttop\tbottom##

These tags are produced by layout-aware PDF parsers (e.g., DeepDoc/Docling/MinerU) and are
consumed by the Chunk Preview PDF panel to map chunks back to bounding boxes.

Design goals:
- Do not split *within* a position-tag block (keeps PDF box mapping stable).
- Strip position tags from chunk text (embedding-friendly).
- Surface lightweight bbox + column hints in chunk metadata (PII-safe numeric-only).

Notes:
- start_char/end_char are offsets into the original text *with tags*, so frontend mapping can
  remove tags for display while keeping stable highlight ranges.
- When tags are missing, this strategy falls back to `langchain_recursive` behavior.
"""


import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.strategies.recursive import LangChainRecursiveChunker
from app.rag.core.logging import get_logger

logger = get_logger(__name__)

# Keep the same tag shape used by the parsing workspace and chunk-preview API.
POSITION_TAG_RE = re.compile(r"@@([0-9-]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##")


@dataclass(frozen=True)
class PositionTag:
    pages: tuple[int, ...]
    left: float
    right: float
    top: float
    bottom: float


@dataclass
class _Block:
    raw_start: int
    raw_end: int
    tags: list[PositionTag]


def _strip_position_tags(text: str) -> str:
    if not text:
        return ""
    return POSITION_TAG_RE.sub("", text)


def _parse_pages(value: str) -> tuple[int, ...]:
    s = str(value or "").strip()
    if not s:
        return ()
    out: list[int] = []
    for part in s.split("-"):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if n <= 0:
            continue
        out.append(n)
    # Dedup while preserving order.
    seen: set[int] = set()
    uniq: list[int] = []
    for n in out:
        if n in seen:
            continue
        seen.add(n)
        uniq.append(n)
    return tuple(uniq)


def _parse_tag(match: re.Match[str]) -> PositionTag | None:
    try:
        pages = _parse_pages(match.group(1))
        left = float(match.group(2))
        right = float(match.group(3))
        top = float(match.group(4))
        bottom = float(match.group(5))
    except Exception:
        return None
    if not pages:
        return None
    return PositionTag(pages=pages, left=float(left), right=float(right), top=float(top), bottom=float(bottom))


def _extract_position_blocks(raw: str) -> list[_Block]:
    """
    Extract position-tag blocks from raw markdown.

    A "block" is: some text (possibly with whitespace) followed by 1+ position tags.
    Consecutive tags with no intervening text are treated as belonging to the previous block.
    """
    if not raw:
        return []

    blocks: list[_Block] = []
    cursor = 0

    for m in POSITION_TAG_RE.finditer(raw):
        tag = _parse_tag(m)
        if tag is None:
            cursor = m.end()
            continue

        text_chunk = raw[cursor : m.start()]
        has_text = bool(text_chunk.strip())
        if has_text or not blocks:
            blocks.append(_Block(raw_start=int(cursor), raw_end=int(m.end()), tags=[tag]))
        else:
            # Attach to previous block.
            blocks[-1].raw_end = int(m.end())
            blocks[-1].tags.append(tag)

        cursor = int(m.end())

    # Trailing text without any tag is kept as a tagless block (best-effort).
    tail = raw[cursor:]
    if tail.strip():
        blocks.append(_Block(raw_start=int(cursor), raw_end=len(raw), tags=[]))

    return blocks


def _collect_tags(blocks: Iterable[_Block]) -> list[PositionTag]:
    out: list[PositionTag] = []
    for b in blocks:
        out.extend(list(b.tags or []))
    return out


def _layout_meta_from_tags(tags: list[PositionTag]) -> dict[str, Any] | None:
    if not tags:
        return None

    # Expand multi-page tags into per-page boxes (same coords per page).
    by_page: dict[int, list[tuple[float, float, float, float]]] = {}
    for t in tags:
        for p in t.pages:
            by_page.setdefault(int(p), []).append((float(t.left), float(t.right), float(t.top), float(t.bottom)))

    pages = sorted(by_page.keys())
    if not pages:
        return None

    page_layout: list[dict[str, Any]] = []
    for p in pages:
        boxes = by_page.get(p) or []
        if not boxes:
            continue

        # Estimate page width from observed right-most coordinate.
        page_width = max((r for (_l, r, _t, _b) in boxes), default=0.0)
        if page_width <= 0.0:
            page_width = 1.0

        centers = [((x0 + x1) / 2.0) / page_width for (x0, x1, _y0, _y1) in boxes]
        left_any = any(c < 0.45 for c in centers)
        right_any = any(c > 0.55 for c in centers)
        column_count = 2 if (left_any and right_any) else 1

        cols: dict[int, list[tuple[float, float, float, float]]] = {0: [], 1: []}
        for (x0, x1, y0, y1) in boxes:
            c = ((x0 + x1) / 2.0) / page_width
            col = 0 if (column_count == 1 or c < 0.5) else 1
            cols[col].append((x0, x1, y0, y1))

        def _union(items: list[tuple[float, float, float, float]]) -> dict[str, float] | None:
            if not items:
                return None
            ls = [x[0] for x in items]
            rs = [x[1] for x in items]
            ts = [x[2] for x in items]
            bs = [x[3] for x in items]
            return {
                "x0": round(float(min(ls)), 3),
                "x1": round(float(max(rs)), 3),
                "y0": round(float(min(ts)), 3),
                "y1": round(float(max(bs)), 3),
            }

        union_total = _union(list(boxes))
        col_items: list[dict[str, Any]] = []
        for col in (0, 1):
            if col not in cols:
                continue
            u = _union(cols[col])
            if u is None:
                continue
            col_items.append(
                {
                    "col": int(col),
                    "bbox": u,
                    "boxes": int(len(cols[col])),
                }
            )

        page_layout.append(
            {
                "page": int(p),
                "column_count": int(column_count),
                "bbox": union_total,
                "columns": col_items,
                "boxes": int(len(boxes)),
            }
        )

    if not page_layout:
        return None

    return {
        "schema": "mimirq.pdf_layout.v1",
        "pages": pages,
        "page_layout": page_layout,
        "tag_count": int(len(tags)),
    }


class PDFLayoutChunker(BaseChunker):
    """
    Layout-aware chunker for parsed PDF markdown containing @@...## tags.
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)
        self._fallback = LangChainRecursiveChunker(chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap)

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []
        for doc in documents or []:
            raw = doc.page_content or ""
            if not raw.strip():
                continue

            # Only apply to docs that actually carry position tags.
            if POSITION_TAG_RE.search(raw) is None:
                # Fall back to recursive splitting (keeps offsets correct for non-PDF docs).
                for c in self._fallback.split_documents([doc]):
                    meta = dict(c.metadata or {})
                    fallback_strategy = str(meta.get("chunk_strategy") or "langchain_recursive")
                    meta["chunk_strategy_fallback"] = fallback_strategy
                    meta["chunk_strategy"] = "pdf_layout"
                    out.append(Document(page_content=c.page_content, metadata=meta))
                continue

            blocks = _extract_position_blocks(raw)
            if not blocks:
                # Defensive: should not happen if POSITION_TAG_RE.search matched.
                for c in self._fallback.split_documents([doc]):
                    meta = dict(c.metadata or {})
                    fallback_strategy = str(meta.get("chunk_strategy") or "langchain_recursive")
                    meta["chunk_strategy_fallback"] = fallback_strategy
                    meta["chunk_strategy"] = "pdf_layout"
                    out.append(Document(page_content=c.page_content, metadata=meta))
                continue

            # Precompute per-block cleaned lengths for stable chunk sizing.
            cleaned_lens: list[int] = []
            for b in blocks:
                cleaned = _strip_position_tags(raw[b.raw_start : b.raw_end]).strip()
                cleaned_lens.append(len(cleaned))

            i = 0
            while i < len(blocks):
                start_i = i
                acc = 0
                end_i = i - 1

                while i < len(blocks):
                    blen = int(cleaned_lens[i] or 0)
                    if blen <= 0:
                        i += 1
                        continue

                    # If this is the first block, always include it (even if it exceeds chunk_size).
                    next_acc = blen if acc == 0 else acc + 2 + blen  # +2 for the typical paragraph gap
                    if acc > 0 and next_acc > self.chunk_size:
                        break

                    acc = next_acc
                    end_i = i
                    i += 1

                    if acc >= self.chunk_size:
                        break

                if end_i < start_i:
                    # No usable blocks (all empty). Bail out to avoid infinite loops.
                    break

                raw_start = int(blocks[start_i].raw_start)
                raw_end = int(blocks[end_i].raw_end)
                raw_slice = raw[raw_start:raw_end]
                cleaned = _strip_position_tags(raw_slice).strip()
                if not cleaned:
                    # Still advance (we consumed >=1 block).
                    continue

                tags = _collect_tags(blocks[start_i : end_i + 1])
                layout = _layout_meta_from_tags(tags)

                meta = dict(doc.metadata or {})
                meta["chunk_strategy"] = "pdf_layout"
                meta["start_char"] = raw_start
                meta["end_char"] = raw_end

                if layout is not None:
                    meta["layout"] = layout
                    try:
                        pages = layout.get("pages") if isinstance(layout, Mapping) else None
                        if isinstance(pages, list) and pages:
                            meta.setdefault("page", int(pages[0]))
                            meta.setdefault("page_number", int(pages[0]))
                    except Exception as exc:
                        logger.debug("Ignoring PDF layout page metadata hint failure: %s", exc)

                out.append(Document(page_content=cleaned, metadata=meta))

                # Compute the next window start using an approximate character-based overlap.
                if self.chunk_overlap <= 0:
                    continue

                overlap = 0
                j = end_i
                while j >= start_i and overlap < self.chunk_overlap:
                    overlap += int(cleaned_lens[j] or 0)
                    j -= 1
                next_i = max(start_i + 1, j + 1)
                if next_i < i:
                    i = next_i

        return out
