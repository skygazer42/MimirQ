from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

_PROMPT_INJECTION_RE = re.compile(
    r"忽略.*规则|绕过安全|系统提示词|ignore.*instruction|system prompt|developer message",
    flags=re.IGNORECASE,
)
_SENSITIVE_RE = re.compile(r"\b1\d{10}\b|\b\d{17}[\dXx]\b")


@dataclass(frozen=True)
class LlamaGuardResult:
    action: str
    score: float
    categories: list[str]


class LlamaGuard:
    async def guard_user_input(self, text: str) -> LlamaGuardResult:
        return await asyncio.to_thread(self._check_user_input, str(text or ""))

    async def guard_agent_response(self, text: str) -> LlamaGuardResult:
        return await asyncio.to_thread(self._check_agent_response, str(text or ""))

    @staticmethod
    def _check_user_input(text: str) -> LlamaGuardResult:
        categories: list[str] = []
        if _PROMPT_INJECTION_RE.search(text):
            categories.append("prompt_injection")
        score = 0.86 if categories else 0.0
        action = "block" if score >= 0.8 else ("warn" if score >= 0.35 else "allow")
        return LlamaGuardResult(action=action, score=score, categories=categories)

    @staticmethod
    def _check_agent_response(text: str) -> LlamaGuardResult:
        categories: list[str] = []
        if _SENSITIVE_RE.search(text):
            categories.append("sensitive_info")
        score = 0.82 if categories else 0.0
        action = "block" if score >= 0.8 else ("warn" if score >= 0.35 else "allow")
        return LlamaGuardResult(action=action, score=score, categories=categories)


__all__ = ["LlamaGuard", "LlamaGuardResult"]
