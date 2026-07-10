
from dataclasses import dataclass
from typing import Any

from app.rag.llm.prompts.oneshots import (
    KB_ACTION_ITEMS_ONESHOT,
    KB_ASSISTANT_ONESHOT,
    KB_SUMMARY_ONESHOT,
)
from app.rag.llm.prompts.schemas import (
    ActionItemsPromptSchema,
    AssistantPromptSchema,
    SummaryPromptSchema,
)
from app.rag.llm.prompts.system_prompts import (
    KB_ACTION_ITEMS_SYSTEM_PROMPT,
    KB_ASSISTANT_SYSTEM_PROMPT,
    KB_SUMMARY_SYSTEM_PROMPT,
)


@dataclass(frozen=True)
class PromptBundle:
    key: str
    system_prompt: str
    response_model: type
    template: str
    oneshot_example: dict[str, Any]

    def render(self) -> str:
        schema_json = self.response_model.model_json_schema()
        return "\n\n".join(
            [
                "[System Prompt]",
                self.system_prompt,
                "[Template]",
                self.template,
                "[Schema]",
                str(schema_json),
                "[One-shot Example]",
                str(self.oneshot_example),
            ]
        )


PROMPT_BUNDLES: dict[str, PromptBundle] = {
    "kb_assistant": PromptBundle(
        key="kb_assistant",
        system_prompt=KB_ASSISTANT_SYSTEM_PROMPT,
        response_model=AssistantPromptSchema,
        template=(
            "Context:\n{context}\n\n"
            "History:\n{history}\n\n"
            "Question:\n{question}\n\n"
            "Return a grounded answer with citations."
        ),
        oneshot_example=KB_ASSISTANT_ONESHOT,
    ),
    "kb_summary": PromptBundle(
        key="kb_summary",
        system_prompt=KB_SUMMARY_SYSTEM_PROMPT,
        response_model=SummaryPromptSchema,
        template=(
            "Context:\n{context}\n\n"
            "Question:\n{question}\n\n"
            "Return a concise summary with bullets and citations."
        ),
        oneshot_example=KB_SUMMARY_ONESHOT,
    ),
    "kb_action_items": PromptBundle(
        key="kb_action_items",
        system_prompt=KB_ACTION_ITEMS_SYSTEM_PROMPT,
        response_model=ActionItemsPromptSchema,
        template=(
            "Context:\n{context}\n\n"
            "Question:\n{question}\n\n"
            "Return concrete supported action items and citations."
        ),
        oneshot_example=KB_ACTION_ITEMS_ONESHOT,
    ),
}


def get_prompt_bundle(key: str) -> PromptBundle:
    norm = str(key or "").strip().lower()
    if norm not in PROMPT_BUNDLES:
        raise KeyError(f"Unknown prompt bundle: {key}")
    return PROMPT_BUNDLES[norm]


def list_prompt_bundles() -> list[PromptBundle]:
    return [PROMPT_BUNDLES[key] for key in sorted(PROMPT_BUNDLES)]


__all__ = ["PROMPT_BUNDLES", "PromptBundle", "get_prompt_bundle", "list_prompt_bundles"]
