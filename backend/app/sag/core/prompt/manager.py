from typing import Dict

from app.sag.utils import get_logger

logger = get_logger("sag.prompt")


class PromptManager:
    """Very small prompt registry; extend as needed."""

    def __init__(self):
        self._prompts: Dict[str, str] = {}

    def register(self, name: str, template: str) -> None:
        self._prompts[name] = template

    def get(self, name: str) -> str:
        if name not in self._prompts:
            raise KeyError(f"Prompt '{name}' not found")
        return self._prompts[name]


_manager: PromptManager | None = None


def get_prompt_manager() -> PromptManager:
    global _manager
    if _manager is None:
        _manager = PromptManager()
    return _manager

