from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GuardRule:
    name: str
    pattern: re.Pattern[str]
    score: float


ROLE_HIJACK_RULES: tuple[GuardRule, ...] = (
    GuardRule(
        name="role_hijack",
        pattern=re.compile(r"\b(?:you are now|act as|pretend to be|from now on you are)\b", re.IGNORECASE),
        score=0.45,
    ),
)

INSTRUCTION_OVERRIDE_RULES: tuple[GuardRule, ...] = (
    GuardRule(
        name="instruction_override",
        pattern=re.compile(
            r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+)?(?:previous|prior|above|system)\s+(?:instructions?|rules?)\b",
            re.IGNORECASE,
        ),
        score=0.82,
    ),
    GuardRule(
        name="new_instructions",
        pattern=re.compile(r"\b(?:new|different)\s+instructions?\b", re.IGNORECASE),
        score=0.55,
    ),
)

SYSTEM_PROMPT_PROBE_RULES: tuple[GuardRule, ...] = (
    GuardRule(
        name="system_prompt_probe",
        pattern=re.compile(
            r"\b(?:reveal|repeat|show|print|dump|expose)\b.{0,40}\b(?:system prompt|hidden instructions?|developer message)\b",
            re.IGNORECASE | re.DOTALL,
        ),
        score=0.85,
    ),
)

DELIMITER_ATTACK_RULES: tuple[GuardRule, ...] = (
    GuardRule(
        name="delimiter_attack",
        pattern=re.compile(r"(?:^|\n)\s*(?:---+|```+)\s*(?:system|assistant|developer)\s*:", re.IGNORECASE),
        score=0.62,
    ),
)

HTML_ENTITY_ATTACK_RE = re.compile(r"(?:&#x?[0-9a-f]{2,6};){4,}", re.IGNORECASE)
BASE64_BLOCK_RE = re.compile(r"\b[A-Za-z0-9+/]{24,}={0,2}\b")
ZERO_WIDTH_CHARS = {"\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"}


__all__ = [
    "BASE64_BLOCK_RE",
    "DELIMITER_ATTACK_RULES",
    "GuardRule",
    "HTML_ENTITY_ATTACK_RE",
    "INSTRUCTION_OVERRIDE_RULES",
    "ROLE_HIJACK_RULES",
    "SYSTEM_PROMPT_PROBE_RULES",
    "ZERO_WIDTH_CHARS",
]
