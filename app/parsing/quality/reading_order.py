from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict

from app.parsing.artifact_stats import POSITION_TAG_RE
from app.parsing.utils.scalars import coerce_float as _coerce_float
from app.parsing.utils.scalars import coerce_int as _coerce_int
from app.rag.core.logging import get_logger

_READING_ORDER_SCHEMA = "mimirq.reading_order_score.v1"


class _ReadingOrderItem(TypedDict):
    obs_index: int
    page: int
    x0: float
    y0: float
    x1: float
    y1: float


def _item_meta(item: Any) -> Mapping[str, Any]:
    if isinstance(item, Mapping):
        meta = item.get("metadata")
        if isinstance(meta, Mapping):
            return meta
        return item
    meta = getattr(item, "metadata", None)
    if isinstance(meta, Mapping):
        return meta
    return {}


def _normalize_items(items: Sequence[Any] | None) -> list[_ReadingOrderItem]:
    out: list[_ReadingOrderItem] = []
    for idx, item in enumerate(items or []):
        meta = _item_meta(item)
        page = _coerce_int(meta.get("page"))
        if page is None:
            page = _coerce_int(meta.get("page_number"))
        x0 = _coerce_float(meta.get("x0"))
        if x0 is None:
            x0 = _coerce_float(meta.get("left"))
        y0 = _coerce_float(meta.get("y0"))
        if y0 is None:
            y0 = _coerce_float(meta.get("top"))
        x1 = _coerce_float(meta.get("x1"))
        if x1 is None and x0 is not None:
            width = _coerce_float(meta.get("width"))
            x1 = x0 + width if width is not None else None
        y1 = _coerce_float(meta.get("y1"))
        if y1 is None and y0 is not None:
            height = _coerce_float(meta.get("height"))
            y1 = y0 + height if height is not None else None
        if page is None or x0 is None or y0 is None or x1 is None or y1 is None:
            continue
        out.append(
            {
                "obs_index": idx,
                "page": page,
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
            }
        )
    return out


def _column_threshold(page_items: Sequence[_ReadingOrderItem]) -> float | None:
    centers = sorted((item["x0"] + item["x1"]) / 2.0 for item in page_items)
    if len(centers) < 4:
        return None
    page_min = min(item["x0"] for item in page_items)
    page_max = max(item["x1"] for item in page_items)
    page_width = max(1.0, page_max - page_min)

    best_gap = 0.0
    threshold = None
    for left, right in zip(centers, centers[1:], strict=False):
        gap = right - left
        if gap > best_gap:
            best_gap = gap
            threshold = (left + right) / 2.0

    if threshold is None or best_gap < page_width * 0.18:
        return None
    return threshold


def _expected_order_for_page(page_items: Sequence[_ReadingOrderItem]) -> tuple[list[_ReadingOrderItem], bool]:
    threshold = _column_threshold(page_items)
    if threshold is None:
        return sorted(page_items, key=lambda item: (item["y0"], item["x0"], item["obs_index"])), False

    return (
        sorted(
            page_items,
            key=lambda item: (
                0 if ((item["x0"] + item["x1"]) / 2.0) <= threshold else 1,
                item["y0"],
                item["x0"],
                item["obs_index"],
            ),
        ),
        True,
    )


def _score_reading_order_items(items: Sequence[Any] | None) -> dict[str, Any]:
    normalized = _normalize_items(items)
    if not normalized:
        return {
            "score": 1.0,
            "items": 0,
            "pages": 0,
            "multi_column_pages": 0,
            "inversions": 0,
        }

    by_page: dict[int, list[_ReadingOrderItem]] = defaultdict(list)
    for item in normalized:
        by_page[item["page"]].append(item)

    inversions = 0
    total_pairs = 0
    multi_column_pages = 0

    for page_items in by_page.values():
        expected, is_multi_column = _expected_order_for_page(page_items)
        if is_multi_column:
            multi_column_pages += 1
        expected_rank = {item["obs_index"]: idx for idx, item in enumerate(expected)}
        observed = sorted(page_items, key=lambda item: item["obs_index"])
        n = len(observed)
        total_pairs += max(0, n * (n - 1) // 2)
        for idx, left in enumerate(observed):
            for right in observed[idx + 1 :]:
                if expected_rank[left["obs_index"]] > expected_rank[right["obs_index"]]:
                    inversions += 1

    score = 1.0 if total_pairs <= 0 else max(0.0, 1.0 - (float(inversions) / float(total_pairs)))
    return {
        "score": round(score, 3),
        "items": len(normalized),
        "pages": len(by_page),
        "multi_column_pages": multi_column_pages,
        "inversions": inversions,
    }


def score_pdfplumber_reading_order(pages: Iterable[Any] | None) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for page_index, page in enumerate(pages or [], start=1):
        try:
            words = page.extract_words() or []
        except Exception:
            words = []
        for word in words:
            if not isinstance(word, Mapping):
                continue
            items.append(
                {
                    "page": page_index,
                    "x0": word.get("x0"),
                    "y0": word.get("top"),
                    "x1": word.get("x1"),
                    "y1": word.get("bottom"),
                }
            )
    return _score_reading_order_items(items)


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
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if n <= 0:
            continue
        out.append(n)
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
    return _Tag(pages=pages, left=left, right=right, top=top, bottom=bottom)


def _extract_blocks(markdown: str) -> tuple[list[_Block], int]:
    if not markdown:
        return [], 0

    blocks_tags: list[list[_Tag]] = []
    blocks_boxes: list[tuple[float, float, float, float]] = []
    blocks_pages: list[int] = []
    tag_count = 0
    cursor = 0
    has_last_block = False

    for match in POSITION_TAG_RE.finditer(markdown):
        tag = _parse_tag(match)
        cursor_text = markdown[cursor : match.start()]
        has_text = bool(cursor_text.strip())
        if has_text or not has_last_block:
            blocks_tags.append([])
            blocks_boxes.append((float("inf"), float("-inf"), float("inf"), float("-inf")))
            blocks_pages.append(0)
            has_last_block = True

        if tag is not None:
            tag_count += 1
            blocks_tags[-1].append(tag)
            left, right, top, bottom = blocks_boxes[-1]
            left = min(left, tag.left)
            right = max(right, tag.right)
            top = min(top, tag.top)
            bottom = max(bottom, tag.bottom)
            blocks_boxes[-1] = (left, right, top, bottom)
            page = min(tag.pages) if tag.pages else 0
            if blocks_pages[-1] <= 0 or (page > 0 and page < blocks_pages[-1]):
                blocks_pages[-1] = page

        cursor = match.end()

    out: list[_Block] = []
    for idx, (tags, box, page) in enumerate(zip(blocks_tags, blocks_boxes, blocks_pages, strict=False)):
        if not tags:
            continue
        left, right, top, bottom = box
        if page <= 0:
            page = 1
        out.append(
            _Block(
                idx=idx,
                page=page,
                left=left if left != float("inf") else 0.0,
                right=right if right != float("-inf") else 0.0,
                top=top if top != float("inf") else 0.0,
                bottom=bottom if bottom != float("-inf") else 0.0,
            )
        )
    return out, tag_count


def _count_inversions(ranks: list[int]) -> int:
    n = len(ranks)
    if n <= 1:
        return 0
    bit = [0] * (n + 2)

    def add(i: int, delta: int) -> None:
        while i <= n:
            bit[i] += delta
            i += i & -i

    def prefix_sum(i: int) -> int:
        total = 0
        while i > 0:
            total += bit[i]
            i -= i & -i
        return total

    inversions = 0
    seen = 0
    for rank in ranks:
        value = int(rank)
        if value <= 0:
            continue
        inversions += seen - prefix_sum(value)
        add(value, 1)
        seen += 1
    return inversions


def _reading_order_empty_result(*, tag_count: int) -> dict[str, Any]:
    return {
        "schema": _READING_ORDER_SCHEMA,
        "method": "position_tags",
        "score": None,
        "nid": None,
        "blocks": 0,
        "tag_count": tag_count,
        "pages": [],
        "column_pages": 0,
        "warnings": ["missing_position_tags"],
    }


def _trim_blocks(blocks: list[_Block], *, max_blocks: int) -> list[_Block]:
    if int(max_blocks or 0) <= 0 or len(blocks) <= int(max_blocks):
        return blocks
    keep = int(max_blocks)
    head = keep // 2
    tail = keep - head
    return list(blocks[:head]) + list(blocks[-tail:])


def _reading_order_insufficient_blocks_result(blocks: list[_Block], *, tag_count: int) -> dict[str, Any]:
    pages = sorted({block.page for block in blocks if block.page > 0})
    return {
        "schema": _READING_ORDER_SCHEMA,
        "method": "position_tags",
        "score": None,
        "nid": None,
        "blocks": len(blocks),
        "tag_count": tag_count,
        "pages": pages,
        "column_pages": 0,
        "warnings": ["insufficient_blocks"],
    }


def _blocks_by_page(blocks: list[_Block]) -> dict[int, list[_Block]]:
    by_page: dict[int, list[_Block]] = {}
    for block in blocks:
        by_page.setdefault(block.page, []).append(block)
    return by_page


def _page_widths(by_page: Mapping[int, Sequence[_Block]]) -> dict[int, float]:
    page_width: dict[int, float] = {}
    for page, items in by_page.items():
        width = max((item.right for item in items), default=0.0)
        page_width[page] = width if width > 0.0 else 1.0
    return page_width


def _page_layout_stats(
    by_page: Mapping[int, Sequence[_Block]],
    *,
    page_width: Mapping[int, float],
) -> tuple[dict[int, bool], dict[int, float], dict[int, float]]:
    page_is_two_col: dict[int, bool] = {}
    page_min_top: dict[int, float] = {}
    page_max_bottom: dict[int, float] = {}
    for page, items in by_page.items():
        width = page_width.get(page, 1.0) or 1.0
        centers = [((item.left + item.right) / 2.0) / width for item in items]
        left_any = any(center < 0.45 for center in centers)
        right_any = any(center > 0.55 for center in centers)
        page_is_two_col[page] = left_any and right_any
        page_min_top[page] = min((item.top for item in items), default=0.0)
        page_max_bottom[page] = max((item.bottom for item in items), default=0.0)
    return page_is_two_col, page_min_top, page_max_bottom


def _column_index(
    block: _Block,
    *,
    page_is_two_col: Mapping[int, bool],
    page_width: Mapping[int, float],
) -> int:
    if not page_is_two_col.get(block.page, False):
        return 0
    width = page_width.get(block.page, 1.0) or 1.0
    center = ((block.left + block.right) / 2.0) / width
    return 1 if center > 0.5 else 0


def _flow_group(
    block: _Block,
    *,
    page_is_two_col: Mapping[int, bool],
    page_width: Mapping[int, float],
    page_min_top: Mapping[int, float],
    page_max_bottom: Mapping[int, float],
) -> int:
    if not page_is_two_col.get(block.page, False):
        return 0
    width = page_width.get(block.page, 1.0) or 1.0
    span_ratio = max(0.0, block.right - block.left) / width
    if span_ratio < 0.75:
        return _column_index(block, page_is_two_col=page_is_two_col, page_width=page_width)
    top_min = page_min_top.get(block.page, 0.0)
    bottom_max = page_max_bottom.get(block.page, block.bottom)
    vertical_span = max(1.0, bottom_max - top_min)
    if block.top <= top_min + vertical_span * 0.12:
        return -1
    if block.bottom >= bottom_max - vertical_span * 0.12:
        return 2
    return 2 if block.top >= top_min + vertical_span * 0.35 else -1


def _score_reading_order_markdown(markdown: str, *, max_blocks: int = 600, min_blocks: int = 6) -> dict[str, Any]:
    blocks, tag_count = _extract_blocks(str(markdown or ""))
    if not blocks:
        return _reading_order_empty_result(tag_count=tag_count)

    blocks = _trim_blocks(blocks, max_blocks=int(max_blocks or 0))
    if len(blocks) < int(min_blocks):
        return _reading_order_insufficient_blocks_result(blocks, tag_count=tag_count)

    by_page = _blocks_by_page(blocks)
    page_width = _page_widths(by_page)
    page_is_two_col, page_min_top, page_max_bottom = _page_layout_stats(by_page, page_width=page_width)
    expected = sorted(
        blocks,
        key=lambda block: (
            block.page,
            _flow_group(
                block,
                page_is_two_col=page_is_two_col,
                page_width=page_width,
                page_min_top=page_min_top,
                page_max_bottom=page_max_bottom,
            ),
            block.top,
            block.left,
            block.idx,
        ),
    )
    expected_rank = {block.idx: index + 1 for index, block in enumerate(expected)}
    observed_ranks = [expected_rank.get(block.idx, 0) for block in blocks]
    inversions = _count_inversions(observed_ranks)

    n = len(observed_ranks)
    denom = n * (n - 1) / 2.0
    nid = float(inversions) / denom if denom > 0 else 0.0
    nid = max(0.0, min(1.0, nid))
    score = 1.0 - nid
    pages = sorted({block.page for block in blocks if block.page > 0})
    column_pages = sum(1 for page in pages if page_is_two_col.get(page, False))

    return {
        "schema": _READING_ORDER_SCHEMA,
        "method": "position_tags",
        "score": round(score, 4),
        "nid": round(nid, 4),
        "blocks": n,
        "tag_count": tag_count,
        "pages": pages,
        "column_pages": column_pages,
        "warnings": [],
    }


def score_reading_order(
    subject: str | Sequence[Any] | None, *, max_blocks: int = 600, min_blocks: int = 6
) -> dict[str, Any]:
    if isinstance(subject, str):
        return _score_reading_order_markdown(subject, max_blocks=max_blocks, min_blocks=min_blocks)
    return _score_reading_order_items(subject)


__all__ = ["score_pdfplumber_reading_order", "score_reading_order"]
