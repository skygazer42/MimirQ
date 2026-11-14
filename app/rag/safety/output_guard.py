import asyncio
import re
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.rag.safety.regex_safety_guard import RegexSafetyGuard

_PHONE_RE = re.compile(r"(?<!\d)1\d{10}(?!\d)")
_ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_FAKE_CITATION_RE = re.compile(r"第\s*999\s*页|page\s*999", flags=re.IGNORECASE)
_CN_ENTITY_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")


@dataclass(frozen=True)
class OutputGuardResult:
    action: str = "allow"
    score: float = 0.0
    matched_rules: list[str] | None = None
    details: dict[str, Any] | None = None


class OutputGuard:
    """Best-effort output-side guard for obvious leakage and fabricated citation signals."""

    def __init__(self) -> None:
        self._safety_guard = RegexSafetyGuard()

    async def check(
        self,
        text: str,
        *,
        context_chunks: list[str] | None = None,
        question: str | None = None,
        tenant: str | None = None,
    ) -> OutputGuardResult:
        del question, tenant  # reserved for future topic policy
        sync_result = await asyncio.to_thread(
            self._check_sync,
            text,
            list(context_chunks or []),
        )
        safety_result = await self._safety_guard.guard_agent_response(text)
        matched_rules = list(sync_result.matched_rules)
        details = dict(sync_result.details)
        score = float(sync_result.score)

        if safety_result.action != "allow":
            matched_rules.append("safety_guard_response")
            details["safety_guard_action"] = safety_result.action
            score = min(1.0, max(score, 0.9))

        matched_rules = sorted(set(matched_rules))
        return OutputGuardResult(
            action=self._resolve_action(score=score, matched_rules=matched_rules),
            score=round(score, 3),
            matched_rules=matched_rules,
            details=details,
        )

    def _check_sync(self, text: str, context_chunks: list[str]) -> OutputGuardResult:
        matched: dict[str, float] = {}
        details: dict[str, Any] = {}

        if _PHONE_RE.search(text):
            matched["pii_phone"] = 0.72
        if _ID_CARD_RE.search(text):
            matched["pii_id_card"] = 0.9
        if _FAKE_CITATION_RE.search(text):
            matched["citation_fabrication_risk"] = 0.42

        context_text = " ".join(item for item in context_chunks if item.strip())
        if context_text:
            answer_entities = {item for item in _CN_ENTITY_RE.findall(text) if len(item) >= 4}
            context_entities = {item for item in _CN_ENTITY_RE.findall(context_text) if len(item) >= 4}
            missing = sorted(entity for entity in answer_entities if entity not in context_entities)
            if missing:
                matched["citation_consistency"] = 0.41
                details["missing_entities"] = missing[:10]

        score = min(1.0, sum(sorted(matched.values(), reverse=True)[:3]))
        matched_rules = sorted(matched.keys())
        return OutputGuardResult(
            action=self._resolve_action(score=score, matched_rules=matched_rules),
            score=round(score, 3),
            matched_rules=matched_rules,
            details=details,
        )

    @staticmethod
    def _resolve_action(*, score: float, matched_rules: list[str]) -> str:
        if not matched_rules:
            return "allow"
        mode = settings.OUTPUT_GUARD_MODE
        block_threshold = float(settings.OUTPUT_GUARD_SCORE_THRESHOLD)
        warn_threshold = float(settings.OUTPUT_GUARD_WARN_THRESHOLD)
        if score >= block_threshold:
            return "block" if mode == "block" else "warn"
        if score >= warn_threshold:
            return "warn"
        return "allow"


_OUTPUT_GUARD: OutputGuard | None = None


def get_output_guard() -> OutputGuard:
    global _OUTPUT_GUARD
    if _OUTPUT_GUARD is None:
        _OUTPUT_GUARD = OutputGuard()
    return _OUTPUT_GUARD


__all__ = ["OutputGuard", "OutputGuardResult", "get_output_guard"]
