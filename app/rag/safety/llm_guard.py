from __future__ import annotations

from dataclasses import dataclass, field

from app.rag.safety.llama_guard import LlamaGuard
from app.rag.safety.prompt_guard import PromptGuard


@dataclass(frozen=True)
class LLMGuardResult:
    action: str
    triggered_guards: list[str] = field(default_factory=list)
    prompt_guard_label: str | None = None
    llama_guard_action: str | None = None


class LLMGuard:
    def __init__(self) -> None:
        self._prompt_guard = PromptGuard()
        self._llama_guard = LlamaGuard()

    async def guard_input(self, text: str) -> LLMGuardResult:
        prompt_result = await self._prompt_guard.check(str(text or ""))
        llama_result = await self._llama_guard.guard_user_input(str(text or ""))

        triggered: list[str] = []
        if prompt_result.label != "BENIGN":
            triggered.append("prompt_guard")
        if llama_result.action != "allow":
            triggered.append("llama_guard")

        action = "block" if "prompt_guard" in triggered or "llama_guard" in triggered else "allow"
        return LLMGuardResult(
            action=action,
            triggered_guards=triggered,
            prompt_guard_label=prompt_result.label,
            llama_guard_action=llama_result.action,
        )

    async def guard_output(self, text: str) -> LLMGuardResult:
        llama_result = await self._llama_guard.guard_agent_response(str(text or ""))
        triggered = ["llama_guard"] if llama_result.action != "allow" else []
        action = "block" if triggered else "allow"
        return LLMGuardResult(
            action=action,
            triggered_guards=triggered,
            prompt_guard_label=None,
            llama_guard_action=llama_result.action,
        )


__all__ = ["LLMGuard", "LLMGuardResult"]
