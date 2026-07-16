
import asyncio
import re
from dataclasses import dataclass

# Rule-based safety baseline. This is intentionally a lightweight regex screen,
# NOT a hosted classifier model. It exists so deployments have a zero-dependency
# default; wire a real model behind this interface when stronger guarantees are
# required (see docs/governance-rule-packs.md).

_PROMPT_INJECTION_RE = re.compile(
    r"忽略.*规则|绕过安全|系统提示词|ignore.*instruction|system prompt|developer message",
    flags=re.IGNORECASE,
)
_SENSITIVE_RE = re.compile(r"(?<!\d)1\d{10}(?!\d)|(?<!\d)\d{17}[\dXx](?!\d)")


def _action_for_score(score: float) -> str:
    if score >= 0.8:
        return "block"
    if score >= 0.35:
        return "warn"
    return "allow"


@dataclass(frozen=True)
class RegexSafetyGuardResult:
    action: str
    score: float
    categories: list[str]


class RegexSafetyGuard:
    """Regex-based input/response safety screen (rule baseline, not a model)."""

    async def guard_user_input(self, text: str) -> RegexSafetyGuardResult:
        return await asyncio.to_thread(self._check_user_input, str(text or ""))

    async def guard_agent_response(self, text: str) -> RegexSafetyGuardResult:
        return await asyncio.to_thread(self._check_agent_response, str(text or ""))

    @staticmethod
    def _check_user_input(text: str) -> RegexSafetyGuardResult:
        categories: list[str] = []
        if _PROMPT_INJECTION_RE.search(text):
            categories.append("prompt_injection")
        score = 0.86 if categories else 0.0
        action = _action_for_score(score)
        return RegexSafetyGuardResult(action=action, score=score, categories=categories)

    @staticmethod
    def _check_agent_response(text: str) -> RegexSafetyGuardResult:
        categories: list[str] = []
        if _SENSITIVE_RE.search(text):
            categories.append("sensitive_info")
        score = 0.82 if categories else 0.0
        action = _action_for_score(score)
        return RegexSafetyGuardResult(action=action, score=score, categories=categories)


__all__ = ["RegexSafetyGuard", "RegexSafetyGuardResult"]
