
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


def _normalize_hashes(items: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    if not items:
        return out
    for raw in items:
        if not isinstance(raw, str):
            continue
        val = raw.strip()
        if not val:
            continue
        out.append(val)
    return out


def content_hash_multiset_diff(
    *,
    from_hashes: Iterable[str] | None,
    to_hashes: Iterable[str] | None,
    sample_limit: int = 50,
) -> ContentHashMultisetDiff:
    """
    Compute a multiset diff between two chunk collections keyed by content_hash.

    Notes:
    - Uses multiset counts (duplicates matter).
    - Returns counts + best-effort sample hash lists for UI/debug.
    """
    a = Counter(_normalize_hashes(from_hashes))
    b = Counter(_normalize_hashes(to_hashes))

    from_total = int(sum(a.values()))
    to_total = int(sum(b.values()))

    unchanged = 0
    for key in (a.keys() & b.keys()):
        unchanged += min(int(a.get(key, 0) or 0), int(b.get(key, 0) or 0))

    added = max(0, to_total - int(unchanged))
    removed = max(0, from_total - int(unchanged))

    added_hashes: list[tuple[int, str]] = []
    removed_hashes: list[tuple[int, str]] = []
    for key in (a.keys() | b.keys()):
        da = int(a.get(key, 0) or 0)
        db = int(b.get(key, 0) or 0)
        if db > da:
            added_hashes.append((db - da, key))
        elif da > db:
            removed_hashes.append((da - db, key))

    added_hashes.sort(key=lambda item: (-int(item[0]), item[1]))
    removed_hashes.sort(key=lambda item: (-int(item[0]), item[1]))

    lim = max(0, int(sample_limit or 0))
    return ContentHashMultisetDiff(
        from_chunk_count=from_total,
        to_chunk_count=to_total,
        unchanged_chunks=int(unchanged),
        added_chunks=int(added),
        removed_chunks=int(removed),
        added_hashes=tuple(h for _n, h in (added_hashes[:lim] if lim else [])),
        removed_hashes=tuple(h for _n, h in (removed_hashes[:lim] if lim else [])),
    )
