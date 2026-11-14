"""Shared source-line spans for structured text chunkers."""

from dataclasses import dataclass


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


__all__ = ["SourceLine", "iter_source_lines"]
