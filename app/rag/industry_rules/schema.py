from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IndustryRuleset:
    name: str
    glossary: dict[str, list[str]] = field(default_factory=dict)
    patterns: list[dict[str, object]] = field(default_factory=list)
    intents: list[dict[str, object]] = field(default_factory=list)
