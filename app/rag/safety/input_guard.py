from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger
from app.rag.safety.metrics import observe_input_guard
from app.rag.safety.rules import (
    BASE64_BLOCK_RE,
    DELIMITER_ATTACK_RULES,
    HTML_ENTITY_ATTACK_RE,
    INSTRUCTION_OVERRIDE_RULES,
    ROLE_HIJACK_RULES,
    SYSTEM_PROMPT_PROBE_RULES,
    ZERO_WIDTH_CHARS,
)
from app.services.metrics_logger import log_metrics

logger = get_logger("rag.safety.input_guard")


@dataclass(frozen=True)
class GuardResult:
    action: str
    score: float
    matched_rules: list[str]


class InputGuard:
    """Best-effort prompt injection and jailbreak detector."""

    async def check(
        self,
        query: str,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> GuardResult:
        text = str(query or "")
        matched: dict[str, float] = {}

        def _record(rule_name: str, score: float) -> None:
            matched[rule_name] = max(float(matched.get(rule_name) or 0.0), float(score))

        for rule in ROLE_HIJACK_RULES:
            if rule.pattern.search(text):
                _record(rule.name, rule.score)
        for rule in INSTRUCTION_OVERRIDE_RULES:
            if rule.pattern.search(text):
                _record(rule.name, rule.score)
        for rule in SYSTEM_PROMPT_PROBE_RULES:
            if rule.pattern.search(text):
                _record(rule.name, rule.score)
        for rule in DELIMITER_ATTACK_RULES:
            if rule.pattern.search(text):
                _record(rule.name, rule.score)

        if HTML_ENTITY_ATTACK_RE.search(text):
            _record("html_entity_obfuscation", 0.75)
        if any(ch in text for ch in ZERO_WIDTH_CHARS):
            _record("zero_width_obfuscation", 0.78)

        base64_hits = 0
        for candidate in BASE64_BLOCK_RE.findall(text):
            if len(candidate) < 24:
                continue
            try:
                decoded = base64.b64decode(candidate, validate=True).decode("utf-8", errors="ignore").lower()
            except (binascii.Error, ValueError):
                continue
            if any(marker in decoded for marker in ("ignore previous", "system prompt", "developer message", "act as")):
                base64_hits += 1
        if base64_hits > 0:
            _record("base64_obfuscation", 0.82)

        history_hits = 0
        for msg in (conversation_history or [])[-4:]:
            if not isinstance(msg, dict):
                continue
            if str(msg.get("role") or "").strip().lower() != "user":
                continue
            content = str(msg.get("content") or "")
            if not content:
                continue
            if any(rule.pattern.search(content) for rule in INSTRUCTION_OVERRIDE_RULES + SYSTEM_PROMPT_PROBE_RULES):
                history_hits += 1
        if history_hits > 0:
            _record("indirect_injection_history", min(0.25 + (0.1 * history_hits), 0.55))

        score = min(1.0, sum(sorted(matched.values(), reverse=True)[:3]))
        matched_rules = sorted(matched.keys())
        action = self._resolve_action(score=score, matched_rules=matched_rules)
        result = GuardResult(action=action, score=round(score, 3), matched_rules=matched_rules)
        self._log_result(query=text, result=result)
        return result

    @staticmethod
    def _resolve_action(*, score: float, matched_rules: list[str]) -> str:
        if not matched_rules:
            return "allow"

        warn_threshold = float(getattr(settings, "INPUT_GUARD_WARN_THRESHOLD", 0.35) or 0.35)
        block_threshold = float(getattr(settings, "INPUT_GUARD_SCORE_THRESHOLD", 0.7) or 0.7)
        mode = str(getattr(settings, "INPUT_GUARD_MODE", "warn") or "warn").strip().lower()

        if score >= block_threshold:
            return "block" if mode == "block" else "warn"
        if score >= warn_threshold:
            return "warn"
        return "allow"

    @staticmethod
    def _log_result(*, query: str, result: GuardResult) -> None:
        query_hash = stable_hash(query or "")
        matched_rules = list(result.matched_rules or [])
        observe_input_guard(action=result.action, matched_rules=matched_rules)

        if result.action == "allow":
            return

        payload = {
            "event": "rag_input_guard",
            "action": result.action,
            "score": float(result.score or 0.0),
            "matched_rules": matched_rules,
            "query_hash": query_hash,
        }
        log_metrics(payload)

        if result.action == "block":
            if bool(getattr(settings, "INPUT_GUARD_LOG_BLOCKED", True)):
                logger.warning("Input guard blocked query hash=%s rules=%s score=%.3f", query_hash, matched_rules, result.score)
            return
        logger.warning("Input guard warning query hash=%s rules=%s score=%.3f", query_hash, matched_rules, result.score)


_INPUT_GUARD: InputGuard | None = None


def get_input_guard() -> InputGuard:
    global _INPUT_GUARD
    if _INPUT_GUARD is None:
        _INPUT_GUARD = InputGuard()
    return _INPUT_GUARD


__all__ = ["GuardResult", "InputGuard", "get_input_guard"]
