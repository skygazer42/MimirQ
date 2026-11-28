"""Prompt bundles, their response contracts, and conversation-history formatting."""

from dataclasses import dataclass
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

_ANSWER_SEMANTICS_SYSTEM_MESSAGE = (
    "Stay within the user's requested subject and scope. Do not append records, backups, incidents, or advice merely "
    "because they share domain terms; include additional facts only when they directly support a requested conclusion. "
    "Answer each distinct requested amount or status separately. A computed payable or eligible amount is the amount "
    "available under the stated assumptions, not proof that payment or another action was completed. If the reference "
    "materials or a deterministic calculation contain a requested amount, report it explicitly. If a question asks for "
    "both a settlement amount (可结算) and a payable amount (可支付), give each as a separate labeled value. When its "
    "inputs and prerequisites are stated as satisfied, use the computed payable amount for 可支付; do not replace it "
    "with an actual-paid status. A missing transaction receipt means only that completed payment is unconfirmed."
)


def with_answer_semantics_system_message(prompt: ChatPromptTemplate) -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([("system", _ANSWER_SEMANTICS_SYSTEM_MESSAGE), *prompt.messages])


class BasePromptSchema(BaseModel):
    answer: str = Field(default="")
    citations: list[dict] = Field(default_factory=list)


class AssistantPromptSchema(BasePromptSchema):
    pass


class SummaryPromptSchema(BasePromptSchema):
    bullets: list[str] = Field(default_factory=list)
    summary: str = Field(default="")


class ActionItemsPromptSchema(BasePromptSchema):
    actions: list[dict] = Field(default_factory=list)


KB_ASSISTANT_ONESHOT = {
    "question": "What does the deployment guide require before starting the service?",
    "answer": "The guide requires configuring the environment variables before starting the service.",
    "citations": [{"document_id": "doc-1", "chunk_id": "chunk-1"}],
}


KB_SUMMARY_ONESHOT = {
    "answer": "The document explains MQTT broker setup for industrial gateways.",
    "citations": [{"document_id": "doc-2", "chunk_id": "chunk-2"}],
    "bullets": ["Broker host and port are configurable.", "Credentials must be updated for the field device."],
    "summary": "MQTT broker setup and connection parameters are covered.",
}


KB_ACTION_ITEMS_ONESHOT = {
    "answer": "Two concrete actions are described.",
    "citations": [{"document_id": "doc-3", "chunk_id": "chunk-3"}],
    "actions": [
        {"item": "Update the broker host", "owner": "", "due": ""},
        {"item": "Validate gateway credentials", "owner": "", "due": ""},
    ],
}


KB_ASSISTANT_SYSTEM_PROMPT = (
    "You are a retrieval-grounded enterprise knowledge assistant.\n"
    "Only answer from the provided context.\n"
    "If the answer is unsupported, say you cannot answer from the available materials.\n"
    "Keep answers concise, accurate, and citation-friendly."
)


KB_SUMMARY_SYSTEM_PROMPT = (
    "You are a retrieval-grounded summarization assistant.\n"
    "Summarize only what is supported by the supplied context.\n"
    "Prefer compact bullets and a short executive summary."
)


KB_ACTION_ITEMS_SYSTEM_PROMPT = (
    "You are a retrieval-grounded action-item extractor.\n"
    "Return only concrete, supported actions from the supplied context.\n"
    "Do not invent owners or deadlines when they are missing."
)


@dataclass(frozen=True)
class PromptBundle:
    key: str
    system_prompt: str
    response_model: type[BasePromptSchema]
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
            "Context:\n{context}\n\nQuestion:\n{question}\n\nReturn a concise summary with bullets and citations."
        ),
        oneshot_example=KB_SUMMARY_ONESHOT,
    ),
    "kb_action_items": PromptBundle(
        key="kb_action_items",
        system_prompt=KB_ACTION_ITEMS_SYSTEM_PROMPT,
        response_model=ActionItemsPromptSchema,
        template=(
            "Context:\n{context}\n\nQuestion:\n{question}\n\nReturn concrete supported action items and citations."
        ),
        oneshot_example=KB_ACTION_ITEMS_ONESHOT,
    ),
}


def get_prompt_bundle(key: str) -> PromptBundle:
    norm = key.strip().lower()
    if norm not in PROMPT_BUNDLES:
        raise KeyError(f"Unknown prompt bundle: {key}")
    return PROMPT_BUNDLES[norm]


def list_prompt_bundles() -> list[PromptBundle]:
    return [PROMPT_BUNDLES[key] for key in sorted(PROMPT_BUNDLES)]


def format_history_text(
    history: list[dict[str, Any]] | None,
    *,
    window: int,
    empty_placeholder: str = "(No conversation history)",
    user_label: str = "User",
    assistant_label: str = "Assistant",
) -> str:
    """
    Format chat history into a prompt-friendly text block.

    Supports a list of dict messages like: {"role": "user"|"assistant", "content": "..."}.
    """
    if not history:
        return empty_placeholder

    window = max(int(window or 0), 0)
    if not window:
        return empty_placeholder

    hist_slice = _with_latest_system_message(history, history[-window:])
    parts = [
        _format_history_message(message, user_label=user_label, assistant_label=assistant_label)
        for message in hist_slice
    ]

    text = "\n\n".join(parts).strip()
    return text or empty_placeholder


def _message_value(message: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(field_name, default)
    return getattr(message, field_name, default)


def _with_latest_system_message(history: list[Any], window_messages: list[Any]) -> list[Any]:
    """Keep summary memory available even when it falls outside the rolling window."""
    latest_system = next(
        (message for message in reversed(history) if _message_value(message, "role") == "system"),
        None,
    )
    if latest_system is None or latest_system in window_messages:
        return window_messages
    return [latest_system, *window_messages]


def _format_history_message(message: Any, *, user_label: str, assistant_label: str) -> str:
    role_value = _message_value(message, "role")
    content = _message_value(message, "content", "")
    if role_value == "system":
        role = "System"
    else:
        role = user_label if role_value == "user" else assistant_label
    return f"{role}: {content}"


__all__ = [
    "KB_ASSISTANT_ONESHOT",
    "KB_SUMMARY_ONESHOT",
    "KB_ACTION_ITEMS_ONESHOT",
    "KB_ASSISTANT_SYSTEM_PROMPT",
    "KB_SUMMARY_SYSTEM_PROMPT",
    "KB_ACTION_ITEMS_SYSTEM_PROMPT",
    "BasePromptSchema",
    "AssistantPromptSchema",
    "SummaryPromptSchema",
    "ActionItemsPromptSchema",
    "PROMPT_BUNDLES",
    "PromptBundle",
    "get_prompt_bundle",
    "list_prompt_bundles",
    "format_history_text",
]
