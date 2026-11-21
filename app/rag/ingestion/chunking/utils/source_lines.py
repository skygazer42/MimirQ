"""Shared source-line spans for structured text chunkers."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceLine:
    start: int
    end: int
    plain: str


def iter_source_lines(text: str) -> list[SourceLine]:
    lines: list[SourceLine] = []
    offset = 0
    for raw in (text).splitlines(keepends=True):
        start = offset
        end = start + len(raw)
        offset = end
        lines.append(SourceLine(start=start, end=end, plain=raw.rstrip("\r\n")))
    return lines


def apply_splitter_span(
    metadata: dict[str, Any], *, start_index: int | None, content: str, base_offset: int = 0
) -> None:
    """Record an SDK splitter span without inventing a missing source position."""
    if start_index is None or start_index < 0:
        metadata["start_char"] = None
        metadata["end_char"] = None
        metadata["offset_mapping_error"] = "splitter_start_index_unavailable"
        return
    metadata["start_char"] = base_offset + start_index
    metadata["end_char"] = base_offset + start_index + len(content)


__all__ = ["SourceLine", "apply_splitter_span", "iter_source_lines"]
