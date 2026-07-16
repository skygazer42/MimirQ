
from dataclasses import dataclass, field

from app.rag.safety.regex_prompt_screen import RegexPromptScreen
from app.rag.safety.regex_safety_guard import RegexSafetyGuard


@dataclass(frozen=True)
class LLMGuardResult:
    action: str
    triggered_guards: list[str] = field(default_factory=list)
    prompt_screen_label: str | None = None
    safety_guard_action: str | None = None


class LLMGuard:
    def __init__(self) -> None:
        self._prompt_screen = RegexPromptScreen()
        self._safety_guard = RegexSafetyGuard()

    async def guard_input(self, text: str) -> LLMGuardResult:
        prompt_result = await self._prompt_screen.check(str(text or ""))
        safety_result = await self._safety_guard.guard_user_input(str(text or ""))

        triggered: list[str] = []
        if prompt_result.label != "BENIGN":
            triggered.append("prompt_screen")
        if safety_result.action != "allow":
            triggered.append("safety_guard")

        action = "block" if "prompt_screen" in triggered or "safety_guard" in triggered else "allow"
        return LLMGuardResult(
            action=action,
            triggered_guards=triggered,
            prompt_screen_label=prompt_result.label,
            safety_guard_action=safety_result.action,
        )

    async def guard_output(self, text: str) -> LLMGuardResult:
        safety_result = await self._safety_guard.guard_agent_response(str(text or ""))
        triggered = ["safety_guard"] if safety_result.action != "allow" else []
        action = "block" if triggered else "allow"
        return LLMGuardResult(
            action=action,
            triggered_guards=triggered,
            prompt_screen_label=None,
            safety_guard_action=safety_result.action,
        )


__all__ = ["LLMGuard", "LLMGuardResult"]
