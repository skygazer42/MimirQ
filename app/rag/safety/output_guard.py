from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutputGuardResult:
    action: str = "allow"
    score: float = 0.0
    matched_rules: list[str] | None = None


class OutputGuard:
    """Phase 1 scaffold: output guard defaults to pass-through."""

    async def check(self, _text: str) -> OutputGuardResult:
        return OutputGuardResult(action="allow", score=0.0, matched_rules=[])


_OUTPUT_GUARD: OutputGuard | None = None


def get_output_guard() -> OutputGuard:
    global _OUTPUT_GUARD
    if _OUTPUT_GUARD is None:
        _OUTPUT_GUARD = OutputGuard()
    return _OUTPUT_GUARD


__all__ = ["OutputGuard", "OutputGuardResult", "get_output_guard"]
