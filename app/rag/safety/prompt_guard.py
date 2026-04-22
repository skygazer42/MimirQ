from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass


_INJECTION_RE = re.compile(r"忽略.*规则|ignore.*instruction|system prompt", flags=re.IGNORECASE)
_JAILBREAK_RE = re.compile(r"\bDAN\b|角色扮演|越狱|act as root", flags=re.IGNORECASE)


@dataclass(frozen=True)
class PromptGuardResult:
    label: str
    confidence: float
    matched_rules: list[str]


class PromptGuard:
    async def check(self, text: str) -> PromptGuardResult:
        return await asyncio.to_thread(self._check_sync, str(text or ""))

    @staticmethod
    def _check_sync(text: str) -> PromptGuardResult:
        matched: list[str] = []
        if _INJECTION_RE.search(text):
            matched.append("injection")
        if _JAILBREAK_RE.search(text):
            matched.append("jailbreak")
        if "jailbreak" in matched:
            return PromptGuardResult(label="JAILBREAK", confidence=0.9, matched_rules=matched)
        if "injection" in matched:
            return PromptGuardResult(label="INJECTION", confidence=0.82, matched_rules=matched)
        return PromptGuardResult(label="BENIGN", confidence=0.92, matched_rules=[])


__all__ = ["PromptGuard", "PromptGuardResult"]
