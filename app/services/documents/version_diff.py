from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ContentHashMultisetDiff:
    from_chunk_count: int
    to_chunk_count: int
    unchanged_chunks: int
    added_chunks: int
    removed_chunks: int
    added_hashes: tuple[str, ...] = ()
    removed_hashes: tuple[str, ...] = ()


def _normalize_hashes(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    for raw in items:
        val = raw.strip()
        if not val:
            continue
        out.append(val)
    return out


def content_hash_multiset_diff(
    *,
    from_hashes: Iterable[str],
    to_hashes: Iterable[str],
    sample_limit: int = 50,
) -> ContentHashMultisetDiff:
    """
    Compute a multiset diff between two chunk collections keyed by content_hash.

    Notes:
    - Uses multiset counts (duplicates matter).
    - Returns counts + best-effort sample hash lists for UI/debug.
    """
    before_counts = Counter(_normalize_hashes(from_hashes))
    after_counts = Counter(_normalize_hashes(to_hashes))

    from_total = sum(before_counts.values())
    to_total = sum(after_counts.values())

    unchanged = 0
    for key in before_counts.keys() & after_counts.keys():
        unchanged += min(before_counts[key], after_counts[key])

    added = to_total - unchanged
    removed = from_total - unchanged

    added_hashes: list[tuple[int, str]] = []
    removed_hashes: list[tuple[int, str]] = []
    for key in before_counts.keys() | after_counts.keys():
        before_count = before_counts[key]
        after_count = after_counts[key]
        if after_count > before_count:
            added_hashes.append((after_count - before_count, key))
        elif before_count > after_count:
            removed_hashes.append((before_count - after_count, key))

    added_hashes.sort(key=lambda item: (-item[0], item[1]))
    removed_hashes.sort(key=lambda item: (-item[0], item[1]))

    lim = max(0, sample_limit)
    return ContentHashMultisetDiff(
        from_chunk_count=from_total,
        to_chunk_count=to_total,
        unchanged_chunks=unchanged,
        added_chunks=added,
        removed_chunks=removed,
        added_hashes=tuple(h for _n, h in added_hashes[:lim]),
        removed_hashes=tuple(h for _n, h in removed_hashes[:lim]),
    )
