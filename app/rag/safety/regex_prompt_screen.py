
import asyncio
import re
from dataclasses import dataclass

# Rule-based prompt screening. This is intentionally a lightweight regex screen,
# NOT a hosted classifier model. Wire a real prompt-injection classifier behind
# this interface when stronger guarantees are required.

_INJECTION_RE = re.compile(r"忽略.*规则|ignore.*instruction|system prompt", flags=re.IGNORECASE)
_JAILBREAK_RE = re.compile(r"\bDAN\b|角色扮演|越狱|act as root", flags=re.IGNORECASE)


@dataclass(frozen=True)
class RegexPromptScreenResult:
    label: str
    confidence: float
    matched_rules: list[str]


class RegexPromptScreen:
    """Regex-based prompt injection/jailbreak screen (rule baseline, not a model)."""

    async def check(self, text: str) -> RegexPromptScreenResult:
        return await asyncio.to_thread(self._check_sync, str(text or ""))

    @staticmethod
    def _check_sync(text: str) -> RegexPromptScreenResult:
        matched: list[str] = []
        if _INJECTION_RE.search(text):
            matched.append("injection")
        if _JAILBREAK_RE.search(text):
            matched.append("jailbreak")
        if "jailbreak" in matched:
            return RegexPromptScreenResult(label="JAILBREAK", confidence=0.9, matched_rules=matched)
        if "injection" in matched:
            return RegexPromptScreenResult(label="INJECTION", confidence=0.82, matched_rules=matched)
        return RegexPromptScreenResult(label="BENIGN", confidence=0.92, matched_rules=[])


__all__ = ["RegexPromptScreen", "RegexPromptScreenResult"]
