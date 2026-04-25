from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

_ASCII_TOKEN_CHAR_RE = re.compile(r"[A-Za-z0-9_]")


@dataclass(frozen=True)
class EntityMatch:
    entity_key: str
    matched_text: str
    start_char: int
    end_char: int


def _normalize_candidates(candidates: Iterable[object] | None) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for raw in candidates or []:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        rows.append(text)
    rows.sort(key=lambda item: (-len(item), item.casefold(), item))
    return rows


def _is_ascii_token_surface(surface: str) -> bool:
    s = str(surface or "").strip()
    if not s or not s.isascii():
        return False
    return any(ch.isalnum() for ch in s)


def _compile_surface_pattern(surface: str) -> re.Pattern[str]:
    escaped = re.escape(surface)
    if _is_ascii_token_surface(surface):
        return re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", flags=re.IGNORECASE)
    return re.compile(escaped)


def _replace_span_with_spaces(text: str, start_char: int, end_char: int) -> str:
    start = max(0, int(start_char))
    end = max(start, int(end_char))
    return text[:start] + (" " * max(0, end - start)) + text[end:]


def find_entity_matches(
    text: str,
    candidates: Iterable[object] | None,
    *,
    max_matches: int = 32,
) -> list[EntityMatch]:
    """
    Match candidate entity surfaces in text with deterministic overlap handling.

    Strategy:
    - normalize and dedupe candidates
    - sort by surface length descending
    - for ASCII token-like entities, require token boundaries
    - after each match, replace the matched span in the working copy so shorter
      surfaces cannot "steal" substrings inside a longer matched entity
    """
    source = str(text or "")
    if not source:
        return []

    limit = max(0, int(max_matches or 0))
    if limit <= 0:
        return []

    working = source
    matches: list[EntityMatch] = []
    for entity_key in _normalize_candidates(candidates):
        pattern = _compile_surface_pattern(entity_key)
        while len(matches) < limit:
            found = pattern.search(working)
            if found is None:
                break
            start, end = int(found.start()), int(found.end())
            matches.append(
                EntityMatch(
                    entity_key=entity_key,
                    matched_text=source[start:end],
                    start_char=start,
                    end_char=end,
                )
            )
            working = _replace_span_with_spaces(working, start, end)
        if len(matches) >= limit:
            break

    matches.sort(key=lambda item: (item.start_char, item.end_char, item.entity_key.casefold()))
    return matches


def extract_partition_keys(
    text: str,
    candidates: Iterable[object] | None,
    *,
    max_keys: int = 8,
) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for match in find_entity_matches(text, candidates, max_matches=max_keys * 4):
        key = str(match.entity_key or "").strip()
        if not key:
            continue
        norm = key.casefold()
        if norm in seen:
            continue
        seen.add(norm)
        keys.append(key)
        if len(keys) >= max(0, int(max_keys or 0)):
            break
    return keys


__all__ = ["EntityMatch", "extract_partition_keys", "find_entity_matches"]
