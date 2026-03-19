"""
Reading-order validation helpers.

Opt 6 (docs/plans/2026-03-19-document-parsing-optimization.md):
- Provide a lightweight, deterministic reading-order score that can be used by:
  - parse competition matrix selection (Opt8)
  - observability dashboards (Opt12)

Design notes:
- We do NOT re-render PDFs or run heavy layout models here.
- Instead, we reuse the existing position-tag format already produced by layout-aware PDF parsers:
    @@page\\tleft\\tright\\ttop\\tbottom##
- When tags are missing, this scorer returns a structured "no signal" payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.parsing.artifact_stats import POSITION_TAG_RE


@dataclass(frozen=True, slots=True)
class _Tag:
    pages: tuple[int, ...]
    left: float
    right: float
    top: float
    bottom: float


@dataclass(frozen=True, slots=True)
class _Block:
    idx: int
    # Use the earliest page for ordering when tags span multiple pages.
    page: int
    left: float
    right: float
    top: float
    bottom: float


def _parse_pages(raw: str) -> tuple[int, ...]:
    s = str(raw or "").strip()
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


def _parse_tag(match) -> _Tag | None:
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
    return _Tag(pages=pages, left=float(left), right=float(right), top=float(top), bottom=float(bottom))


def _extract_blocks(markdown: str) -> tuple[list[_Block], int]:
    """
    Extract position-tag blocks from markdown.

    Returns:
      (blocks, tag_count)
    """
    if not markdown:
        return [], 0

    blocks_tags: list[list[_Tag]] = []
    blocks_boxes: list[tuple[float, float, float, float]] = []
    blocks_pages: list[int] = []
    tag_count = 0

    cursor = 0
    has_last_block = False
    for m in POSITION_TAG_RE.finditer(markdown):
        tag = _parse_tag(m)
        cursor_text = markdown[cursor : m.start()]
        has_text = bool(cursor_text.strip())
        if has_text or not has_last_block:
            # Start a new block.
            blocks_tags.append([])
            blocks_boxes.append((float("inf"), float("-inf"), float("inf"), float("-inf")))
            blocks_pages.append(0)
            has_last_block = True

        if tag is not None:
            tag_count += 1
            blocks_tags[-1].append(tag)
            # Update union bbox.
            left, right, top, bottom = blocks_boxes[-1]
            left = min(left, float(tag.left))
            right = max(right, float(tag.right))
            top = min(top, float(tag.top))
            bottom = max(bottom, float(tag.bottom))
            blocks_boxes[-1] = (left, right, top, bottom)
            # Use smallest page as representative.
            page = min(tag.pages) if tag.pages else 0
            if blocks_pages[-1] <= 0 or (page > 0 and page < blocks_pages[-1]):
                blocks_pages[-1] = int(page)

        cursor = int(m.end())

    out: list[_Block] = []
    for i, (tags, box, page) in enumerate(zip(blocks_tags, blocks_boxes, blocks_pages, strict=False)):
        if not tags:
            # Ignore tagless blocks (no layout signal).
            continue
        left, right, top, bottom = box
        if page <= 0:
            page = 1
        out.append(
            _Block(
                idx=int(i),
                page=int(page),
                left=float(left if left != float("inf") else 0.0),
                right=float(right if right != float("-inf") else 0.0),
                top=float(top if top != float("inf") else 0.0),
                bottom=float(bottom if bottom != float("-inf") else 0.0),
            )
        )
    return out, int(tag_count)


def _count_inversions(ranks: list[int]) -> int:
    """
    Count inversions in a permutation (Fenwick tree).

    ranks are 1-based.
    """
    n = int(len(ranks))
    if n <= 1:
        return 0
    bit = [0] * (n + 2)

    def add(i: int, delta: int) -> None:
        while i <= n:
            bit[i] += delta
            i += i & -i

    def prefix_sum(i: int) -> int:
        s = 0
        while i > 0:
            s += bit[i]
            i -= i & -i
        return s

    inv = 0
    seen = 0
    for x in ranks:
        xi = int(x)
        if xi <= 0:
            continue
        inv += seen - prefix_sum(xi)
        add(xi, 1)
        seen += 1
    return int(inv)


def score_reading_order(
    markdown: str,
    *,
    max_blocks: int = 600,
    min_blocks: int = 6,
) -> dict[str, Any]:
    """
    Return a best-effort reading-order score derived from @@...## position tags.

    The score is based on normalized inversion distance (NID) between:
    - observed block order: as produced by the parser
    - expected block order: sorted by (page, column, top, left)

    Output is JSON-safe and intentionally PII-minimal (numeric-only).
    """
    raw = str(markdown or "")
    blocks, tag_count = _extract_blocks(raw)
    if not blocks:
        return {
            "schema": "mimirq.reading_order_score.v1",
            "method": "position_tags",
            "score": None,
            "nid": None,
            "blocks": 0,
            "tag_count": int(tag_count),
            "pages": [],
            "column_pages": 0,
            "warnings": ["missing_position_tags"],
        }

    # Bound for safety; for very large docs we sample deterministically (head+tail).
    blocks_total = int(len(blocks))
    if int(max_blocks or 0) > 0 and blocks_total > int(max_blocks):
        keep = int(max_blocks)
        head = keep // 2
        tail = keep - head
        blocks = list(blocks[:head]) + list(blocks[-tail:])

    if len(blocks) < int(min_blocks):
        pages = sorted({int(b.page) for b in blocks if int(b.page) > 0})
        return {
            "schema": "mimirq.reading_order_score.v1",
            "method": "position_tags",
            "score": None,
            "nid": None,
            "blocks": int(len(blocks)),
            "tag_count": int(tag_count),
            "pages": pages,
            "column_pages": 0,
            "warnings": ["insufficient_blocks"],
        }

    # Estimate per-page width (max observed right coordinate).
    by_page: dict[int, list[_Block]] = {}
    for b in blocks:
        by_page.setdefault(int(b.page), []).append(b)

    page_width: dict[int, float] = {}
    for p, items in by_page.items():
        w = max((float(it.right) for it in items), default=0.0)
        page_width[int(p)] = float(w if w > 0.0 else 1.0)

    # Determine which pages look like two-column layout (simple heuristic).
    page_is_two_col: dict[int, bool] = {}
    for p, items in by_page.items():
        w = page_width.get(int(p), 1.0) or 1.0
        centers = [((float(it.left) + float(it.right)) / 2.0) / float(w) for it in items]
        left_any = any(c < 0.45 for c in centers)
        right_any = any(c > 0.55 for c in centers)
        page_is_two_col[int(p)] = bool(left_any and right_any)

    def _col_idx(b: _Block) -> int:
        if not page_is_two_col.get(int(b.page), False):
            return 0
        w = page_width.get(int(b.page), 1.0) or 1.0
        center = ((float(b.left) + float(b.right)) / 2.0) / float(w)
        return 1 if center > 0.5 else 0

    expected = sorted(
        blocks,
        key=lambda b: (
            int(b.page),
            _col_idx(b),
            float(b.top),
            float(b.left),
            int(b.idx),
        ),
    )
    expected_rank: dict[int, int] = {int(b.idx): i + 1 for i, b in enumerate(expected)}

    observed_ranks = [expected_rank.get(int(b.idx), 0) for b in blocks]
    inversions = _count_inversions(observed_ranks)

    n = int(len(observed_ranks))
    denom = n * (n - 1) / 2.0
    nid = float(inversions) / float(denom) if denom > 0 else 0.0
    nid = max(0.0, min(1.0, nid))
    score = 1.0 - nid

    pages = sorted({int(b.page) for b in blocks if int(b.page) > 0})
    column_pages = sum(1 for p in pages if page_is_two_col.get(int(p), False))

    return {
        "schema": "mimirq.reading_order_score.v1",
        "method": "position_tags",
        "score": round(float(score), 4),
        "nid": round(float(nid), 4),
        "blocks": int(n),
        "tag_count": int(tag_count),
        "pages": pages,
        "column_pages": int(column_pages),
        "warnings": [],
    }


__all__ = ["score_reading_order"]
