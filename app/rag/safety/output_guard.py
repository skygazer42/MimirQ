from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from app.core.config import settings

_OUTPUT_GUARD_MODE_DEFAULT = "warn"
_OUTPUT_GUARD_SCORE_THRESHOLD_DEFAULT = 0.7
_OUTPUT_GUARD_WARN_THRESHOLD_DEFAULT = 0.35

_PHONE_RE = re.compile(r"\b1\d{10}\b")
_ID_CARD_RE = re.compile(r"\b\d{17}[\dXx]\b")
_FAKE_CITATION_RE = re.compile(r"第\s*999\s*页|page\s*999", flags=re.IGNORECASE)


@dataclass(frozen=True)
class OutputGuardResult:
    action: str = "allow"
    score: float = 0.0
    matched_rules: list[str] | None = None


class OutputGuard:
    """Best-effort output-side guard for obvious leakage and fabricated citation signals."""

    async def check(self, text: str) -> OutputGuardResult:
        return await asyncio.to_thread(self._check_sync, str(text or ""))

    def _check_sync(self, text: str) -> OutputGuardResult:
        matched: dict[str, float] = {}

        def _record(name: str, score: float) -> None:
            matched[name] = max(float(matched.get(name) or 0.0), float(score))

        if _PHONE_RE.search(text):
            _record("pii_phone", 0.72)
        if _ID_CARD_RE.search(text):
            _record("pii_id_card", 0.9)
        if _FAKE_CITATION_RE.search(text):
            _record("citation_fabrication_risk", 0.42)

        score = min(1.0, sum(sorted(matched.values(), reverse=True)[:3]))
        matched_rules = sorted(matched.keys())
        return OutputGuardResult(
            action=self._resolve_action(score=score, matched_rules=matched_rules),
            score=round(score, 3),
            matched_rules=matched_rules,
        )

    @staticmethod
    def _resolve_action(*, score: float, matched_rules: list[str]) -> str:
        if not matched_rules:
            return "allow"
        mode = str(getattr(settings, "OUTPUT_GUARD_MODE", _OUTPUT_GUARD_MODE_DEFAULT) or _OUTPUT_GUARD_MODE_DEFAULT).strip().lower()
        block_threshold = float(getattr(settings, "OUTPUT_GUARD_SCORE_THRESHOLD", _OUTPUT_GUARD_SCORE_THRESHOLD_DEFAULT) or _OUTPUT_GUARD_SCORE_THRESHOLD_DEFAULT)
        warn_threshold = float(getattr(settings, "OUTPUT_GUARD_WARN_THRESHOLD", _OUTPUT_GUARD_WARN_THRESHOLD_DEFAULT) or _OUTPUT_GUARD_WARN_THRESHOLD_DEFAULT)
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
